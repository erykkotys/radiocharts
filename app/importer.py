from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from .db import Database, clean_legacy_name, filter_import_warnings
from .schedules import legacy_schedule_to_rules


REQUIRED_COLUMNS = {
    "Nazwa audycji",
    "Folder",
    "Dzień emisji",
    "Schemat nazwy pliku",
}


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def read_legacy_xls(path: str | Path) -> list[dict[str, Any]]:
    try:
        import xlrd
    except ImportError as exc:  # pragma: no cover - dependency is present in Docker
        raise RuntimeError("Brak biblioteki xlrd potrzebnej do importu pliku .xls") from exc

    workbook = xlrd.open_workbook(str(path))
    sheet = workbook.sheet_by_index(0)
    if sheet.nrows < 1:
        return []
    headers = [_text(sheet.cell_value(0, column)) for column in range(sheet.ncols)]
    missing = REQUIRED_COLUMNS.difference(headers)
    if missing:
        raise ValueError("Brak kolumn: " + ", ".join(sorted(missing)))

    rows: list[dict[str, Any]] = []
    for row_index in range(1, sheet.nrows):
        row = {
            headers[column]: sheet.cell_value(row_index, column)
            for column in range(sheet.ncols)
            if headers[column]
        }
        if _text(row.get("Nazwa audycji")):
            rows.append(row)
    return rows


def import_legacy_xls(database: Database, path: str | Path) -> dict[str, Any]:
    rows = read_legacy_xls(path)
    warnings: list[str] = []
    entries: list[dict[str, Any]] = []
    for row_number, row in enumerate(rows, start=2):
        legacy_name = _text(row.get("Nazwa audycji"))
        name, is_repeat, is_ftp = clean_legacy_name(legacy_name)
        rules, row_warnings = legacy_schedule_to_rules(_text(row.get("Dzień emisji")))
        warnings.extend(f"Wiersz {row_number} ({legacy_name}): {item}" for item in row_warnings)
        entries.append(
            {
                "name": name,
                "is_repeat": is_repeat,
                "is_ftp": is_ftp,
                "folder_pattern": _text(row.get("Folder")),
                "filename_pattern": _text(row.get("Schemat nazwy pliku")),
                "requires_editing": _text(row.get("PRODUKCJA", row.get("MONTAŻ"))).upper() == "TAK",
                "schedule": rules,
            }
        )

    groups: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        groups.setdefault(entry["name"].casefold(), []).append(entry)

    for group in groups.values():
        main = next((entry for entry in group if not entry["is_repeat"]), group[0])
        main_is_repeat = bool(main["is_repeat"])
        repeat_entries = [entry for entry in group if entry is not main or main_is_repeat]
        repeats = [
            {
                "label": f"Powtórka {index + 1}",
                "folder_pattern": entry["folder_pattern"],
                "filename_pattern": entry["filename_pattern"],
                "schedule": entry["schedule"],
            }
            for index, entry in enumerate(repeat_entries)
        ]
        database.create_show(
            {
                "name": main["name"],
                "folder_pattern": main["folder_pattern"],
                "filename_pattern": main["filename_pattern"],
                "requires_editing": any(entry["requires_editing"] for entry in group),
                "is_ftp": any(entry["is_ftp"] for entry in group),
                "active": True,
                "schedule": [] if main_is_repeat else main["schedule"],
                "repeats": repeats,
            }
        )
    database.consolidate_part_shows()
    imported = len(entries)
    warnings = filter_import_warnings(warnings)
    database.record_import(Path(path).name, imported, warnings)
    return {"imported": imported, "shows": database.count_shows(), "warnings": warnings}


def seed_if_empty(database: Database, seed_path: str | Path) -> dict[str, Any] | None:
    seed = Path(seed_path)
    if database.count_shows() or not seed.is_file():
        return None
    return import_legacy_xls(database, seed)
