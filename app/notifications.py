from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import uuid
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from .checker import check_occurrence
from .db import Database
from .patterns import safe_join
from .schedules import matches_date


LOGGER = logging.getLogger(__name__)
PUSHOVER_URL = "https://api.pushover.net/1/messages.json"
SETTINGS_KEY = "notification_settings"
POLL_SECONDS = 30


def _identifier(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def normalize_notification_settings(value: Any) -> dict[str, list[dict[str, Any]]]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = {}
    if not isinstance(value, dict):
        value = {}

    recipients: list[dict[str, Any]] = []
    seen_recipient_ids: set[str] = set()
    for index, raw in enumerate(value.get("recipients", [])):
        if not isinstance(raw, dict):
            continue
        recipient_id = str(raw.get("id") or _identifier("recipient"))
        if recipient_id in seen_recipient_ids:
            recipient_id = _identifier("recipient")
        seen_recipient_ids.add(recipient_id)
        recipients.append(
            {
                "id": recipient_id,
                "label": str(raw.get("label") or f"Odbiorca {index + 1}").strip(),
                "app_token": str(raw.get("app_token") or "").strip(),
                "user_key": str(raw.get("user_key") or "").strip(),
                "device": str(raw.get("device") or "").strip(),
                "enabled": bool(raw.get("enabled", True)),
                "production_folder_notifications": bool(
                    raw.get("production_folder_notifications", False)
                ),
            }
        )

    rules: list[dict[str, Any]] = []
    seen_rule_ids: set[str] = set()
    seen_leads: set[int] = set()
    for raw in value.get("rules", []):
        if not isinstance(raw, dict):
            continue
        try:
            lead_minutes = int(raw.get("lead_minutes", 0))
        except (TypeError, ValueError):
            continue
        if lead_minutes < 1 or lead_minutes > 43_200 or lead_minutes in seen_leads:
            continue
        seen_leads.add(lead_minutes)
        rule_id = str(raw.get("id") or _identifier("rule"))
        if rule_id in seen_rule_ids:
            rule_id = _identifier("rule")
        seen_rule_ids.add(rule_id)
        rules.append(
            {
                "id": rule_id,
                "lead_minutes": lead_minutes,
                "enabled": bool(raw.get("enabled", True)),
            }
        )
    rules.sort(key=lambda rule: rule["lead_minutes"], reverse=True)
    return {"recipients": recipients, "rules": rules}


def get_notification_settings(database: Database) -> dict[str, list[dict[str, Any]]]:
    return normalize_notification_settings(database.get_setting(SETTINGS_KEY, "{}"))


def save_notification_settings(database: Database, value: Any) -> dict[str, list[dict[str, Any]]]:
    settings = normalize_notification_settings(value)
    for recipient in settings["recipients"]:
        if recipient["enabled"] and (not recipient["app_token"] or not recipient["user_key"]):
            raise ValueError("Każdy aktywny odbiorca musi mieć API Token i User/Group Key")
    database.set_setting(SETTINGS_KEY, json.dumps(settings, ensure_ascii=False))
    return settings


def send_pushover(
    recipient: dict[str, Any],
    title: str,
    message: str,
    priority: int = 0,
) -> dict[str, Any]:
    payload = {
        "token": recipient["app_token"],
        "user": recipient["user_key"],
        "title": title,
        "message": message,
        "priority": str(priority),
    }
    if recipient.get("device"):
        payload["device"] = recipient["device"]
    request = Request(
        PUSHOVER_URL,
        data=urlencode(payload).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=15) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Pushover HTTP {exc.code}: {detail[:400]}") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Nie udało się połączyć z Pushover: {exc}") from exc
    if int(result.get("status", 0)) != 1:
        errors = ", ".join(str(item) for item in result.get("errors", []))
        raise RuntimeError(errors or "Pushover odrzucił wiadomość")
    return result


def _lead_label(minutes: int) -> str:
    if minutes % 1440 == 0:
        days = minutes // 1440
        return f"{days} d przed emisją"
    if minutes % 60 == 0:
        hours = minutes // 60
        return f"{hours} h przed emisją"
    return f"{minutes} min przed emisją"


def _message_for(item: dict[str, Any], emission_at: dt.datetime, lead_minutes: int) -> tuple[str, str]:
    missing = [part for part in item["parts"] if not part["found"]]
    missing_names = ", ".join(
        str(part.get("label") or (f"cz. {part['part_number']}" if item["parts_total"] > 1 else "plik"))
        for part in missing
    )
    title = f"Brakuje audycji: {item['name']}"
    body = (
        f"Audycja: {item['name']}. "
        f"{item['occurrence_label']} — {emission_at:%d.%m.%Y o %H:%M}. "
        f"Brakuje: {missing_names}. Powiadomienie: {_lead_label(lead_minutes)}."
    )
    return title, body


def process_notifications_once(
    database: Database,
    media_root: Path,
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

    settings = get_notification_settings(database)
    recipients = [item for item in settings["recipients"] if item["enabled"]]
    rules = [item for item in settings["rules"] if item["enabled"]]
    if not recipients or not rules:
        return {"sent": 0, "skipped": 0, "failed": 0}

    max_days = max(rule["lead_minutes"] for rule in rules) // 1440 + 2
    result = {"sent": 0, "skipped": 0, "failed": 0}
    for show in database.list_shows(include_inactive=False):
        occurrences: list[tuple[str, dict[str, Any], int | None, list[dict[str, Any]], list[str]]] = []
        for slot in show.get("premiere_slots", []):
            occurrences.append(
                (f"main:{slot['id']}", show, None, slot.get("schedule", []), slot.get("emission_times", []))
            )
        if not show.get("premiere_slots"):
            occurrences.append(("main", show, None, show.get("schedule", []), show.get("emission_times", [])))
        occurrences.extend(
            (f"repeat:{repeat['id']}", repeat, index, repeat.get("schedule", []), repeat.get("emission_times", []))
            for index, repeat in enumerate(show.get("repeats", []))
        )
        for occurrence_prefix, occurrence, repeat_index, schedule, emission_times in occurrences:
            report_occurrence_key = "main" if repeat_index is None else f"repeat:{occurrence['id']}"
            for emission_time in emission_times:
                occurrence_key = f"{occurrence_prefix}:{emission_time}"
                hour, minute = map(int, emission_time.split(":"))
                for offset in range(max_days + 1):
                    day = now.date() + dt.timedelta(days=offset)
                    if not matches_date(schedule, day):
                        continue
                    if database.is_report_occurrence_ignored(
                        show["id"], report_occurrence_key, day.isoformat()
                    ):
                        continue
                    emission_at = dt.datetime.combine(day, dt.time(hour, minute), timezone)
                    if emission_at <= now:
                        continue
                    due_rules = [
                        rule for rule in rules
                        if emission_at - dt.timedelta(minutes=rule["lead_minutes"]) <= now
                    ]
                    if not due_rules:
                        continue
                    newest_due = min(due_rules, key=lambda rule: rule["lead_minutes"])
                    item = check_occurrence(show, occurrence, day, media_root, repeat_index)
                    for rule in due_rules:
                        for recipient in recipients:
                            claimed = database.claim_notification(
                                show["id"], occurrence_key, day.isoformat(), rule["lead_minutes"], recipient["id"]
                            )
                            if not claimed:
                                continue
                            if rule is not newest_due:
                                database.finish_notification(
                                    show["id"], occurrence_key, day.isoformat(), rule["lead_minutes"],
                                    recipient["id"], "skipped_late", "Pominięto starszy zaległy próg",
                                )
                                result["skipped"] += 1
                                continue
                            if item["found"]:
                                database.finish_notification(
                                    show["id"], occurrence_key, day.isoformat(), rule["lead_minutes"],
                                    recipient["id"], "present", "Wszystkie pliki były obecne",
                                )
                                result["skipped"] += 1
                                continue
                            title, message = _message_for(item, emission_at, rule["lead_minutes"])
                            try:
                                send_pushover(recipient, title, message)
                            except RuntimeError as exc:
                                database.release_notification(
                                    show["id"], occurrence_key, day.isoformat(), rule["lead_minutes"], recipient["id"]
                                )
                                LOGGER.warning("Pushover notification failed: %s", exc)
                                result["failed"] += 1
                            else:
                                database.finish_notification(
                                    show["id"], occurrence_key, day.isoformat(), rule["lead_minutes"],
                                    recipient["id"], "sent", message,
                                )
                                result["sent"] += 1
    return result


def _production_files(directory: Path) -> list[str]:
    files: list[str] = []
    for path in directory.rglob("*"):
        relative = path.relative_to(directory)
        if any(part.startswith(".") for part in relative.parts):
            continue
        if path.suffix.casefold() not in {".mp3", ".wav"}:
            continue
        if path.is_file() and not path.is_symlink():
            files.append(relative.as_posix())
    return sorted(files)


ROOT_LABELS = {
    "media": "AUDYCJE",
    "archive": "Archiwum",
    "emaus": "Emaus",
    "emaus_contact": "Emaus Kontakt",
}


def _production_folder_source(value: Any) -> tuple[str, str]:
    if isinstance(value, dict):
        return (
            str(value.get("root", "media") or "media").strip().lower(),
            str(value.get("path", "") or "").strip(),
        )
    return "media", str(value or "").strip()


def _production_folder_key(root: str, folder: str) -> str:
    return folder if root == "media" else f"{root}:{folder}"


def _production_message(
    show: dict[str, Any], root: str, folder: str, paths: list[str]
) -> tuple[str, str]:
    visible = paths[:12]
    file_list = ", ".join(visible)
    if len(paths) > len(visible):
        file_list += f" oraz {len(paths) - len(visible)} kolejnych"
    label = ROOT_LABELS.get(root, root)
    message = f"W /{label}/{folder} pojawiły się nowe pliki ({len(paths)}): {file_list}"
    if len(message) > 900:
        message = message[:897].rstrip() + "…"
    return f"Nowe pliki produkcyjne: {show['name']}", message


def process_production_folders_once(
    database: Database,
    media_root: Path,
    now: dt.datetime | None = None,
    timezone_name: str = "Europe/Warsaw",
    source_roots: dict[str, Path] | None = None,
) -> dict[str, int]:
    timezone = ZoneInfo(timezone_name)
    if now is None:
        now = dt.datetime.now(timezone)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone)
    else:
        now = now.astimezone(timezone)

    settings = get_notification_settings(database)
    recipients = [
        item for item in settings["recipients"]
        if item["enabled"] and item.get("production_folder_notifications", False)
    ]
    recipient_ids = [str(item["id"]) for item in recipients]
    result = {"initialized": 0, "detected": 0, "sent": 0, "failed": 0}
    configured: set[tuple[int, str]] = set()
    roots = {"media": media_root}
    if source_roots:
        roots.update(source_roots)

    for show in database.list_shows(include_inactive=True):
        if not show.get("requires_editing"):
            continue
        for raw_folder in show.get("production_watch_folders", []):
            root_name, folder = _production_folder_source(raw_folder)
            folder_key = _production_folder_key(root_name, folder)
            configured.add((int(show["id"]), folder_key))
            try:
                source_root = roots.get(root_name)
                if source_root is None:
                    raise ValueError("Nieznane źródło monitorowanego folderu")
                directory = safe_join(source_root, folder)
                if not directory.is_dir():
                    LOGGER.warning(
                        "Production folder unavailable for %s: %s", show["name"], directory
                    )
                    result["failed"] += 1
                    continue
                scan = database.scan_production_folder(
                    int(show["id"]), folder_key, _production_files(directory), now.isoformat()
                )
            except (OSError, ValueError):
                LOGGER.exception("Production folder scan failed for %s: %s", show["name"], folder)
                result["failed"] += 1
                continue
            if scan["initialized"]:
                result["initialized"] += 1
                continue
            pending = scan["pending"]
            if not pending:
                continue
            event_ids = [str(item["event_id"]) for item in pending]
            paths = [str(item["relative_path"]) for item in pending]
            path_by_event = {
                str(item["event_id"]): str(item["relative_path"]) for item in pending
            }
            result["detected"] += len(paths)
            for recipient in recipients:
                claimed = [
                    event_id for event_id in event_ids
                    if database.claim_production_notification(event_id, str(recipient["id"]))
                ]
                if not claimed:
                    continue
                title, message = _production_message(
                    show, root_name, folder, [path_by_event[event_id] for event_id in claimed]
                )
                try:
                    send_pushover(recipient, title, message)
                except RuntimeError as exc:
                    for event_id in claimed:
                        database.release_production_notification(event_id, str(recipient["id"]))
                    LOGGER.warning("Production folder Pushover notification failed: %s", exc)
                    result["failed"] += 1
                else:
                    for event_id in claimed:
                        database.finish_production_notification(
                            event_id, str(recipient["id"]), message
                        )
                    result["sent"] += 1
            database.complete_production_events(event_ids, recipient_ids)

    database.prune_production_watch_configuration(configured)
    return result


async def notification_loop(
    database: Database,
    media_root: Path,
    timezone_name: str,
    source_roots: dict[str, Path] | None = None,
) -> None:
    while True:
        try:
            await asyncio.to_thread(process_notifications_once, database, media_root, None, timezone_name)
            await asyncio.to_thread(
                process_production_folders_once,
                database,
                media_root,
                None,
                timezone_name,
                source_roots,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("Notification scheduler failed")
        await asyncio.sleep(POLL_SECONDS)
