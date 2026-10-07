from __future__ import annotations

import json
import math
import os
import re
import secrets
import sqlite3
import threading
import unicodedata
import uuid
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any, Iterator

from .patterns import normalize_relative
from .schedules import describe_rules, normalize_rules


DATA_MODEL_VERSION = 14
_REPEAT_MARKER = re.compile(r"\s*\((?:powtórka|potórka)\)\s*", re.IGNORECASE)
_FTP_MARKER = re.compile(r"\s*\([^)]*\bftp\b[^)]*\)\s*", re.IGNORECASE)
_PART_MARKER = re.compile(r"\s+cz(?:ęść)?\s*(\d+)\s*$", re.IGNORECASE)
_AUTHOR_EMAIL_PATTERN = re.compile(r"^[^@\s,;]+@[^@\s,;]+$")
_POLISH_ORDER = "0123456789aąbcćdeęfghijklłmnńoóprsśtuwyzźżqvx"
_POLISH_RANK = {character: index for index, character in enumerate(_POLISH_ORDER)}
FTP_DEFAULTS_APPLIED_KEY = "ftp_defaults_v1_applied"
BUILTIN_FTP_SOURCES = {
    "księga": "/PCR/Radio Warszawa/AUDYCJE - CYKLE/RW Ksiega",
    "lista z moca": "/PCR/Lista z moca",
    "nie jesteś sam": "/PCR/Radio Warszawa/AUDYCJE - CYKLE/RW Nie jestes sam",
    "święci z nieba ściągnięci": "/PCR/Radio eM Katowice/Swieci z nieba sciagnieci",
    "wywiad z czlowiekiem": "/PCR/Radio Warszawa/AUDYCJE - CYKLE/RW Wywiad z czlowiekiem",
}
TIMETABLE_CATEGORIES = {
    "shows",
    "ads",
    "presenter",
    "weather",
    "news",
    "branding",
    "transmission",
    "other",
    "music",
}
FILE_SOURCE_ROOTS = {"media", "archive", "emaus", "emaus_contact"}


def filter_import_warnings(warnings: Any) -> list[str]:
    """Hide benign legacy corrections while preserving actionable import warnings."""
    if not isinstance(warnings, list):
        return []
    return [
        str(warning)
        for warning in warnings
        if "Poprawiono literówkę w regule:" not in str(warning)
    ]


def normalize_author_emails(value: Any) -> list[str]:
    """Return a case-insensitively deduplicated list of author addresses."""
    raw_values = value if isinstance(value, (list, tuple, set)) else [value]
    addresses: list[str] = []
    seen: set[str] = set()
    for raw_value in raw_values:
        for raw_address in re.split(r"[,;\n\r]+", str(raw_value or "")):
            address = raw_address.strip()
            if not address:
                continue
            if not _AUTHOR_EMAIL_PATTERN.fullmatch(address):
                raise ValueError(f"Nieprawidłowy adres e-mail autora: {address}")
            key = address.casefold()
            if key in seen:
                continue
            seen.add(key)
            addresses.append(address)
    return addresses


SCHEMA = """
CREATE TABLE IF NOT EXISTS shows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    folder_pattern TEXT NOT NULL DEFAULT '',
    filename_pattern TEXT NOT NULL,
    additional_patterns_json TEXT NOT NULL DEFAULT '[]',
    emission_time TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    requires_editing INTEGER NOT NULL DEFAULT 0,
    production_watch_folders_json TEXT NOT NULL DEFAULT '[]',
    auto_archive INTEGER NOT NULL DEFAULT 0,
    is_ftp INTEGER NOT NULL DEFAULT 0,
    ftp_source_path TEXT NOT NULL DEFAULT '',
    ftp_auto_sync INTEGER NOT NULL DEFAULT 0,
    ftp_rename_enabled INTEGER NOT NULL DEFAULT 0,
    ftp_source_patterns_json TEXT NOT NULL DEFAULT '[]',
    premiere_slots_json TEXT NOT NULL DEFAULT '[]',
    has_youtube_version INTEGER NOT NULL DEFAULT 0,
    send_to_author INTEGER NOT NULL DEFAULT 0,
    author_email TEXT NOT NULL DEFAULT '',
    duration_minutes REAL NOT NULL DEFAULT 45,
    max_duration_minutes REAL DEFAULT NULL,
    drive_folder_id TEXT NOT NULL DEFAULT '',
    drive_permission_id TEXT NOT NULL DEFAULT '',
    drive_shared_email TEXT NOT NULL DEFAULT '',
    drive_permissions_json TEXT NOT NULL DEFAULT '{}',
    drive_link_permission_id TEXT NOT NULL DEFAULT '',
    schedule_json TEXT NOT NULL DEFAULT '[]',
    repeats_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS import_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    imported INTEGER NOT NULL,
    warnings_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS notification_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    show_id INTEGER NOT NULL,
    occurrence_key TEXT NOT NULL,
    emission_date TEXT NOT NULL,
    lead_minutes INTEGER NOT NULL,
    recipient_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(show_id, occurrence_key, emission_date, lead_minutes, recipient_id)
);
CREATE TABLE IF NOT EXISTS report_ignored_occurrences (
    show_id INTEGER NOT NULL,
    occurrence_key TEXT NOT NULL,
    emission_date TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(show_id, occurrence_key, emission_date),
    FOREIGN KEY(show_id) REFERENCES shows(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS production_watch_folders (
    show_id INTEGER NOT NULL,
    folder_path TEXT NOT NULL,
    initialized_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_scan_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(show_id, folder_path),
    FOREIGN KEY(show_id) REFERENCES shows(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS production_watch_files (
    show_id INTEGER NOT NULL,
    folder_path TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    event_id TEXT NOT NULL UNIQUE,
    detected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    pending INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(show_id, folder_path, relative_path),
    FOREIGN KEY(show_id) REFERENCES shows(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS production_watch_notification_log (
    event_id TEXT NOT NULL,
    recipient_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(event_id, recipient_id),
    FOREIGN KEY(event_id) REFERENCES production_watch_files(event_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS file_maintenance_state (
    kind TEXT NOT NULL,
    show_id INTEGER NOT NULL,
    scope_path TEXT NOT NULL DEFAULT '',
    relative_path TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    first_seen_at TEXT NOT NULL,
    origin TEXT NOT NULL DEFAULT 'normal',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(kind, show_id, scope_path, relative_path),
    FOREIGN KEY(show_id) REFERENCES shows(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS file_maintenance_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    show_id INTEGER,
    source_path TEXT NOT NULL,
    target_path TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS ftp_sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    show_id INTEGER NOT NULL,
    emission_date TEXT NOT NULL,
    hour_slot INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(show_id, emission_date, hour_slot)
);
CREATE TABLE IF NOT EXISTS ftp_manual_sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    show_id INTEGER NOT NULL,
    status TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS author_delivery_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    show_id INTEGER NOT NULL,
    emission_date TEXT NOT NULL,
    recipient TEXT NOT NULL,
    status TEXT NOT NULL,
    files_json TEXT NOT NULL DEFAULT '[]',
    folder_url TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS timetable_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    show_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(show_id) REFERENCES shows(id) ON DELETE SET NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS timetable_items_show_unique
ON timetable_items(show_id) WHERE show_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS timetable_items_element_unique
ON timetable_items(lower(name), category) WHERE show_id IS NULL;
CREATE TABLE IF NOT EXISTS timetable_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL,
    weekday INTEGER NOT NULL,
    start_time TEXT NOT NULL,
    duration_minutes REAL NOT NULL DEFAULT 5,
    approximate INTEGER NOT NULL DEFAULT 0,
    show_role TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'manual',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(item_id) REFERENCES timetable_items(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS zetta_played_rows (
    station_id TEXT NOT NULL,
    emission_date TEXT NOT NULL,
    hour_slot INTEGER NOT NULL,
    row_id TEXT NOT NULL,
    sequence INTEGER,
    air_time TEXT NOT NULL DEFAULT '',
    status_code INTEGER,
    edit_code INTEGER,
    runtime_ms INTEGER,
    duration_ms INTEGER,
    asset_id TEXT NOT NULL DEFAULT '',
    universal_identifier TEXT NOT NULL DEFAULT '',
    log_group_universal_identifier TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    artist TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT 'other',
    asset_json TEXT NOT NULL DEFAULT '{}',
    raw_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(station_id, emission_date, row_id)
);
CREATE INDEX IF NOT EXISTS zetta_played_rows_day_idx
ON zetta_played_rows(station_id, emission_date, hour_slot, sequence, air_time);
CREATE TABLE IF NOT EXISTS zetta_sync_log (
    station_id TEXT NOT NULL,
    emission_date TEXT NOT NULL,
    hour_slot INTEGER NOT NULL,
    status TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    row_count INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(station_id, emission_date, hour_slot)
);
"""


def clean_legacy_name(value: str) -> tuple[str, bool, bool]:
    """Return clean title plus legacy repeat/FTP flags."""
    name = str(value).strip()
    is_repeat = bool(_REPEAT_MARKER.search(name))
    is_ftp = bool(_FTP_MARKER.search(name))
    name = _REPEAT_MARKER.sub(" ", name)
    name = _FTP_MARKER.sub(" ", name)
    name = " ".join(name.split()).strip(" -–")
    return name, is_repeat, is_ftp


def derive_tags(requires_editing: bool, is_ftp: bool) -> list[str]:
    tags: list[str] = []
    if requires_editing:
        tags.append("PRODUKCJA")
    if is_ftp:
        tags.append("FTP")
    return tags


def default_show_duration(name: str) -> int:
    key = unicodedata.normalize(
        "NFKD", name.translate(str.maketrans({"ł": "l", "Ł": "L"}))
    ).encode("ascii", "ignore").decode().casefold()
    if any(value in key for value in ("5 minut", "mysli swietych", "slowo o slowie")):
        return 5
    if "swieci z nieba" in key or "w drodze do emaus" in key:
        return 10
    return 45


def normalize_duration_minutes(value: Any, default: float = 5) -> float:
    try:
        duration = float(default if value in (None, "") else value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Nieprawidłowy czas trwania") from exc
    if not math.isfinite(duration) or duration < 0.5 or duration > 240:
        raise ValueError("Czas trwania musi wynosić od 0,5 do 240 minut")
    if not math.isclose(duration * 2, round(duration * 2), abs_tol=1e-9):
        raise ValueError("Czas trwania podaj z dokładnością do pół minuty")
    return round(duration * 2) / 2


def normalize_max_duration_minutes(value: Any, typical_duration: float) -> float | None:
    if value in (None, ""):
        return None
    maximum = normalize_duration_minutes(value, typical_duration)
    if maximum < typical_duration:
        raise ValueError("Czas maksymalny nie może być krótszy niż czas typowy")
    return maximum


def polish_sort_key(value: str) -> tuple[tuple[int, str], ...]:
    return tuple((_POLISH_RANK.get(character, 1000), character) for character in value.casefold())


def _normalize_time(value: Any) -> str | None:
    emission_time = str(value or "").strip() or None
    if not emission_time:
        return None
    compact = re.fullmatch(r"\d{3,4}", emission_time)
    if compact:
        emission_time = f"{emission_time[:-2]}:{emission_time[-2:]}"
    parts = emission_time.split(":")
    if len(parts) != 2 or not all(item.isdigit() for item in parts):
        raise ValueError("Nieprawidłowa godzina emisji")
    hour, minute = map(int, parts)
    if hour not in range(24) or minute not in range(60):
        raise ValueError("Nieprawidłowa godzina emisji")
    return f"{hour:02d}:{minute:02d}"


def normalize_times(value: Any, fallback: Any = None) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        value = []
    if not value and fallback:
        value = [fallback]
    result: list[str] = []
    for raw in value:
        normalized = _normalize_time(raw)
        if normalized and normalized not in result:
            result.append(normalized)
    return sorted(result)


def normalize_emission_slots(
    value: Any,
    fallback_schedule: Any = None,
    fallback_time: Any = None,
) -> list[dict[str, Any]]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = []
    if not isinstance(value, list):
        value = []
    if not value and normalize_rules(fallback_schedule):
        value = [{"schedule": fallback_schedule, "emission_times": [fallback_time] if fallback_time else []}]

    slots: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    for index, raw in enumerate(value):
        if not isinstance(raw, dict):
            continue
        schedule = normalize_rules(raw.get("schedule", []))
        if not schedule:
            continue
        slot_id = str(raw.get("id") or uuid.uuid4().hex)
        if slot_id in used_ids:
            slot_id = uuid.uuid4().hex
        used_ids.add(slot_id)
        times = normalize_times(raw.get("emission_times"), raw.get("emission_time"))
        slots.append(
            {
                "id": slot_id,
                "label": str(raw.get("label") or f"Plan {index + 1}").strip(),
                "emission_times": times,
                "emission_time": times[0] if times else None,
                "schedule": schedule,
                "schedule_description": describe_rules(schedule),
            }
        )
    return slots


def combined_schedule(slots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    seen: set[str] = set()
    for slot in slots:
        for rule in normalize_rules(slot.get("schedule", [])):
            key = json.dumps(rule, ensure_ascii=False, sort_keys=True)
            if key not in seen:
                seen.add(key)
                rules.append(rule)
    return rules


def normalize_filename_patterns(value: Any, fallback: str = "") -> list[str]:
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
            value = decoded if isinstance(decoded, list) else [value]
        except json.JSONDecodeError:
            value = [value]
    if not isinstance(value, list):
        value = []
    patterns: list[str] = []
    for raw in value:
        pattern = str(raw or "").strip()
        if pattern and pattern not in patterns:
            patterns.append(pattern)
    if not patterns and fallback.strip():
        patterns.append(fallback.strip())
    return patterns


def normalize_production_watch_folders(value: Any) -> list[Any]:
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
            value = decoded if isinstance(decoded, list) else [value]
        except json.JSONDecodeError:
            value = [value]
    if not isinstance(value, list):
        value = []
    folders: list[Any] = []
    seen: set[tuple[str, str]] = set()
    for raw in value:
        if isinstance(raw, dict):
            root = str(raw.get("root", "media") or "media").strip().lower()
            candidate = str(raw.get("path", "") or "").strip()
            auto_delete = bool(raw.get("auto_delete", False))
        else:
            root = "media"
            candidate = str(raw or "").strip()
            auto_delete = False
        if not candidate:
            continue
        if root not in FILE_SOURCE_ROOTS:
            raise ValueError("Nieznane źródło monitorowanego folderu")
        if any(character in candidate for character in ("\0", "\n", "\r")):
            raise ValueError("Nieprawidłowa ścieżka monitorowanego folderu")
        folder = normalize_relative(candidate)
        if not folder:
            raise ValueError("Nie można monitorować całego źródła plików")
        key = (root, folder)
        if key in seen:
            continue
        seen.add(key)
        # Zachowujemy dotychczasowy format dla AUDYCJE, a pozostałe źródła
        # zapisujemy razem z identyfikatorem roota.
        if auto_delete:
            folders.append({"root": root, "path": folder, "auto_delete": True})
        elif root == "media":
            folders.append(folder)
        else:
            folders.append({"root": root, "path": folder})
    if len(folders) > 20:
        raise ValueError("Jedna audycja może monitorować maksymalnie 20 folderów")
    return folders


def normalize_repeats(
    value: Any,
    default_folder: str = "",
    default_filename: str = "",
) -> list[dict[str, Any]]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    if not isinstance(value, list):
        return []

    repeats: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    for index, raw in enumerate(value):
        if not isinstance(raw, dict):
            continue
        repeat_id = str(raw.get("id") or uuid.uuid4().hex)
        if repeat_id in used_ids:
            repeat_id = uuid.uuid4().hex
        used_ids.add(repeat_id)
        schedule = normalize_rules(raw.get("schedule", []))
        folder = str(raw.get("folder_pattern", default_folder)).strip()
        filenames = normalize_filename_patterns(
            raw.get("filename_patterns", [raw.get("filename_pattern", default_filename)]),
            default_filename,
        )
        filename = filenames[0] if filenames else ""
        emission_times = normalize_times(raw.get("emission_times"), raw.get("emission_time"))
        repeats.append(
            {
                "id": repeat_id,
                "label": str(raw.get("label") or f"Powtórka {index + 1}").strip(),
                "emission_times": emission_times,
                "emission_time": emission_times[0] if emission_times else None,
                "folder_pattern": folder,
                "filename_pattern": filename,
                "filename_patterns": filenames,
                "schedule": schedule,
                "schedule_description": describe_rules(schedule),
            }
        )
    return repeats


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.RLock()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        with self._write_lock, self.connect() as connection:
            connection.executescript(SCHEMA)
            connection.execute(
                "DELETE FROM production_watch_notification_log WHERE status='pending'"
            )
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(shows)")}
            if "is_ftp" not in columns:
                connection.execute("ALTER TABLE shows ADD COLUMN is_ftp INTEGER NOT NULL DEFAULT 0")
            if "production_watch_folders_json" not in columns:
                connection.execute(
                    "ALTER TABLE shows ADD COLUMN production_watch_folders_json TEXT NOT NULL DEFAULT '[]'"
                )
            if "auto_archive" not in columns:
                connection.execute("ALTER TABLE shows ADD COLUMN auto_archive INTEGER NOT NULL DEFAULT 0")
            if "repeats_json" not in columns:
                connection.execute("ALTER TABLE shows ADD COLUMN repeats_json TEXT NOT NULL DEFAULT '[]'")
            if "additional_patterns_json" not in columns:
                connection.execute("ALTER TABLE shows ADD COLUMN additional_patterns_json TEXT NOT NULL DEFAULT '[]'")
            if "ftp_source_path" not in columns:
                connection.execute("ALTER TABLE shows ADD COLUMN ftp_source_path TEXT NOT NULL DEFAULT ''")
            if "ftp_auto_sync" not in columns:
                connection.execute("ALTER TABLE shows ADD COLUMN ftp_auto_sync INTEGER NOT NULL DEFAULT 0")
            if "ftp_rename_enabled" not in columns:
                connection.execute("ALTER TABLE shows ADD COLUMN ftp_rename_enabled INTEGER NOT NULL DEFAULT 0")
            if "ftp_source_patterns_json" not in columns:
                connection.execute("ALTER TABLE shows ADD COLUMN ftp_source_patterns_json TEXT NOT NULL DEFAULT '[]'")
            if "premiere_slots_json" not in columns:
                connection.execute("ALTER TABLE shows ADD COLUMN premiere_slots_json TEXT NOT NULL DEFAULT '[]'")
            if "has_youtube_version" not in columns:
                connection.execute("ALTER TABLE shows ADD COLUMN has_youtube_version INTEGER NOT NULL DEFAULT 0")
            if "send_to_author" not in columns:
                connection.execute("ALTER TABLE shows ADD COLUMN send_to_author INTEGER NOT NULL DEFAULT 0")
            if "author_email" not in columns:
                connection.execute("ALTER TABLE shows ADD COLUMN author_email TEXT NOT NULL DEFAULT ''")
            if "drive_folder_id" not in columns:
                connection.execute("ALTER TABLE shows ADD COLUMN drive_folder_id TEXT NOT NULL DEFAULT ''")
            if "drive_permission_id" not in columns:
                connection.execute("ALTER TABLE shows ADD COLUMN drive_permission_id TEXT NOT NULL DEFAULT ''")
            if "drive_shared_email" not in columns:
                connection.execute("ALTER TABLE shows ADD COLUMN drive_shared_email TEXT NOT NULL DEFAULT ''")
            if "drive_permissions_json" not in columns:
                connection.execute(
                    "ALTER TABLE shows ADD COLUMN drive_permissions_json TEXT NOT NULL DEFAULT '{}'"
                )
            if "drive_link_permission_id" not in columns:
                connection.execute(
                    "ALTER TABLE shows ADD COLUMN drive_link_permission_id TEXT NOT NULL DEFAULT ''"
                )
            if "duration_minutes" not in columns:
                connection.execute("ALTER TABLE shows ADD COLUMN duration_minutes REAL NOT NULL DEFAULT 45")
                connection.execute(
                    "UPDATE shows SET duration_minutes=5 WHERE lower(name) LIKE '%5 minut%' "
                    "OR lower(name) LIKE '%myśli świętych%' OR lower(name) LIKE '%slowo o slowie%'"
                )
                connection.execute(
                    "UPDATE shows SET duration_minutes=10 WHERE lower(name) LIKE '%święci z nieba%' "
                    "OR lower(name) LIKE '%w drodze do emaus%'"
                )
            if "max_duration_minutes" not in columns:
                connection.execute("ALTER TABLE shows ADD COLUMN max_duration_minutes REAL DEFAULT NULL")
            connection.commit()
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES('session_secret', ?)",
                (secrets.token_hex(32),),
            )
            version_row = connection.execute(
                "SELECT value FROM settings WHERE key='data_model_version'"
            ).fetchone()
            current_version = int(version_row["value"]) if version_row else 1
            if current_version < 2:
                self._migrate_legacy_shows(connection)
            if current_version < 3:
                self._consolidate_part_shows(connection)
            if current_version < 5:
                self._migrate_emission_slots(connection)
            if current_version < DATA_MODEL_VERSION:
                connection.execute(
                    "INSERT INTO settings(key, value) VALUES('data_model_version', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (str(DATA_MODEL_VERSION),),
                )
            connection.commit()

    @staticmethod
    def _migrate_emission_slots(connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            "SELECT id, schedule_json, emission_time, premiere_slots_json FROM shows"
        ).fetchall()
        for row in rows:
            existing = normalize_emission_slots(row["premiere_slots_json"])
            if existing:
                continue
            migrated = normalize_emission_slots([], row["schedule_json"], row["emission_time"])
            connection.execute(
                "UPDATE shows SET premiere_slots_json=? WHERE id=?",
                (json.dumps(migrated, ensure_ascii=False), row["id"]),
            )

    @staticmethod
    def _migrate_legacy_shows(connection: sqlite3.Connection) -> None:
        rows = connection.execute("SELECT * FROM shows ORDER BY id").fetchall()
        groups: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            clean_name, marked_repeat, marked_ftp = clean_legacy_name(row["name"])
            item = {
                "row": row,
                "clean_name": clean_name,
                "marked_repeat": marked_repeat,
                "marked_ftp": marked_ftp,
            }
            groups.setdefault(clean_name.casefold(), []).append(item)

        for group in groups.values():
            main = next((item for item in group if not item["marked_repeat"]), group[0])
            main_row = main["row"]
            main_is_repeat = bool(main["marked_repeat"])
            repeat_rows = [item for item in group if item is not main or main_is_repeat]
            repeats = normalize_repeats(
                main_row["repeats_json"], main_row["folder_pattern"], main_row["filename_pattern"]
            )
            for item in repeat_rows:
                row = item["row"]
                repeats.append(
                    {
                        "id": f"legacy-{row['id']}",
                        "label": f"Powtórka {len(repeats) + 1}",
                        "emission_time": row["emission_time"],
                        "folder_pattern": row["folder_pattern"],
                        "filename_pattern": row["filename_pattern"],
                        "schedule": normalize_rules(row["schedule_json"]),
                    }
                )
            repeats = normalize_repeats(
                repeats, main_row["folder_pattern"], main_row["filename_pattern"]
            )
            main_schedule = [] if main_is_repeat else normalize_rules(main_row["schedule_json"])
            has_schedule = bool(main_schedule) or any(repeat["schedule"] for repeat in repeats)
            is_ftp = bool(main_row["is_ftp"]) or any(item["marked_ftp"] for item in group)
            connection.execute(
                "UPDATE shows SET name=?, active=?, is_ftp=?, schedule_json=?, repeats_json=?, "
                "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (
                    main["clean_name"],
                    1 if bool(main_row["active"]) and has_schedule else 0,
                    1 if is_ftp else 0,
                    json.dumps(main_schedule, ensure_ascii=False),
                    json.dumps(repeats, ensure_ascii=False),
                    main_row["id"],
                ),
            )
            absorbed_ids = [item["row"]["id"] for item in group if item is not main]
            if absorbed_ids:
                placeholders = ",".join("?" for _ in absorbed_ids)
                connection.execute(f"DELETE FROM shows WHERE id IN ({placeholders})", absorbed_ids)

    @staticmethod
    def _consolidate_part_shows(connection: sqlite3.Connection) -> None:
        rows = connection.execute("SELECT * FROM shows ORDER BY id").fetchall()
        groups: dict[str, list[tuple[int, sqlite3.Row, str]]] = {}
        for row in rows:
            match = _PART_MARKER.search(row["name"])
            if not match:
                continue
            base_name = _PART_MARKER.sub("", row["name"]).strip()
            groups.setdefault(base_name.casefold(), []).append((int(match.group(1)), row, base_name))

        for parts in groups.values():
            if len(parts) < 2:
                continue
            parts.sort(key=lambda item: (item[0], item[1]["id"]))
            _, main, base_name = parts[0]
            patterns: list[str] = []
            for _, row, _ in parts:
                for pattern in normalize_filename_patterns(
                    [row["filename_pattern"], *normalize_filename_patterns(row["additional_patterns_json"])]
                ):
                    if pattern not in patterns:
                        patterns.append(pattern)
            repeats: list[dict[str, Any]] = []
            for _, row, _ in parts:
                repeats.extend(normalize_repeats(row["repeats_json"], row["folder_pattern"], row["filename_pattern"]))
            schedule = normalize_rules(main["schedule_json"])
            has_schedule = bool(schedule) or any(repeat["schedule"] for repeat in repeats)
            connection.execute(
                "UPDATE shows SET name=?, filename_pattern=?, additional_patterns_json=?, active=?, "
                "requires_editing=?, is_ftp=?, repeats_json=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (
                    base_name,
                    patterns[0],
                    json.dumps(patterns[1:], ensure_ascii=False),
                    1 if any(bool(row["active"]) for _, row, _ in parts) and has_schedule else 0,
                    1 if any(bool(row["requires_editing"]) for _, row, _ in parts) else 0,
                    1 if any(bool(row["is_ftp"]) for _, row, _ in parts) else 0,
                    json.dumps(normalize_repeats(repeats, main["folder_pattern"], patterns[0]), ensure_ascii=False),
                    main["id"],
                ),
            )
            absorbed = [row["id"] for _, row, _ in parts[1:]]
            placeholders = ",".join("?" for _ in absorbed)
            connection.execute(f"DELETE FROM shows WHERE id IN ({placeholders})", absorbed)

    def consolidate_part_shows(self) -> None:
        with self._write_lock, self.connect() as connection:
            self._consolidate_part_shows(connection)
            connection.commit()

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        with self.connect() as connection:
            row = connection.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._write_lock, self.connect() as connection:
            connection.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
            connection.commit()

    def observe_maintenance_file(
        self,
        kind: str,
        show_id: int,
        scope_path: str,
        relative_path: str,
        file_size: int,
        mtime_ns: int,
        observed_at: str,
        origin: str | None = None,
    ) -> dict[str, Any]:
        """Remember when this exact file version first appeared in a managed folder."""
        with self._write_lock, self.connect() as connection:
            row = connection.execute(
                "SELECT file_size, mtime_ns, first_seen_at, origin FROM file_maintenance_state "
                "WHERE kind=? AND show_id=? AND scope_path=? AND relative_path=?",
                (kind, show_id, scope_path, relative_path),
            ).fetchone()
            same_version = bool(
                row
                and int(row["file_size"]) == int(file_size)
                and int(row["mtime_ns"]) == int(mtime_ns)
            )
            if same_version:
                current_origin = str(origin or row["origin"] or "normal")
                connection.execute(
                    "UPDATE file_maintenance_state SET origin=?, updated_at=CURRENT_TIMESTAMP "
                    "WHERE kind=? AND show_id=? AND scope_path=? AND relative_path=?",
                    (current_origin, kind, show_id, scope_path, relative_path),
                )
                first_seen_at = str(row["first_seen_at"])
            else:
                current_origin = str(origin or "normal")
                first_seen_at = observed_at
                connection.execute(
                    "INSERT INTO file_maintenance_state("
                    "kind, show_id, scope_path, relative_path, file_size, mtime_ns, first_seen_at, origin"
                    ") VALUES(?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(kind, show_id, scope_path, relative_path) DO UPDATE SET "
                    "file_size=excluded.file_size, mtime_ns=excluded.mtime_ns, "
                    "first_seen_at=excluded.first_seen_at, origin=excluded.origin, "
                    "updated_at=CURRENT_TIMESTAMP",
                    (
                        kind,
                        show_id,
                        scope_path,
                        relative_path,
                        int(file_size),
                        int(mtime_ns),
                        first_seen_at,
                        current_origin,
                    ),
                )
            connection.commit()
        return {
            "first_seen_at": first_seen_at,
            "origin": current_origin,
            "version_changed": not same_version,
        }

    def remove_maintenance_file(
        self, kind: str, show_id: int, scope_path: str, relative_path: str
    ) -> None:
        with self._write_lock, self.connect() as connection:
            connection.execute(
                "DELETE FROM file_maintenance_state "
                "WHERE kind=? AND show_id=? AND scope_path=? AND relative_path=?",
                (kind, show_id, scope_path, relative_path),
            )
            connection.commit()

    def prune_maintenance_files(
        self,
        kind: str,
        show_id: int,
        scope_path: str,
        current_paths: set[str],
    ) -> None:
        with self._write_lock, self.connect() as connection:
            rows = connection.execute(
                "SELECT relative_path FROM file_maintenance_state "
                "WHERE kind=? AND show_id=? AND scope_path=?",
                (kind, show_id, scope_path),
            ).fetchall()
            stale = [
                (kind, show_id, scope_path, str(row["relative_path"]))
                for row in rows
                if str(row["relative_path"]) not in current_paths
            ]
            connection.executemany(
                "DELETE FROM file_maintenance_state "
                "WHERE kind=? AND show_id=? AND scope_path=? AND relative_path=?",
                stale,
            )
            connection.commit()

    def clear_maintenance_scope(self, kind: str, show_id: int, scope_path: str = "") -> None:
        with self._write_lock, self.connect() as connection:
            connection.execute(
                "DELETE FROM file_maintenance_state WHERE kind=? AND show_id=? AND scope_path=?",
                (kind, show_id, scope_path),
            )
            connection.commit()

    def record_file_maintenance(
        self,
        action: str,
        show_id: int | None,
        source_path: str,
        target_path: str,
        status: str,
        detail: str = "",
    ) -> None:
        with self._write_lock, self.connect() as connection:
            connection.execute(
                "INSERT INTO file_maintenance_log("
                "action, show_id, source_path, target_path, status, detail"
                ") VALUES(?, ?, ?, ?, ?, ?)",
                (action, show_id, source_path, target_path, status, detail[:4000]),
            )
            connection.execute(
                "DELETE FROM file_maintenance_log WHERE id NOT IN "
                "(SELECT id FROM file_maintenance_log ORDER BY id DESC LIMIT 1000)"
            )
            connection.commit()

    def count_shows(self) -> int:
        with self.connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM shows").fetchone()[0])

    def apply_builtin_ftp_defaults_once(self) -> None:
        """Populate known legacy FTP folders without overwriting later user configuration."""
        with self._write_lock, self.connect() as connection:
            already_applied = connection.execute(
                "SELECT 1 FROM settings WHERE key=?", (FTP_DEFAULTS_APPLIED_KEY,)
            ).fetchone()
            if already_applied:
                return
            rows = connection.execute("SELECT id, name, ftp_source_path FROM shows").fetchall()
            for row in rows:
                source = BUILTIN_FTP_SOURCES.get(str(row["name"]).casefold())
                if not source:
                    continue
                connection.execute(
                    "UPDATE shows SET is_ftp=1, ftp_source_path=CASE WHEN ftp_source_path='' THEN ? ELSE ftp_source_path END, "
                    "ftp_auto_sync=CASE WHEN ftp_source_path='' THEN 1 ELSE ftp_auto_sync END, "
                    "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (source, row["id"]),
                )
            connection.execute(
                "INSERT INTO settings(key, value) VALUES(?, '1')",
                (FTP_DEFAULTS_APPLIED_KEY,),
            )
            connection.commit()

    @staticmethod
    def _row_to_show(row: sqlite3.Row) -> dict[str, Any]:
        premiere_slots = normalize_emission_slots(
            row["premiere_slots_json"], row["schedule_json"], row["emission_time"]
        )
        rules = combined_schedule(premiere_slots)
        premiere_times = sorted(
            {time for slot in premiere_slots for time in slot.get("emission_times", [])}
        )
        requires_editing = bool(row["requires_editing"])
        is_ftp = bool(row["is_ftp"])
        repeats = normalize_repeats(
            row["repeats_json"], row["folder_pattern"], row["filename_pattern"]
        )
        filename_patterns = normalize_filename_patterns(
            [row["filename_pattern"], *normalize_filename_patterns(row["additional_patterns_json"])]
        )
        ftp_source_patterns = normalize_filename_patterns(row["ftp_source_patterns_json"])
        production_watch_folders = normalize_production_watch_folders(
            row["production_watch_folders_json"]
        )
        try:
            drive_permissions = json.loads(row["drive_permissions_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            drive_permissions = {}
        if not isinstance(drive_permissions, dict):
            drive_permissions = {}
        drive_permissions = {
            str(email): str(permission_id)
            for email, permission_id in drive_permissions.items()
            if str(email).strip() and str(permission_id).strip()
        }
        if not drive_permissions and row["drive_shared_email"] and row["drive_permission_id"]:
            drive_permissions[str(row["drive_shared_email"])] = str(row["drive_permission_id"])
        try:
            author_emails = normalize_author_emails(row["author_email"])
        except ValueError:
            author_emails = []
        return {
            "id": row["id"],
            "name": row["name"],
            "folder_pattern": row["folder_pattern"],
            "filename_pattern": row["filename_pattern"],
            "filename_patterns": filename_patterns,
            "emission_time": premiere_times[0] if premiere_times else None,
            "emission_times": premiere_times,
            "premiere_slots": premiere_slots,
            "active": bool(row["active"]),
            "requires_editing": requires_editing,
            "production_watch_folders": production_watch_folders,
            "auto_archive": bool(row["auto_archive"]),
            "is_ftp": is_ftp,
            "ftp_source_path": row["ftp_source_path"],
            "ftp_auto_sync": bool(row["ftp_auto_sync"]),
            "ftp_rename_enabled": bool(row["ftp_rename_enabled"]),
            "ftp_source_patterns": ftp_source_patterns,
            "has_youtube_version": bool(row["has_youtube_version"]),
            "send_to_author": bool(row["send_to_author"]),
            "author_email": row["author_email"],
            "author_emails": author_emails,
            "duration_minutes": float(row["duration_minutes"]),
            "max_duration_minutes": (
                float(row["max_duration_minutes"])
                if row["max_duration_minutes"] is not None
                else None
            ),
            "drive_folder_id": row["drive_folder_id"],
            "drive_permission_id": row["drive_permission_id"],
            "drive_shared_email": row["drive_shared_email"],
            "drive_permissions": drive_permissions,
            "drive_link_permission_id": row["drive_link_permission_id"],
            "tags": derive_tags(requires_editing, is_ftp),
            "schedule": rules,
            "schedule_description": describe_rules(rules),
            "repeats": repeats,
        }

    def list_shows(self, include_inactive: bool = True) -> list[dict[str, Any]]:
        query = "SELECT * FROM shows"
        if not include_inactive:
            query += " WHERE active=1"
        with self.connect() as connection:
            rows = connection.execute(query).fetchall()
        shows = [self._row_to_show(row) for row in rows]
        return sorted(
            shows,
            key=lambda show: (not show["active"], polish_sort_key(show["name"]), show["id"]),
        )

    def get_show(self, show_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM shows WHERE id=?", (show_id,)).fetchone()
        return self._row_to_show(row) if row else None

    def create_show(self, data: dict[str, Any]) -> dict[str, Any]:
        values = self._validate_show(data)
        with self._write_lock, self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO shows(name, folder_pattern, filename_pattern, additional_patterns_json, emission_time, active, "
                "requires_editing, production_watch_folders_json, auto_archive, is_ftp, ftp_source_path, ftp_auto_sync, ftp_rename_enabled, ftp_source_patterns_json, "
                "premiere_slots_json, has_youtube_version, send_to_author, author_email, duration_minutes, max_duration_minutes, schedule_json, repeats_json) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                values,
            )
            connection.commit()
            show_id = int(cursor.lastrowid)
        self.rebuild_timetable_show_entries(show_id)
        return self.get_show(show_id)  # type: ignore[return-value]

    def update_show(self, show_id: int, data: dict[str, Any]) -> dict[str, Any] | None:
        values = self._validate_show(data)
        with self._write_lock, self.connect() as connection:
            previous = connection.execute(
                "SELECT author_email FROM shows WHERE id=?", (show_id,)
            ).fetchone()
            cursor = connection.execute(
                "UPDATE shows SET name=?, folder_pattern=?, filename_pattern=?, additional_patterns_json=?, emission_time=?, active=?, "
                "requires_editing=?, production_watch_folders_json=?, auto_archive=?, is_ftp=?, ftp_source_path=?, ftp_auto_sync=?, ftp_rename_enabled=?, ftp_source_patterns_json=?, "
                "premiere_slots_json=?, has_youtube_version=?, send_to_author=?, author_email=?, duration_minutes=?, max_duration_minutes=?, schedule_json=?, repeats_json=?, "
                "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (*values, show_id),
            )
            new_author_email = str(values[17])
            try:
                previous_author_keys = {
                    email.casefold()
                    for email in normalize_author_emails(
                        previous["author_email"] if previous is not None else ""
                    )
                }
            except ValueError:
                previous_author_keys = set()
            new_author_keys = {
                email.casefold() for email in normalize_author_emails(new_author_email)
            }
            if (
                previous is not None
                and previous_author_keys != new_author_keys
            ):
                connection.execute(
                    "UPDATE author_delivery_log SET status='superseded', "
                    "detail=CASE WHEN detail='' THEN 'Zmieniono listę autorów' ELSE detail END "
                    "WHERE show_id=? AND status='sent'",
                    (show_id,),
                )
            connection.commit()
        if not cursor.rowcount:
            return None
        self.rebuild_timetable_show_entries(show_id)
        return self.get_show(show_id)

    def delete_show(self, show_id: int) -> bool:
        with self._write_lock, self.connect() as connection:
            connection.execute("DELETE FROM timetable_items WHERE show_id=?", (show_id,))
            cursor = connection.execute("DELETE FROM shows WHERE id=?", (show_id,))
            connection.commit()
        return bool(cursor.rowcount)

    @staticmethod
    def _timetable_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "item_id": int(row["item_id"]),
            "name": row["item_name"],
            "category": row["category"],
            "show_id": int(row["show_id"]) if row["show_id"] is not None else None,
            "show_name": row["show_name"],
            "weekday": int(row["weekday"]),
            "start_time": row["start_time"],
            "duration_minutes": float(row["duration_minutes"]),
            "approximate": bool(row["approximate"]),
            "show_role": row["show_role"],
            "note": row["note"],
            "source": row["source"],
        }

    @staticmethod
    def _validate_timetable_entry(data: dict[str, Any]) -> dict[str, Any]:
        try:
            weekday = int(data.get("weekday"))
        except (TypeError, ValueError) as exc:
            raise ValueError("Nieprawidłowy dzień tygodnia") from exc
        duration = normalize_duration_minutes(data.get("duration_minutes"), 5)
        if weekday not in range(7):
            raise ValueError("Dzień tygodnia musi mieścić się w zakresie 0–6")
        start_time = _normalize_time(data.get("start_time"))
        if not start_time:
            raise ValueError("Godzina rozpoczęcia jest wymagana")
        show_id = data.get("show_id")
        if show_id in (None, ""):
            show_id = None
        else:
            try:
                show_id = int(show_id)
            except (TypeError, ValueError) as exc:
                raise ValueError("Nieprawidłowa audycja") from exc
        category = "shows" if show_id is not None else str(data.get("category", "other")).strip()
        if category not in TIMETABLE_CATEGORIES:
            raise ValueError("Nieprawidłowa warstwa ramówki")
        name = str(data.get("name", "")).strip()
        item_id = data.get("item_id")
        try:
            item_id = int(item_id) if item_id not in (None, "") else None
        except (TypeError, ValueError) as exc:
            raise ValueError("Nieprawidłowy element ramówki") from exc
        role = str(data.get("show_role", "")).strip()
        if role not in {"", "main", "repeat"}:
            raise ValueError("Nieprawidłowy rodzaj emisji audycji")
        return {
            "weekday": weekday,
            "start_time": start_time,
            "duration_minutes": duration,
            "approximate": 1 if data.get("approximate", False) else 0,
            "show_role": role if show_id is not None else "",
            "note": str(data.get("note", "")).strip()[:500],
            "source": str(data.get("source", "manual")).strip()[:40] or "manual",
            "show_id": show_id,
            "category": category,
            "name": name,
            "item_id": item_id,
        }

    @staticmethod
    def _resolve_timetable_item(
        connection: sqlite3.Connection, values: dict[str, Any]
    ) -> int:
        if values["show_id"] is not None:
            show = connection.execute(
                "SELECT id, name FROM shows WHERE id=?", (values["show_id"],)
            ).fetchone()
            if not show:
                raise ValueError("Nie znaleziono audycji")
            row = connection.execute(
                "SELECT id FROM timetable_items WHERE show_id=?", (show["id"],)
            ).fetchone()
            if row:
                connection.execute(
                    "UPDATE timetable_items SET name=?, category='shows', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (show["name"], row["id"]),
                )
                return int(row["id"])
            cursor = connection.execute(
                "INSERT INTO timetable_items(name, category, show_id) VALUES(?, 'shows', ?)",
                (show["name"], show["id"]),
            )
            return int(cursor.lastrowid)

        if values["item_id"] is not None:
            row = connection.execute(
                "SELECT id FROM timetable_items WHERE id=? AND show_id IS NULL",
                (values["item_id"],),
            ).fetchone()
            if row:
                return int(row["id"])
        if not values["name"]:
            raise ValueError("Nazwa elementu ramówki jest wymagana")
        row = connection.execute(
            "SELECT id FROM timetable_items WHERE show_id IS NULL AND lower(name)=lower(?) AND category=?",
            (values["name"], values["category"]),
        ).fetchone()
        if row:
            return int(row["id"])
        cursor = connection.execute(
            "INSERT INTO timetable_items(name, category) VALUES(?, ?)",
            (values["name"], values["category"]),
        )
        return int(cursor.lastrowid)

    def timetable(self) -> dict[str, Any]:
        with self.connect() as connection:
            entry_rows = connection.execute(
                "SELECT entries.*, items.name AS item_name, items.category, items.show_id, "
                "shows.name AS show_name FROM timetable_entries AS entries "
                "JOIN timetable_items AS items ON items.id=entries.item_id "
                "LEFT JOIN shows ON shows.id=items.show_id "
                "ORDER BY entries.weekday, entries.start_time, entries.id"
            ).fetchall()
            item_rows = connection.execute(
                "SELECT items.id, items.name, items.category, items.show_id, shows.name AS show_name "
                "FROM timetable_items AS items LEFT JOIN shows ON shows.id=items.show_id "
                "ORDER BY items.category, lower(items.name), items.id"
            ).fetchall()
        return {
            "items": [
                {
                    "id": int(row["id"]),
                    "name": row["name"],
                    "category": row["category"],
                    "show_id": int(row["show_id"]) if row["show_id"] is not None else None,
                    "show_name": row["show_name"],
                }
                for row in item_rows
            ],
            "entries": [self._timetable_row(row) for row in entry_rows],
        }

    def get_timetable_entry(self, entry_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT entries.*, items.name AS item_name, items.category, items.show_id, "
                "shows.name AS show_name FROM timetable_entries AS entries "
                "JOIN timetable_items AS items ON items.id=entries.item_id "
                "LEFT JOIN shows ON shows.id=items.show_id WHERE entries.id=?",
                (entry_id,),
            ).fetchone()
        return self._timetable_row(row) if row else None

    def rebuild_timetable_show_entries(self, show_id: int) -> None:
        show = self.get_show(show_id)
        with self._write_lock, self.connect() as connection:
            item = connection.execute(
                "SELECT id FROM timetable_items WHERE show_id=?", (show_id,)
            ).fetchone()
            if show is None or not show.get("active", False):
                if item:
                    connection.execute("DELETE FROM timetable_items WHERE id=?", (item["id"],))
                    connection.commit()
                return
            duration = normalize_duration_minutes(show.get("duration_minutes"), 45)
            records: list[tuple[int, str, int, str, str]] = []
            sources = [
                (slot, "main", slot.get("label", "Premiera"))
                for slot in show.get("premiere_slots", [])
            ] + [
                (repeat, "repeat", repeat.get("label", "Powtórka"))
                for repeat in show.get("repeats", [])
            ]
            for slot, role, label in sources:
                weekdays = sorted(
                    {
                        int(day)
                        for rule in slot.get("schedule", [])
                        for day in rule.get("weekdays", [])
                        if str(day).isdigit() and int(day) in range(7)
                    }
                )
                times = normalize_times(slot.get("emission_times", []), slot.get("emission_time"))
                description = str(slot.get("schedule_description", "")).strip()
                note = " • ".join(value for value in (label, description) if value)[:500]
                records.extend(
                    (weekday, start_time, duration, role, note)
                    for weekday in weekdays
                    for start_time in times
                )
            if not records:
                if item:
                    connection.execute("DELETE FROM timetable_items WHERE id=?", (item["id"],))
                    connection.commit()
                return
            if item:
                item_id = int(item["id"])
                connection.execute(
                    "UPDATE timetable_items SET name=?, category='shows', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (show["name"], item_id),
                )
                connection.execute("DELETE FROM timetable_entries WHERE item_id=?", (item_id,))
            else:
                cursor = connection.execute(
                    "INSERT INTO timetable_items(name, category, show_id) VALUES(?, 'shows', ?)",
                    (show["name"], show_id),
                )
                item_id = int(cursor.lastrowid)
            for weekday, start_time, item_duration, role, note in records:
                connection.execute(
                    "INSERT INTO timetable_entries(item_id, weekday, start_time, duration_minutes, "
                    "approximate, show_role, note, source) VALUES(?, ?, ?, ?, 0, ?, ?, 'shows')",
                    (item_id, weekday, start_time, item_duration, role, note),
                )
            connection.commit()

    def rebuild_all_timetable_shows(self) -> None:
        for show in self.list_shows(include_inactive=True):
            self.rebuild_timetable_show_entries(int(show["id"]))

    def create_timetable_entry(self, data: dict[str, Any]) -> dict[str, Any]:
        values = self._validate_timetable_entry(data)
        with self._write_lock, self.connect() as connection:
            item_id = self._resolve_timetable_item(connection, values)
            cursor = connection.execute(
                "INSERT INTO timetable_entries(item_id, weekday, start_time, duration_minutes, approximate, "
                "show_role, note, source) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    item_id, values["weekday"], values["start_time"], values["duration_minutes"],
                    values["approximate"], values["show_role"], values["note"], values["source"],
                ),
            )
            entry_id = int(cursor.lastrowid)
            connection.commit()
        return next(entry for entry in self.timetable()["entries"] if entry["id"] == entry_id)

    def update_timetable_entry(self, entry_id: int, data: dict[str, Any]) -> dict[str, Any] | None:
        values = self._validate_timetable_entry(data)
        with self._write_lock, self.connect() as connection:
            if not connection.execute(
                "SELECT 1 FROM timetable_entries WHERE id=?", (entry_id,)
            ).fetchone():
                return None
            item_id = self._resolve_timetable_item(connection, values)
            connection.execute(
                "UPDATE timetable_entries SET item_id=?, weekday=?, start_time=?, duration_minutes=?, "
                "approximate=?, show_role=?, note=?, source=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (
                    item_id, values["weekday"], values["start_time"], values["duration_minutes"],
                    values["approximate"], values["show_role"], values["note"], values["source"], entry_id,
                ),
            )
            connection.commit()
        return next(entry for entry in self.timetable()["entries"] if entry["id"] == entry_id)

    def update_timetable_entries(
        self, updates: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Atomically update independent timetable occurrences selected by the user."""
        if not updates:
            raise ValueError("Nie wybrano emisji do zmiany")
        prepared: list[tuple[int, dict[str, Any]]] = []
        seen: set[int] = set()
        for update in updates:
            try:
                entry_id = int(update.get("id"))
            except (TypeError, ValueError) as exc:
                raise ValueError("Nieprawidłowa emisja ramówki") from exc
            if entry_id in seen:
                raise ValueError("Ta sama emisja została wybrana więcej niż raz")
            seen.add(entry_id)
            prepared.append((entry_id, self._validate_timetable_entry(update)))

        with self._write_lock, self.connect() as connection:
            for entry_id, values in prepared:
                current = connection.execute(
                    "SELECT items.show_id FROM timetable_entries AS entries "
                    "JOIN timetable_items AS items ON items.id=entries.item_id "
                    "WHERE entries.id=?",
                    (entry_id,),
                ).fetchone()
                if current is None:
                    raise ValueError("Nie znaleziono jednej z wybranych emisji")
                if current["show_id"] is not None:
                    raise ValueError(
                        "Masowa zmiana dotyczy tylko niezależnych elementów ramówki"
                    )
                item_id = self._resolve_timetable_item(connection, values)
                connection.execute(
                    "UPDATE timetable_entries SET item_id=?, weekday=?, start_time=?, duration_minutes=?, "
                    "approximate=?, show_role=?, note=?, source=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (
                        item_id,
                        values["weekday"],
                        values["start_time"],
                        values["duration_minutes"],
                        values["approximate"],
                        values["show_role"],
                        values["note"],
                        values["source"],
                        entry_id,
                    ),
                )
            connection.commit()
        entries_by_id = {
            entry["id"]: entry
            for entry in self.timetable()["entries"]
            if entry["id"] in seen
        }
        return [entries_by_id[entry_id] for entry_id, _ in prepared]

    def delete_timetable_entry(self, entry_id: int) -> bool:
        with self._write_lock, self.connect() as connection:
            cursor = connection.execute("DELETE FROM timetable_entries WHERE id=?", (entry_id,))
            connection.commit()
        return bool(cursor.rowcount)

    def seed_timetable(self, entries: list[dict[str, Any]], marker: str) -> int:
        """Insert a prepared recurring weekly timetable exactly once."""
        with self._write_lock, self.connect() as connection:
            if connection.execute("SELECT 1 FROM settings WHERE key=?", (marker,)).fetchone():
                return 0
            inserted = 0
            for raw in entries:
                values = self._validate_timetable_entry({**raw, "source": "xlsx-seed"})
                item_id = self._resolve_timetable_item(connection, values)
                connection.execute(
                    "INSERT INTO timetable_entries(item_id, weekday, start_time, duration_minutes, approximate, "
                    "show_role, note, source) VALUES(?, ?, ?, ?, ?, ?, ?, 'xlsx-seed')",
                    (
                        item_id, values["weekday"], values["start_time"], values["duration_minutes"],
                        values["approximate"], values["show_role"], values["note"],
                    ),
                )
                inserted += 1
            connection.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?)", (marker, str(inserted))
            )
            connection.commit()
        return inserted

    def set_drive_folder(
        self,
        show_id: int,
        folder_id: str,
        permissions: dict[str, str],
        link_permission_id: str = "",
    ) -> None:
        normalized_permissions = {
            str(email).strip(): str(permission_id).strip()
            for email, permission_id in permissions.items()
            if str(email).strip() and str(permission_id).strip()
        }
        first_email, first_permission = next(
            iter(normalized_permissions.items()), ("", "")
        )
        with self._write_lock, self.connect() as connection:
            connection.execute(
                "UPDATE shows SET drive_folder_id=?, drive_permission_id=?, drive_shared_email=?, "
                "drive_permissions_json=?, drive_link_permission_id=?, "
                "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (
                    folder_id,
                    first_permission,
                    first_email,
                    json.dumps(normalized_permissions, ensure_ascii=False),
                    str(link_permission_id).strip(),
                    show_id,
                ),
            )
            connection.commit()

    def record_author_delivery(
        self,
        show_id: int,
        emission_date: str,
        recipient: str,
        status: str,
        files: list[str],
        folder_url: str = "",
        detail: str = "",
    ) -> None:
        with self._write_lock, self.connect() as connection:
            connection.execute(
                "INSERT INTO author_delivery_log(show_id, emission_date, recipient, status, files_json, folder_url, detail) "
                "VALUES(?, ?, ?, ?, ?, ?, ?)",
                (
                    show_id,
                    emission_date,
                    recipient,
                    status,
                    json.dumps(files, ensure_ascii=False),
                    folder_url,
                    detail[:4000],
                ),
            )
            connection.commit()

    def successful_author_deliveries(
        self, emission_date: str
    ) -> dict[tuple[int, str], dict[str, Any]]:
        """Return the latest successful delivery per show and recipient for a date."""
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT show_id, recipient, files_json, folder_url, created_at "
                "FROM author_delivery_log "
                "WHERE emission_date=? AND status='sent' ORDER BY id",
                (emission_date,),
            ).fetchall()
        deliveries: dict[tuple[int, str], dict[str, Any]] = {}
        for row in rows:
            try:
                files = json.loads(row["files_json"])
            except (TypeError, json.JSONDecodeError):
                files = []
            deliveries[(int(row["show_id"]), str(row["recipient"]).casefold())] = {
                "recipient": row["recipient"],
                "files": files if isinstance(files, list) else [],
                "folder_url": row["folder_url"],
                "sent_at": row["created_at"],
            }
        return deliveries

    @staticmethod
    def _validate_show(data: dict[str, Any]) -> tuple[Any, ...]:
        name = str(data.get("name", "")).strip()
        filenames = normalize_filename_patterns(
            data.get("filename_patterns", [data.get("filename_pattern", "")])
        )
        filename = filenames[0] if filenames else ""
        folder = str(data.get("folder_pattern", "")).strip()
        if not name:
            raise ValueError("Nazwa audycji jest wymagana")
        if not filename:
            raise ValueError("Schemat nazwy pliku jest wymagany")
        premiere_slots = normalize_emission_slots(
            data.get("premiere_slots", []), data.get("schedule", []), data.get("emission_time")
        )
        rules = combined_schedule(premiere_slots)
        premiere_times = sorted(
            {time for slot in premiere_slots for time in slot.get("emission_times", [])}
        )
        emission_time = premiere_times[0] if premiere_times else None
        repeats = normalize_repeats(data.get("repeats", []), folder, filename)
        if any(not repeat["filename_pattern"] for repeat in repeats):
            raise ValueError("Każda powtórka musi mieć schemat nazwy pliku")
        if any(len(repeat["filename_patterns"]) != len(filenames) for repeat in repeats):
            raise ValueError("Każda powtórka musi mieć tyle samo części co emisja premierowa")
        has_schedule = bool(premiere_slots) or any(repeat["schedule"] for repeat in repeats)
        active = bool(data.get("active", True)) and has_schedule
        is_ftp = bool(data.get("is_ftp", False))
        ftp_source_path = str(data.get("ftp_source_path", "")).strip()
        if any(character in ftp_source_path for character in ("\0", "\n", "\r")):
            raise ValueError("Nieprawidłowa ścieżka źródłowa FTP")
        if ftp_source_path and not ftp_source_path.startswith("/"):
            ftp_source_path = "/" + ftp_source_path
        if ".." in PurePosixPath(ftp_source_path or "/").parts:
            raise ValueError("Ścieżka źródłowa FTP nie może zawierać '..'")
        ftp_auto_sync = is_ftp and bool(data.get("ftp_auto_sync", False))
        if ftp_auto_sync and not ftp_source_path.strip("/"):
            raise ValueError("Automatyczne pobieranie wymaga folderu źródłowego FTP")
        ftp_source_patterns = normalize_filename_patterns(data.get("ftp_source_patterns", []))
        for pattern in ftp_source_patterns:
            normalize_relative(pattern)
        ftp_rename_enabled = is_ftp and bool(data.get("ftp_rename_enabled", False))
        if ftp_rename_enabled and len(ftp_source_patterns) != len(filenames):
            raise ValueError("Liczba schematów źródłowych FTP musi odpowiadać liczbie części audycji")
        has_youtube_version = bool(data.get("has_youtube_version", False))
        send_to_author = bool(data.get("send_to_author", False))
        author_emails = (
            normalize_author_emails(data.get("author_email", "")) if send_to_author else []
        )
        if send_to_author and not author_emails:
            raise ValueError("Podaj co najmniej jeden adres e-mail autora")
        author_email = ", ".join(author_emails)
        duration_minutes = normalize_duration_minutes(
            data.get("duration_minutes"), default_show_duration(name)
        )
        max_duration_minutes = normalize_max_duration_minutes(
            data.get("max_duration_minutes"), duration_minutes
        )
        production_watch_folders = normalize_production_watch_folders(
            data.get("production_watch_folders", [])
        )
        return (
            name,
            folder,
            filename,
            json.dumps(filenames[1:], ensure_ascii=False),
            emission_time,
            1 if active else 0,
            1 if data.get("requires_editing", False) else 0,
            json.dumps(production_watch_folders, ensure_ascii=False),
            1 if data.get("auto_archive", False) else 0,
            1 if is_ftp else 0,
            ftp_source_path if is_ftp else "",
            1 if ftp_auto_sync else 0,
            1 if ftp_rename_enabled else 0,
            json.dumps(ftp_source_patterns if ftp_rename_enabled else [], ensure_ascii=False),
            json.dumps(premiere_slots, ensure_ascii=False),
            1 if has_youtube_version else 0,
            1 if send_to_author else 0,
            author_email if send_to_author else "",
            duration_minutes,
            max_duration_minutes,
            json.dumps(rules, ensure_ascii=False),
            json.dumps(repeats, ensure_ascii=False),
        )

    def claim_ftp_sync(self, show_id: int, emission_date: str, hour_slot: int) -> bool:
        with self._write_lock, self.connect() as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO ftp_sync_log(show_id, emission_date, hour_slot) VALUES(?, ?, ?)",
                (show_id, emission_date, hour_slot),
            )
            connection.commit()
        return bool(cursor.rowcount)

    def finish_ftp_sync(
        self, show_id: int, emission_date: str, hour_slot: int, status: str, detail: str = ""
    ) -> None:
        with self._write_lock, self.connect() as connection:
            connection.execute(
                "UPDATE ftp_sync_log SET status=?, detail=?, updated_at=CURRENT_TIMESTAMP "
                "WHERE show_id=? AND emission_date=? AND hour_slot=?",
                (status, detail[:12000], show_id, emission_date, hour_slot),
            )
            connection.commit()

    def record_manual_ftp_sync(self, show_id: int, status: str, detail: str = "") -> None:
        with self._write_lock, self.connect() as connection:
            connection.execute(
                "INSERT INTO ftp_manual_sync_log(show_id, status, detail) VALUES(?, ?, ?)",
                (show_id, status, detail[:12000]),
            )
            connection.commit()

    def ftp_sync_history(self, limit: int = 80) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 500))
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT history.id, history.show_id, history.show_name, history.emission_date, "
                "history.hour_slot, history.status, history.detail, history.created_at, "
                "history.updated_at, history.trigger FROM ("
                "SELECT log.id, log.show_id, shows.name AS show_name, log.emission_date, "
                "log.hour_slot, log.status, log.detail, log.created_at, log.updated_at, "
                "'automatic' AS trigger FROM ftp_sync_log AS log "
                "LEFT JOIN shows ON shows.id=log.show_id "
                "UNION ALL "
                "SELECT log.id, log.show_id, shows.name AS show_name, date(log.created_at) AS emission_date, "
                "-1 AS hour_slot, log.status, log.detail, log.created_at, log.updated_at, "
                "'manual' AS trigger FROM ftp_manual_sync_log AS log "
                "LEFT JOIN shows ON shows.id=log.show_id"
                ") AS history ORDER BY history.updated_at DESC, history.id DESC LIMIT ?",
                (safe_limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def record_import(self, source: str, imported: int, warnings: list[str]) -> None:
        visible_warnings = filter_import_warnings(warnings)
        with self._write_lock, self.connect() as connection:
            connection.execute(
                "INSERT INTO import_log(source, imported, warnings_json) VALUES(?, ?, ?)",
                (source, imported, json.dumps(visible_warnings, ensure_ascii=False)),
            )
            connection.commit()

    def latest_import(self) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM import_log ORDER BY id DESC LIMIT 1").fetchone()
        if not row:
            return None
        return {
            "source": row["source"],
            "imported": row["imported"],
            "warnings": filter_import_warnings(json.loads(row["warnings_json"])),
            "created_at": row["created_at"],
        }

    def scan_production_folder(
        self,
        show_id: int,
        folder_path: str,
        relative_files: list[str],
        detected_at: str,
    ) -> dict[str, Any]:
        current = sorted(set(relative_files))
        with self._write_lock, self.connect() as connection:
            marker = connection.execute(
                "SELECT 1 FROM production_watch_folders WHERE show_id=? AND folder_path=?",
                (show_id, folder_path),
            ).fetchone()
            if marker is None:
                connection.execute(
                    "INSERT INTO production_watch_folders(show_id, folder_path) VALUES(?, ?)",
                    (show_id, folder_path),
                )
                connection.executemany(
                    "INSERT INTO production_watch_files(show_id, folder_path, relative_path, event_id, pending) "
                    "VALUES(?, ?, ?, ?, 0)",
                    [(show_id, folder_path, path, uuid.uuid4().hex) for path in current],
                )
                connection.commit()
                return {"initialized": True, "pending": []}

            rows = connection.execute(
                "SELECT relative_path, event_id FROM production_watch_files "
                "WHERE show_id=? AND folder_path=?",
                (show_id, folder_path),
            ).fetchall()
            known = {str(row["relative_path"]): str(row["event_id"]) for row in rows}
            missing = sorted(set(known) - set(current))
            if missing:
                event_ids = [known[path] for path in missing]
                connection.executemany(
                    "DELETE FROM production_watch_notification_log WHERE event_id=?",
                    [(event_id,) for event_id in event_ids],
                )
                connection.executemany(
                    "DELETE FROM production_watch_files WHERE show_id=? AND folder_path=? AND relative_path=?",
                    [(show_id, folder_path, path) for path in missing],
                )
            additions = sorted(set(current) - set(known))
            connection.executemany(
                "INSERT INTO production_watch_files(show_id, folder_path, relative_path, event_id, detected_at, pending) "
                "VALUES(?, ?, ?, ?, ?, 1)",
                [(show_id, folder_path, path, uuid.uuid4().hex, detected_at) for path in additions],
            )
            connection.execute(
                "UPDATE production_watch_folders SET last_scan_at=CURRENT_TIMESTAMP "
                "WHERE show_id=? AND folder_path=?",
                (show_id, folder_path),
            )
            pending = connection.execute(
                "SELECT relative_path, event_id, detected_at FROM production_watch_files "
                "WHERE show_id=? AND folder_path=? AND pending=1 ORDER BY detected_at, relative_path",
                (show_id, folder_path),
            ).fetchall()
            connection.commit()
        return {"initialized": False, "pending": [dict(row) for row in pending]}

    def prune_production_watch_configuration(
        self, configured: set[tuple[int, str]]
    ) -> None:
        with self._write_lock, self.connect() as connection:
            rows = connection.execute(
                "SELECT show_id, folder_path FROM production_watch_folders"
            ).fetchall()
            stale = [
                (int(row["show_id"]), str(row["folder_path"]))
                for row in rows
                if (int(row["show_id"]), str(row["folder_path"])) not in configured
            ]
            for show_id, folder_path in stale:
                events = connection.execute(
                    "SELECT event_id FROM production_watch_files WHERE show_id=? AND folder_path=?",
                    (show_id, folder_path),
                ).fetchall()
                connection.executemany(
                    "DELETE FROM production_watch_notification_log WHERE event_id=?",
                    [(str(row["event_id"]),) for row in events],
                )
                connection.execute(
                    "DELETE FROM production_watch_files WHERE show_id=? AND folder_path=?",
                    (show_id, folder_path),
                )
                connection.execute(
                    "DELETE FROM production_watch_folders WHERE show_id=? AND folder_path=?",
                    (show_id, folder_path),
                )
            connection.commit()

    def claim_production_notification(self, event_id: str, recipient_id: str) -> bool:
        with self._write_lock, self.connect() as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO production_watch_notification_log(event_id, recipient_id) "
                "VALUES(?, ?)",
                (event_id, recipient_id),
            )
            connection.commit()
        return bool(cursor.rowcount)

    def finish_production_notification(
        self, event_id: str, recipient_id: str, detail: str = ""
    ) -> None:
        with self._write_lock, self.connect() as connection:
            connection.execute(
                "UPDATE production_watch_notification_log SET status='sent', detail=?, "
                "updated_at=CURRENT_TIMESTAMP WHERE event_id=? AND recipient_id=?",
                (detail[:1000], event_id, recipient_id),
            )
            connection.commit()

    def release_production_notification(self, event_id: str, recipient_id: str) -> None:
        with self._write_lock, self.connect() as connection:
            connection.execute(
                "DELETE FROM production_watch_notification_log "
                "WHERE event_id=? AND recipient_id=? AND status='pending'",
                (event_id, recipient_id),
            )
            connection.commit()

    def complete_production_events(
        self, event_ids: list[str], recipient_ids: list[str]
    ) -> None:
        if not event_ids:
            return
        with self._write_lock, self.connect() as connection:
            for event_id in event_ids:
                if recipient_ids:
                    placeholders = ",".join("?" for _ in recipient_ids)
                    sent = connection.execute(
                        f"SELECT COUNT(*) FROM production_watch_notification_log "
                        f"WHERE event_id=? AND status='sent' AND recipient_id IN ({placeholders})",
                        (event_id, *recipient_ids),
                    ).fetchone()[0]
                    if int(sent) < len(recipient_ids):
                        continue
                connection.execute(
                    "UPDATE production_watch_files SET pending=0 WHERE event_id=?",
                    (event_id,),
                )
            connection.commit()

    def claim_notification(
        self,
        show_id: int,
        occurrence_key: str,
        emission_date: str,
        lead_minutes: int,
        recipient_id: str,
    ) -> bool:
        with self._write_lock, self.connect() as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO notification_log("
                "show_id, occurrence_key, emission_date, lead_minutes, recipient_id"
                ") VALUES(?, ?, ?, ?, ?)",
                (show_id, occurrence_key, emission_date, lead_minutes, recipient_id),
            )
            connection.commit()
        return bool(cursor.rowcount)

    def ignore_report_occurrence(
        self, show_id: int, occurrence_key: str, emission_date: str
    ) -> None:
        with self._write_lock, self.connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO report_ignored_occurrences("
                "show_id, occurrence_key, emission_date) VALUES(?, ?, ?)",
                (show_id, occurrence_key, emission_date),
            )
            connection.commit()

    def ignored_report_occurrences(self, emission_date: str) -> set[tuple[int, str]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT show_id, occurrence_key FROM report_ignored_occurrences "
                "WHERE emission_date=?",
                (emission_date,),
            ).fetchall()
        return {(int(row["show_id"]), str(row["occurrence_key"])) for row in rows}

    def is_report_occurrence_ignored(
        self, show_id: int, occurrence_key: str, emission_date: str
    ) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM report_ignored_occurrences "
                "WHERE show_id=? AND occurrence_key=? AND emission_date=?",
                (show_id, occurrence_key, emission_date),
            ).fetchone()
        return row is not None

    def finish_notification(
        self,
        show_id: int,
        occurrence_key: str,
        emission_date: str,
        lead_minutes: int,
        recipient_id: str,
        status: str,
        detail: str = "",
    ) -> None:
        with self._write_lock, self.connect() as connection:
            connection.execute(
                "UPDATE notification_log SET status=?, detail=? WHERE "
                "show_id=? AND occurrence_key=? AND emission_date=? AND lead_minutes=? AND recipient_id=?",
                (
                    status,
                    detail[:1000],
                    show_id,
                    occurrence_key,
                    emission_date,
                    lead_minutes,
                    recipient_id,
                ),
            )
            connection.commit()

    def release_notification(
        self,
        show_id: int,
        occurrence_key: str,
        emission_date: str,
        lead_minutes: int,
        recipient_id: str,
    ) -> None:
        with self._write_lock, self.connect() as connection:
            connection.execute(
                "DELETE FROM notification_log WHERE show_id=? AND occurrence_key=? "
                "AND emission_date=? AND lead_minutes=? AND recipient_id=? AND status='pending'",
                (show_id, occurrence_key, emission_date, lead_minutes, recipient_id),
            )
            connection.commit()


def database_from_env() -> Database:
    path = os.getenv("DATABASE_PATH", "/data/sprawdzacz.db")
    return Database(path)
