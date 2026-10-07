from __future__ import annotations

import asyncio
import datetime as dt
import filecmp
import hashlib
import json
import logging
import os
import re
import shutil
import threading
import uuid
from pathlib import Path, PurePosixPath
from typing import Any

from .checker import AUDIO_SUFFIXES
from .db import Database
from .patterns import normalize_relative, pattern_day, safe_join


LOGGER = logging.getLogger(__name__)
SETTINGS_KEY = "file_maintenance_settings"
MAINTENANCE_INTERVAL_SECONDS = 15 * 60
PRODUCTION_SUFFIXES = {".mp3", ".wav"}
ARCHIVE_INDEX_TTL = dt.timedelta(hours=24)
PATTERN_TEMPLATE_MARKER = "SPRAWDZACZ AUDYCJI — PLIK WZORCA"
ROOT_LABELS = {
    "media": "AUDYCJE",
    "archive": "Archiwum",
    "emaus": "Emaus",
    "emaus_contact": "Emaus Kontakt",
}

_archive_index_lock = threading.Lock()
_archive_index_root: str | None = None
_archive_index_built_at: dt.datetime | None = None
_archive_size_index: dict[int, list[Path]] = {}
_file_hash_cache: dict[tuple[str, int, int], str] = {}


def normalize_file_maintenance_settings(value: Any) -> dict[str, int]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = {}
    if not isinstance(value, dict):
        value = {}

    def days(key: str, default: int) -> int:
        try:
            result = int(value.get(key, default))
        except (TypeError, ValueError) as exc:
            raise ValueError("Czas automatycznego porządkowania musi być liczbą dni") from exc
        if result < 1 or result > 3650:
            raise ValueError("Czas automatycznego porządkowania musi wynosić od 1 do 3650 dni")
        return result

    return {
        "archive_after_days": days("archive_after_days", 30),
        "production_delete_after_days": days("production_delete_after_days", 30),
    }


def get_file_maintenance_settings(database: Database) -> dict[str, int]:
    return normalize_file_maintenance_settings(database.get_setting(SETTINGS_KEY, "{}"))


def save_file_maintenance_settings(database: Database, value: Any) -> dict[str, int]:
    settings = normalize_file_maintenance_settings(value)
    database.set_setting(SETTINGS_KEY, json.dumps(settings, ensure_ascii=False))
    return settings


def _folder_source(value: Any) -> tuple[str, str, bool]:
    if isinstance(value, dict):
        return (
            str(value.get("root", "media") or "media").strip().lower(),
            normalize_relative(str(value.get("path", "") or "")),
            bool(value.get("auto_delete", False)),
        )
    return "media", normalize_relative(str(value or "")), False


def _audio_files(root: Path, suffixes: set[str]) -> list[Path]:
    files: list[Path] = []
    if not root.is_dir():
        return files
    for directory, names, filenames in os.walk(root, followlinks=False):
        base = Path(directory)
        names[:] = [
            name for name in names
            if not name.startswith(".") and not (base / name).is_symlink()
        ]
        for name in filenames:
            if name.startswith(".") or Path(name).suffix.casefold() not in suffixes:
                continue
            path = base / name
            if path.is_file() and not path.is_symlink():
                files.append(path)
    return files


def _invalidate_archive_index() -> None:
    global _archive_index_root, _archive_index_built_at, _archive_size_index
    with _archive_index_lock:
        _archive_index_root = None
        _archive_index_built_at = None
        _archive_size_index = {}


def _archive_index(archive_root: Path, now: dt.datetime) -> dict[int, list[Path]]:
    """Index Archive by size; rebuild at most daily unless this process changes it."""
    global _archive_index_root, _archive_index_built_at, _archive_size_index
    root_key = str(archive_root.resolve())
    with _archive_index_lock:
        fresh = (
            _archive_index_root == root_key
            and _archive_index_built_at is not None
            and now - _archive_index_built_at < ARCHIVE_INDEX_TTL
        )
        if fresh:
            return _archive_size_index
        rebuilt: dict[int, list[Path]] = {}
        for path in _audio_files(archive_root, AUDIO_SUFFIXES):
            try:
                rebuilt.setdefault(path.stat().st_size, []).append(path)
            except OSError:
                continue
        _archive_index_root = root_key
        _archive_index_built_at = now
        _archive_size_index = rebuilt
        return _archive_size_index


def _file_sha256(path: Path, file_stat: os.stat_result | None = None) -> str:
    stat = file_stat or path.stat()
    key = (str(path.resolve()), int(stat.st_size), int(stat.st_mtime_ns))
    cached = _file_hash_cache.get(key)
    if cached is not None:
        return cached
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    if len(_file_hash_cache) >= 4096:
        _file_hash_cache.clear()
    result = digest.hexdigest()
    _file_hash_cache[key] = result
    return result


def _is_copy_already_in_archive(
    source: Path,
    file_stat: os.stat_result,
    archive_root: Path,
    now: dt.datetime,
) -> bool:
    """Detect restores made outside the app by exact content, not path or timestamps."""
    candidates = _archive_index(archive_root, now).get(file_stat.st_size, [])
    if not candidates:
        return False
    source_digest = _file_sha256(source, file_stat)
    for candidate in candidates:
        try:
            candidate_stat = candidate.stat()
            if _file_sha256(candidate, candidate_stat) == source_digest:
                return True
        except OSError:
            continue
    return False


def _pattern_regex(folder_pattern: str, filename_pattern: str) -> re.Pattern[str]:
    _, folder_mask = pattern_day(normalize_relative(folder_pattern), dt.date(2000, 1, 1))
    _, filename_mask = pattern_day(normalize_relative(filename_pattern), dt.date(2000, 1, 1))
    mask = PurePosixPath(folder_mask, filename_mask).as_posix()
    escaped = re.escape(mask)
    for token, replacement in (
        ("%Y", r"\d{4}"),
        ("%y", r"\d{2}"),
        ("%m", r"(?:0[1-9]|1[0-2])"),
        ("%d", r"(?:0[1-9]|[12]\d|3[01])"),
    ):
        escaped = escaped.replace(re.escape(token), replacement)
    return re.compile(f"^{escaped}$", re.IGNORECASE)


def _show_archive_patterns(show: dict[str, Any]) -> list[re.Pattern[str]]:
    masks: list[tuple[str, str]] = []
    main_patterns = show.get("filename_patterns") or [show.get("filename_pattern", "")]
    for filename in main_patterns:
        masks.append((str(show.get("folder_pattern", "")), str(filename)))
        if show.get("has_youtube_version"):
            path = Path(str(filename))
            masks.append((str(show.get("folder_pattern", "")), f"{path.stem}_yt{path.suffix}"))
    for repeat in show.get("repeats", []):
        filenames = repeat.get("filename_patterns") or [repeat.get("filename_pattern", "")]
        for filename in filenames:
            masks.append((str(repeat.get("folder_pattern", "")), str(filename)))
    result: list[re.Pattern[str]] = []
    seen: set[tuple[str, str]] = set()
    for folder, filename in masks:
        if not filename or (folder, filename) in seen:
            continue
        seen.add((folder, filename))
        result.append(_pattern_regex(folder, filename))
    return result


def _parse_timestamp(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def _archive_file(source: Path, target: Path) -> str:
    def remove_source() -> None:
        # Stare serwery Samba potrafią zostawić oryginalną nazwę jako
        # nieotwieralny wpis "delete pending", gdy ktoś kończy równoległy
        # odczyt. Najpierw atomowo odsuwamy plik spod nazwy audycji, a dopiero
        # potem go usuwamy. Ewentualny wadliwy wpis jest ukryty i nie pasuje
        # już do schematu audycji.
        pending = source.with_name(
            f".{source.name}.{uuid.uuid4().hex}.archive-delete"
        )
        source.rename(pending)
        pending.unlink()

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.is_file() and filecmp.cmp(source, target, shallow=False):
            remove_source()
            return "duplicate_removed"
        raise FileExistsError(f"W Archiwum istnieje już inny plik: {target.name}")
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.archive.tmp")
    try:
        shutil.copy2(source, temporary)
        if temporary.stat().st_size != source.stat().st_size:
            raise OSError("Kopia archiwalna ma inny rozmiar niż plik źródłowy")
        os.replace(temporary, target)
        remove_source()
    finally:
        temporary.unlink(missing_ok=True)
    return "moved"


def _static_show_folder(folder_pattern: Any) -> str:
    """Return the stable show folder before the first date token."""
    normalized = normalize_relative(str(folder_pattern or ""))
    if not normalized:
        return ""
    parts: list[str] = []
    for part in PurePosixPath(normalized).parts:
        if "%" in part:
            break
        parts.append(part)
    return PurePosixPath(*parts).as_posix() if parts else ""


def _show_template_locations(show: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Map stable show folders to literal .wzor filenames."""
    locations: dict[str, dict[str, str]] = {}
    occurrences: list[tuple[Any, list[str]]] = [
        (
            show.get("folder_pattern", ""),
            list(show.get("filename_patterns") or [show.get("filename_pattern", "")]),
        )
    ]
    for repeat in show.get("repeats", []):
        occurrences.append(
            (
                repeat.get("folder_pattern", show.get("folder_pattern", "")),
                list(
                    repeat.get("filename_patterns")
                    or [repeat.get("filename_pattern", "")]
                ),
            )
        )
    for folder_pattern, patterns in occurrences:
        folder = _static_show_folder(folder_pattern)
        if not folder:
            continue
        for raw_pattern in patterns:
            pattern = normalize_relative(str(raw_pattern or ""))
            if not pattern:
                continue
            source_name = PurePosixPath(pattern).name
            suffix = PurePosixPath(source_name).suffix
            template_name = (
                f"{source_name[:-len(suffix)]}.wzor" if suffix else f"{source_name}.wzor"
            )
            locations.setdefault(folder, {})[template_name] = source_name
    return locations


def sync_show_pattern_templates(
    media_root: Path,
    show: dict[str, Any],
    previous: dict[str, Any] | None = None,
) -> dict[str, int]:
    """Create literal naming templates and remove obsolete templates we generated."""
    current = _show_template_locations(show)
    old = _show_template_locations(previous or {})
    desired = {
        (folder, name): pattern
        for folder, names in current.items()
        for name, pattern in names.items()
    }
    obsolete = {
        (folder, name) for folder, names in old.items() for name in names
    } - set(desired)
    result = {"created": 0, "removed": 0}

    for (folder, name), pattern in sorted(desired.items()):
        directory = safe_join(media_root, folder)
        directory.mkdir(parents=True, exist_ok=True)
        target = safe_join(directory, name)
        content = (
            f"{PATTERN_TEMPLATE_MARKER}\n"
            f"Audycja: {show.get('name', '')}\n"
            f"Folder: /AUDYCJE/{folder}\n"
            f"Schemat: {pattern}\n"
        )
        if target.is_file():
            try:
                if target.read_text(encoding="utf-8", errors="ignore") == content:
                    continue
            except OSError:
                pass
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(content, encoding="utf-8")
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        result["created"] += 1

    for folder, name in sorted(obsolete):
        target = safe_join(media_root, f"{folder}/{name}")
        try:
            if target.is_file() and target.read_text(
                encoding="utf-8", errors="ignore"
            ).startswith(PATTERN_TEMPLATE_MARKER):
                target.unlink()
                result["removed"] += 1
        except OSError:
            LOGGER.warning("Nie udało się usunąć starego wzorca %s", target)
    return result


def archive_show_folder(
    database: Database,
    media_root: Path,
    archive_root: Path,
    show: dict[str, Any],
) -> dict[str, Any]:
    """Move the complete dedicated show folder into Archive before deleting a show."""
    relative_folder = _static_show_folder(show.get("folder_pattern", ""))
    if not relative_folder:
        return {"status": "no_folder", "files": 0, "folder": ""}

    for candidate in database.list_shows(include_inactive=True):
        if int(candidate["id"]) == int(show["id"]):
            continue
        candidate_folder = _static_show_folder(candidate.get("folder_pattern", ""))
        if not candidate_folder:
            continue
        shared = (
            candidate_folder == relative_folder
            or candidate_folder.startswith(f"{relative_folder}/")
        )
        if shared:
            raise ValueError(
                "Folder audycji jest współdzielony z audycją "
                f"„{candidate['name']}”. Przed usunięciem przypisz jej osobny folder."
            )

    source_root = safe_join(media_root, relative_folder)
    target_root = safe_join(archive_root, relative_folder)
    if not source_root.exists():
        return {
            "status": "missing",
            "files": 0,
            "folder": relative_folder,
            "target": f"/Archiwum/{relative_folder}",
        }
    if not source_root.is_dir() or source_root.is_symlink():
        raise ValueError("Ścieżka audycji nie jest zwykłym folderem")

    files: list[tuple[Path, Path]] = []
    directories: list[Path] = []
    for directory, names, filenames in os.walk(source_root, followlinks=False):
        base = Path(directory)
        names[:] = [name for name in names if not (base / name).is_symlink()]
        directories.append(base)
        for filename in filenames:
            source = base / filename
            if source.is_symlink() or not source.is_file():
                continue
            relative = source.relative_to(source_root)
            target = target_root / relative
            if target.exists() and not (
                target.is_file() and filecmp.cmp(source, target, shallow=False)
            ):
                raise FileExistsError(
                    "W Archiwum istnieje już inny plik: "
                    f"/{ROOT_LABELS['archive']}/{relative_folder}/{relative.as_posix()}"
                )
            files.append((source, target))

    target_root.mkdir(parents=True, exist_ok=True)
    for directory in directories:
        (target_root / directory.relative_to(source_root)).mkdir(
            parents=True, exist_ok=True
        )
    moved = 0
    for source, target in files:
        _archive_file(source, target)
        moved += 1

    for directory in sorted(directories, key=lambda item: len(item.parts), reverse=True):
        try:
            directory.rmdir()
        except OSError:
            continue
    if source_root.exists():
        pending = source_root.with_name(
            f".{source_root.name}.{uuid.uuid4().hex}.archive-delete-folder"
        )
        try:
            source_root.rename(pending)
            shutil.rmtree(pending, ignore_errors=True)
        except OSError:
            LOGGER.warning(
                "Folder %s pozostał po archiwizacji jako pusty lub wpis oczekujący CIFS",
                source_root,
            )

    database.record_file_maintenance(
        "archive_show_delete",
        int(show["id"]),
        f"/{ROOT_LABELS['media']}/{relative_folder}",
        f"/{ROOT_LABELS['archive']}/{relative_folder}",
        "moved",
        f"Przeniesiono {moved} plików przed usunięciem audycji",
    )
    _invalidate_archive_index()
    return {
        "status": "moved",
        "files": moved,
        "folder": relative_folder,
        "target": f"/Archiwum/{relative_folder}",
    }


def archive_media_file_now(
    database: Database,
    media_root: Path,
    archive_root: Path,
    relative_path: str,
) -> dict[str, Any]:
    """Archive one explicitly selected managed file, bypassing the retention clock."""
    relative = normalize_relative(relative_path)
    source = safe_join(media_root, relative)
    if not source.is_file() or source.is_symlink():
        raise FileNotFoundError("Plik nie istnieje")
    if source.suffix.casefold() not in AUDIO_SUFFIXES:
        raise ValueError("Archiwizować można tylko obsługiwane pliki audio")
    matching = [
        show for show in database.list_shows(include_inactive=True)
        if show.get("auto_archive")
        and any(pattern.fullmatch(relative) for pattern in _show_archive_patterns(show))
    ]
    if not matching:
        raise ValueError(
            "Plik nie pasuje do żadnej audycji z włączoną autoarchiwizacją"
        )
    target = safe_join(archive_root, relative)
    status = _archive_file(source, target)
    for show in matching:
        show_id = int(show["id"])
        database.record_file_maintenance(
            "archive", show_id, relative, relative, status, "Uruchomiono ręcznie"
        )
        database.remove_maintenance_file("archive", show_id, "", relative)
    _invalidate_archive_index()
    return {
        "source": f"/{ROOT_LABELS['media']}/{relative}",
        "target": f"/{ROOT_LABELS['archive']}/{relative}",
        "status": status,
    }


def _process_auto_archive(
    database: Database,
    media_root: Path,
    archive_root: Path,
    now: dt.datetime,
    after_days: int,
) -> dict[str, int]:
    enabled: list[tuple[dict[str, Any], list[re.Pattern[str]]]] = []
    for show in database.list_shows(include_inactive=True):
        if show.get("auto_archive"):
            enabled.append((show, _show_archive_patterns(show)))
    result = {"observed": 0, "archived": 0, "skipped_restore": 0, "failed": 0}
    if not enabled:
        return result

    current: dict[int, set[str]] = {int(show["id"]): set() for show, _ in enabled}
    for source in _audio_files(media_root, AUDIO_SUFFIXES):
        relative = source.relative_to(media_root).as_posix()
        for show, patterns in enabled:
            show_id = int(show["id"])
            if not any(pattern.fullmatch(relative) for pattern in patterns):
                continue
            try:
                file_stat = source.stat()
            except OSError:
                result["failed"] += 1
                continue
            current[show_id].add(relative)
            state = database.observe_maintenance_file(
                "archive",
                show_id,
                "",
                relative,
                file_stat.st_size,
                file_stat.st_mtime_ns,
                now.isoformat(),
            )
            result["observed"] += 1
            if state["origin"] != "archive_restore":
                try:
                    restored_manually = _is_copy_already_in_archive(
                        source, file_stat, archive_root, now
                    )
                except OSError as exc:
                    LOGGER.warning(
                        "Nie udało się porównać %s z Archiwum: %s", relative, exc
                    )
                    restored_manually = False
                if restored_manually:
                    state = database.observe_maintenance_file(
                        "archive",
                        show_id,
                        "",
                        relative,
                        file_stat.st_size,
                        file_stat.st_mtime_ns,
                        now.isoformat(),
                        "archive_restore",
                    )
            if state["origin"] == "archive_restore":
                result["skipped_restore"] += 1
                continue
            if now - _parse_timestamp(state["first_seen_at"]) < dt.timedelta(days=after_days):
                continue
            target = safe_join(archive_root, relative)
            try:
                status = _archive_file(source, target)
            except OSError as exc:
                LOGGER.warning("Autoarchiwizacja %s nie powiodła się: %s", relative, exc)
                database.record_file_maintenance(
                    "archive", show_id, relative, relative, "failed", str(exc)
                )
                result["failed"] += 1
            else:
                database.record_file_maintenance(
                    "archive", show_id, relative, relative, status
                )
                database.remove_maintenance_file("archive", show_id, "", relative)
                current[show_id].discard(relative)
                _invalidate_archive_index()
                result["archived"] += 1
            break

    for show, _ in enabled:
        show_id = int(show["id"])
        database.prune_maintenance_files("archive", show_id, "", current[show_id])
    return result


def _process_production_deletion(
    database: Database,
    source_roots: dict[str, Path],
    now: dt.datetime,
    after_days: int,
) -> dict[str, int]:
    result = {"observed": 0, "deleted": 0, "failed": 0}
    for show in database.list_shows(include_inactive=True):
        if not show.get("requires_editing"):
            continue
        for raw_folder in show.get("production_watch_folders", []):
            root_name, folder, auto_delete = _folder_source(raw_folder)
            scope = f"{root_name}:{folder}"
            show_id = int(show["id"])
            if not auto_delete:
                database.clear_maintenance_scope("production_delete", show_id, scope)
                continue
            root = source_roots.get(root_name)
            if root is None:
                result["failed"] += 1
                continue
            try:
                directory = safe_join(root, folder)
                files = _audio_files(directory, PRODUCTION_SUFFIXES)
            except (OSError, ValueError):
                LOGGER.exception("Nie udało się przeskanować folderu produkcji %s", scope)
                result["failed"] += 1
                continue
            current: set[str] = set()
            for source in files:
                relative = source.relative_to(directory).as_posix()
                current.add(relative)
                try:
                    file_stat = source.stat()
                    state = database.observe_maintenance_file(
                        "production_delete",
                        show_id,
                        scope,
                        relative,
                        file_stat.st_size,
                        file_stat.st_mtime_ns,
                        now.isoformat(),
                    )
                    result["observed"] += 1
                    first_seen = _parse_timestamp(state["first_seen_at"])
                    modified = dt.datetime.fromtimestamp(file_stat.st_mtime, tz=dt.timezone.utc)
                    if now - max(first_seen, modified) < dt.timedelta(days=after_days):
                        continue
                    source.unlink()
                except OSError as exc:
                    LOGGER.warning("Autokasowanie %s/%s nie powiodło się: %s", scope, relative, exc)
                    database.record_file_maintenance(
                        "production_delete",
                        show_id,
                        f"/{ROOT_LABELS.get(root_name, root_name)}/{folder}/{relative}",
                        "",
                        "failed",
                        str(exc),
                    )
                    result["failed"] += 1
                else:
                    database.record_file_maintenance(
                        "production_delete",
                        show_id,
                        f"/{ROOT_LABELS.get(root_name, root_name)}/{folder}/{relative}",
                        "",
                        "deleted",
                    )
                    database.remove_maintenance_file(
                        "production_delete", show_id, scope, relative
                    )
                    current.discard(relative)
                    result["deleted"] += 1
            database.prune_maintenance_files(
                "production_delete", show_id, scope, current
            )
    return result


def process_file_maintenance_once(
    database: Database,
    media_root: Path,
    archive_root: Path,
    source_roots: dict[str, Path],
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    moment = now or dt.datetime.now(dt.timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    else:
        moment = moment.astimezone(dt.timezone.utc)
    settings = get_file_maintenance_settings(database)
    return {
        "archive": _process_auto_archive(
            database,
            media_root,
            archive_root,
            moment,
            settings["archive_after_days"],
        ),
        "production_delete": _process_production_deletion(
            database,
            source_roots,
            moment,
            settings["production_delete_after_days"],
        ),
    }


async def file_maintenance_loop(
    database: Database,
    media_root: Path,
    archive_root: Path,
    source_roots: dict[str, Path],
) -> None:
    while True:
        try:
            await asyncio.to_thread(
                process_file_maintenance_once,
                database,
                media_root,
                archive_root,
                source_roots,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("Automatyczne porządkowanie plików nie powiodło się")
        await asyncio.sleep(MAINTENANCE_INTERVAL_SECONDS)
