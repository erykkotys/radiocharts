from __future__ import annotations

import asyncio
import datetime as dt
import ftplib
import logging
import os
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from zoneinfo import ZoneInfo

from .db import Database
from .patterns import normalize_relative, pattern_day, preview_path, safe_join
from .schedules import matches_date


LOGGER = logging.getLogger(__name__)
POLL_SECONDS = 30
MIRROR_TIMEOUT_SECONDS = 30 * 60
_SHOW_LOCKS: dict[int, threading.Lock] = {}
_SHOW_LOCKS_GUARD = threading.Lock()


@dataclass(frozen=True)
class FtpCredentials:
    host: str
    username: str
    password: str
    port: int = 21
    charset: str = "UTF-8"


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def read_ftp_credentials(path: str | Path) -> FtpCredentials:
    credential_path = Path(path)
    try:
        lines = credential_path.read_text(encoding="utf-8-sig").splitlines()
    except FileNotFoundError as exc:
        raise RuntimeError(f"Brak pliku danych FTP: {credential_path}") from exc
    except PermissionError as exc:
        raise RuntimeError(f"Brak prawa odczytu pliku danych FTP: {credential_path}") from exc

    values: dict[str, str] = {}
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("export "):
            line = line[7:].strip()
        separator = "=" if "=" in line else (":" if ":" in line else None)
        if separator is None:
            pair = line.split(None, 1)
            if len(pair) != 2:
                continue
            key, value = pair
        else:
            key, value = line.split(separator, 1)
        canonical_key = key.strip().lower().replace("-", "_")
        aliases = {
            "ftp_host": "host", "ftp_server": "host", "server": "host", "hostname": "host",
            "ftp_username": "username", "ftp_user": "username", "ftp_login": "username", "user": "username", "login": "username",
            "ftp_password": "password", "ftp_pass": "password", "pass": "password", "passwd": "password",
            "ftp_port": "port", "ftp_charset": "charset", "encoding": "charset",
        }
        values[aliases.get(canonical_key, canonical_key)] = _unquote(value.strip())
    missing = [key for key in ("host", "username", "password") if not values.get(key)]
    if missing:
        raise RuntimeError("W pliku danych FTP brakuje pól: " + ", ".join(missing))
    try:
        port = int(values.get("port", "21"))
    except ValueError as exc:
        raise RuntimeError("Nieprawidłowy port w pliku danych FTP") from exc
    return FtpCredentials(
        host=values["host"],
        username=values["username"],
        password=values["password"],
        port=port,
        charset=values.get("charset", "UTF-8") or "UTF-8",
    )


def normalize_remote_path(value: str) -> str:
    value = str(value or "").replace("\\", "/").strip()
    if any(character in value for character in ("\0", "\n", "\r")):
        raise ValueError("Nieprawidłowa ścieżka FTP")
    if not value.startswith("/"):
        value = "/" + value
    path = PurePosixPath(value)
    if ".." in path.parts:
        raise ValueError("Ścieżka FTP nie może zawierać '..'")
    return "/" if str(path) == "/" else "/" + str(path).strip("/")


def ftp_destination_relative(show: dict[str, Any]) -> str:
    """Return stable show root, before any date-driven folder segment."""
    folder = normalize_relative(show.get("folder_pattern", ""))
    stable_parts: list[str] = []
    for part in PurePosixPath(folder).parts:
        if "%" in part or "(%d" in part:
            break
        stable_parts.append(part)
    return PurePosixPath(*stable_parts).as_posix() if stable_parts else ""


def _lftp_quote(value: str) -> str:
    if any(character in value for character in ("\0", "\n", "\r")):
        raise ValueError("Niedozwolony znak w konfiguracji FTP")
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    escaped = escaped.replace("$", "\\$").replace("`", "\\`")
    return f'"{escaped}"'


def _show_lock(show_id: int) -> threading.Lock:
    with _SHOW_LOCKS_GUARD:
        return _SHOW_LOCKS.setdefault(show_id, threading.Lock())


def mirror_ftp_show(
    show: dict[str, Any], media_root: Path, credentials_path: str | Path
) -> dict[str, Any]:
    if not show.get("is_ftp"):
        raise ValueError("Audycja nie ma włączonego pobierania z FTP")
    source = normalize_remote_path(show.get("ftp_source_path", ""))
    if source == "/":
        raise ValueError("Wybierz folder źródłowy na FTP")
    credentials = read_ftp_credentials(credentials_path)
    destination_relative = ftp_destination_relative(show)
    destination = safe_join(media_root, destination_relative)
    destination.mkdir(parents=True, exist_ok=True)
    lock = _show_lock(int(show["id"]))
    if not lock.acquire(blocking=False):
        raise RuntimeError("Pobieranie tej audycji już trwa")
    try:
        host = credentials.host
        if "://" not in host:
            host = f"ftp://{host}:{credentials.port}"
        script = "\n".join(
            [
                "set cmd:fail-exit yes",
                "set net:max-retries 2",
                "set net:timeout 20",
                "set ftp:passive-mode true",
                f"set ftp:charset {_lftp_quote(credentials.charset)}",
                'set file:charset "UTF-8"',
                f"open -u {_lftp_quote(credentials.username)},{_lftp_quote(credentials.password)} {_lftp_quote(host)}",
                f"mirror --continue --verbose=3 {_lftp_quote(source)} {_lftp_quote(str(destination))}",
                "bye",
            ]
        ) + "\n"
        try:
            result = subprocess.run(
                ["lftp", "-f", "/dev/stdin"],
                input=script,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=MIRROR_TIMEOUT_SECONDS,
                check=False,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("W obrazie Docker nie ma programu lftp") from exc
        except subprocess.TimeoutExpired as exc:
            timeout_output = exc.stdout or ""
            if isinstance(timeout_output, bytes):
                timeout_output = timeout_output.decode("utf-8", errors="replace")
            timeout_output = str(timeout_output).replace(credentials.password, "***").strip()
            detail = f"Pobieranie FTP przekroczyło limit 30 minut.\n{timeout_output[-10000:]}".strip()
            raise RuntimeError(detail) from exc
        output = (result.stdout or "").replace(credentials.password, "***").strip()
        if result.returncode:
            raise RuntimeError(
                f"lftp zakończył pobieranie błędem (kod {result.returncode}).\n"
                f"Źródło: {source}\nCel: {destination}\n"
                f"Odpowiedź serwera / log lftp:\n{output[-10000:] or '(brak dodatkowej odpowiedzi)'}"
            )
        return {
            "ok": True,
            "source": source,
            "destination": f"/AUDYCJE/{destination_relative}".rstrip("/"),
            "detail": (
                f"Źródło: {source}\nCel: {destination}\nLog lftp:\n"
                f"{output[-10000:] or '(brak zmian do pobrania)'}"
            ),
        }
    finally:
        lock.release()


def browse_ftp_directories(path: str, credentials_path: str | Path) -> dict[str, Any]:
    credentials = read_ftp_credentials(credentials_path)
    current = normalize_remote_path(path or "/")
    try:
        with ftplib.FTP(timeout=25, encoding=credentials.charset) as connection:
            connection.connect(credentials.host, credentials.port)
            connection.login(credentials.username, credentials.password)
            connection.cwd(current)
            entries = []
            try:
                for name, facts in connection.mlsd(facts=["type"]):
                    if name not in {".", ".."} and facts.get("type") == "dir":
                        entries.append(name)
            except (ftplib.error_perm, AttributeError):
                for item in connection.nlst():
                    name = PurePosixPath(item).name
                    if name in {".", ".."}:
                        continue
                    try:
                        connection.cwd(name)
                        entries.append(name)
                    except ftplib.Error:
                        pass
                    finally:
                        connection.cwd(current)
    except (OSError, UnicodeError, ftplib.Error) as exc:
        raise RuntimeError(f"Nie udało się odczytać folderów FTP: {exc}") from exc
    entries = sorted(set(entries), key=str.casefold)
    parent = None if current == "/" else str(PurePosixPath(current).parent)
    return {
        "path": current,
        "parent": parent,
        "entries": [
            {"name": name, "path": str(PurePosixPath(current, name)), "type": "directory"}
            for name in entries
        ],
    }


def _patterns(occurrence: dict[str, Any]) -> list[str]:
    values = occurrence.get("filename_patterns") or [occurrence.get("filename_pattern", "")]
    return [str(value) for value in values if str(value).strip()]


def _source_relative(show: dict[str, Any], source_pattern: str, day: dt.date) -> str:
    shifted_day, source_mask = pattern_day(normalize_relative(source_pattern), day)
    folder = shifted_day.strftime(normalize_relative(show.get("folder_pattern", "")))
    filename = shifted_day.strftime(source_mask)
    return PurePosixPath(folder, filename).as_posix()


def ftp_source_status(
    show: dict[str, Any], occurrence: dict[str, Any], day: dt.date, media_root: Path
) -> list[dict[str, Any]]:
    source_patterns = show.get("ftp_source_patterns") or []
    targets = _patterns(occurrence)
    statuses: list[dict[str, Any]] = []
    for index, pattern in enumerate(source_patterns):
        relative = _source_relative(show, str(pattern), day)
        source = safe_join(media_root, relative)
        target_relative = (
            preview_path(occurrence.get("folder_pattern", ""), targets[index], day)
            if index < len(targets)
            else None
        )
        target = safe_join(media_root, target_relative) if target_relative else None
        source_found = source.is_file()
        target_found = bool(target and target.is_file())
        renamed = False
        if target_found and target is not None:
            if source.resolve() == target.resolve() or not source_found:
                renamed = True
            else:
                try:
                    source_stat = source.stat()
                    target_stat = target.stat()
                    renamed = (
                        source_stat.st_size == target_stat.st_size
                        and target_stat.st_mtime_ns >= source_stat.st_mtime_ns
                    )
                except OSError:
                    renamed = False
        statuses.append(
            {
                "part_number": index + 1,
                "found": source_found,
                "relative_path": relative,
                "target_relative_path": target_relative,
                "target_found": target_found,
                "renamed": renamed,
            }
        )
    return statuses


def rename_ftp_files(
    show: dict[str, Any], day: dt.date, media_root: Path, repeat_id: str | None = None
) -> dict[str, Any]:
    lock = _show_lock(int(show["id"]))
    if not lock.acquire(blocking=False):
        raise RuntimeError("Pobieranie lub przemianowanie tej audycji już trwa")
    try:
        return _rename_ftp_files_unlocked(show, day, media_root, repeat_id)
    finally:
        lock.release()


def _rename_ftp_files_unlocked(
    show: dict[str, Any], day: dt.date, media_root: Path, repeat_id: str | None = None
) -> dict[str, Any]:
    if not show.get("is_ftp") or not show.get("ftp_rename_enabled"):
        raise ValueError("Dla tej audycji nie włączono innego schematu nazwy")
    occurrence = show
    if repeat_id:
        occurrence = next((item for item in show.get("repeats", []) if item["id"] == repeat_id), None)
        if occurrence is None:
            raise ValueError("Nie znaleziono powtórki")
    targets = _patterns(occurrence)
    sources = show.get("ftp_source_patterns") or []
    if len(sources) != len(targets):
        raise ValueError("Liczba schematów źródłowych nie odpowiada liczbie plików docelowych")
    copies: list[dict[str, str]] = []
    for index, source_pattern in enumerate(sources):
        source_relative = _source_relative(show, str(source_pattern), day)
        target_relative = preview_path(occurrence.get("folder_pattern", ""), targets[index], day)
        source = safe_join(media_root, source_relative)
        target = safe_join(media_root, target_relative)
        if not source.is_file():
            raise FileNotFoundError(f"Brak pliku źródłowego: /AUDYCJE/{source_relative}")
        if source.resolve() != target.resolve():
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f".{target.name}.ftp-copy.tmp")
            try:
                shutil.copy2(source, temporary)
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        copies.append({"source": source_relative, "target": target_relative})
    return {"ok": True, "copied": len(copies), "files": copies}


def _last_scheduled_hour(show: dict[str, Any], day: dt.date) -> int | None:
    scheduled: list[dict[str, Any]] = [
        slot for slot in show.get("premiere_slots", [])
        if matches_date(slot.get("schedule", []), day)
    ]
    if not show.get("premiere_slots") and matches_date(show.get("schedule", []), day):
        scheduled.append(show)
    scheduled.extend(
        repeat for repeat in show.get("repeats", []) if matches_date(repeat.get("schedule", []), day)
    )
    if not scheduled:
        return None
    if any(not (occurrence.get("emission_times") or occurrence.get("emission_time")) for occurrence in scheduled):
        return 23
    hours: list[int] = []
    for occurrence in scheduled:
        times = occurrence.get("emission_times") or [occurrence.get("emission_time")]
        hours.extend(int(str(value).split(":", 1)[0]) for value in times if value)
    return max(hours) if hours else 23


def _ftp_schedule_entries(show: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    premiere_slots = show.get("premiere_slots") or []
    if premiere_slots:
        for index, slot in enumerate(premiere_slots):
            entries.append({
                "label": slot.get("label") or f"Premiera {index + 1}",
                "description": slot.get("schedule_description") or "Brak emisji",
                "times": slot.get("emission_times") or [],
            })
    elif show.get("schedule"):
        entries.append({
            "label": "Premiera",
            "description": show.get("schedule_description") or "Brak emisji",
            "times": show.get("emission_times") or [],
        })
    for index, repeat in enumerate(show.get("repeats") or []):
        entries.append({
            "label": repeat.get("label") or f"Powtórka {index + 1}",
            "description": repeat.get("schedule_description") or "Brak emisji",
            "times": repeat.get("emission_times") or [],
        })
    return entries


def _next_automatic_ftp_run(
    show: dict[str, Any],
    now: dt.datetime,
    claimed: set[tuple[int, str, int]],
) -> dt.datetime | None:
    show_id = int(show["id"])
    for offset in range(367):
        day = now.date() + dt.timedelta(days=offset)
        first_hour = now.hour if offset == 0 else 0
        for hour in range(first_hour, 24):
            key = (show_id, day.isoformat(), hour)
            if key in claimed:
                continue
            candidate = dt.datetime.combine(day, dt.time(hour), tzinfo=now.tzinfo)
            return now if candidate <= now else candidate
    return None


def _local_log_time(value: str, timezone: ZoneInfo) -> str:
    try:
        parsed = dt.datetime.fromisoformat(str(value)).replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return str(value)
    return parsed.astimezone(timezone).isoformat(timespec="seconds")


def build_ftp_task_overview(
    database: Database,
    timezone_name: str = "Europe/Warsaw",
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    timezone = ZoneInfo(timezone_name)
    if now is None:
        now = dt.datetime.now(timezone)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone)
    else:
        now = now.astimezone(timezone)

    history_rows = database.ftp_sync_history(500)
    claimed = {
        (int(row["show_id"]), str(row["emission_date"]), int(row["hour_slot"]))
        for row in history_rows
        if row.get("trigger") == "automatic"
    }
    latest_by_show: dict[int, dict[str, Any]] = {}
    history: list[dict[str, Any]] = []
    for row in history_rows:
        normalized = {
            **row,
            "show_name": row.get("show_name") or f"Audycja #{row['show_id']}",
            "created_at": _local_log_time(row["created_at"], timezone),
            "updated_at": _local_log_time(row["updated_at"], timezone),
        }
        latest_by_show.setdefault(int(row["show_id"]), normalized)
        if len(history) < 100:
            history.append(normalized)

    tasks: list[dict[str, Any]] = []
    for show in database.list_shows(include_inactive=False):
        if not (
            show.get("is_ftp")
            and show.get("ftp_auto_sync")
            and show.get("ftp_source_path")
        ):
            continue
        next_run = _next_automatic_ftp_run(show, now, claimed)
        tasks.append({
            "show_id": show["id"],
            "name": show["name"],
            "source": normalize_remote_path(show["ftp_source_path"]),
            "destination": f"/AUDYCJE/{ftp_destination_relative(show)}".rstrip("/"),
            "schedule": _ftp_schedule_entries(show),
            "rule": "Co godzinę, codziennie",
            "today_until_hour": 23,
            "today_active": True,
            "next_run": next_run.isoformat(timespec="seconds") if next_run else None,
            "last_run": latest_by_show.get(int(show["id"])),
        })

    today = now.date().isoformat()
    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "summary": {
            "tasks": len(tasks),
            "synced_today": sum(
                1 for row in history_rows
                if row["emission_date"] == today and row["status"] == "synced"
            ),
            "failed_today": sum(
                1 for row in history_rows
                if row["emission_date"] == today and row["status"] == "failed"
            ),
            "running": sum(
                1 for row in latest_by_show.values()
                if row["status"] == "pending"
                and row["emission_date"] == today
                and int(row["hour_slot"]) == now.hour
            ),
        },
        "items": tasks,
        "history": history,
    }


def process_automatic_ftp_once(
    database: Database,
    media_root: Path,
    credentials_path: str | Path,
    now: dt.datetime | None = None,
    timezone_name: str = "Europe/Warsaw",
) -> dict[str, int]:
    timezone = ZoneInfo(timezone_name)
    if now is None:
        now = dt.datetime.now(timezone)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone)
    else:
        now = now.astimezone(timezone)
    result = {"synced": 0, "failed": 0, "skipped": 0}
    for show in database.list_shows(include_inactive=False):
        if not show.get("is_ftp") or not show.get("ftp_auto_sync") or not show.get("ftp_source_path"):
            continue
        if not database.claim_ftp_sync(show["id"], now.date().isoformat(), now.hour):
            result["skipped"] += 1
            continue
        try:
            sync_result = mirror_ftp_show(show, media_root, credentials_path)
        except Exception as exc:
            database.finish_ftp_sync(
                show["id"], now.date().isoformat(), now.hour, "failed", str(exc)
            )
            LOGGER.warning("Automatic FTP sync failed for %s: %s", show["name"], exc)
            result["failed"] += 1
        else:
            database.finish_ftp_sync(
                show["id"], now.date().isoformat(), now.hour, "synced", sync_result.get("detail", "")
            )
            result["synced"] += 1
    return result


async def ftp_sync_loop(
    database: Database,
    media_root: Path,
    credentials_path: str | Path,
    timezone_name: str,
) -> None:
    while True:
        try:
            await asyncio.to_thread(
                process_automatic_ftp_once,
                database,
                media_root,
                credentials_path,
                None,
                timezone_name,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("FTP scheduler failed")
        await asyncio.sleep(POLL_SECONDS)
