from __future__ import annotations

import json
import re
import unicodedata
import uuid
from pathlib import Path
from typing import Any

from .db import Database, normalize_duration_minutes, normalize_times


TIMETABLE_SEED_MARKER = "timetable_autumn_2026_v1"
TIMETABLE_SHOW_TIMES_MARKER = "timetable_autumn_2026_show_times_v1"


def normalized_title(value: Any) -> str:
    source = str(value or "").translate(str.maketrans({"ł": "l", "Ł": "L"}))
    text = unicodedata.normalize("NFKD", source).encode("ascii", "ignore").decode()
    text = text.casefold().replace("&", " i ")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _show_lookup(database: Database) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for show in database.list_shows(include_inactive=True):
        lookup[normalized_title(show["name"])] = show
    return lookup


def _prepare_entries(
    database: Database, raw_entries: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[tuple[dict[str, Any], dict[str, Any]]]]:
    lookup = _show_lookup(database)
    prepared: list[dict[str, Any]] = []
    linked: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for raw in raw_entries:
        item = dict(raw)
        show_name = item.pop("show_name", None)
        show = lookup.get(normalized_title(show_name)) if show_name else None
        if show:
            linked.append((raw, show))
            continue
        else:
            item["show_id"] = None
            if item.get("category") == "shows":
                item["category"] = "other"
        prepared.append(item)
    return prepared, linked


def _slot_weekdays(slot: dict[str, Any]) -> set[int]:
    result: set[int] = set()
    for rule in slot.get("schedule", []):
        for weekday in rule.get("weekdays", []):
            try:
                day = int(weekday)
            except (TypeError, ValueError):
                continue
            if day in range(7):
                result.add(day)
    return result


def _fill_slot_times(
    slot: dict[str, Any], times_by_weekday: dict[int, set[str]]
) -> list[dict[str, Any]]:
    if slot.get("emission_times"):
        return [slot]
    weekdays = _slot_weekdays(slot)
    if not weekdays:
        return [slot]
    schedule = slot.get("schedule", [])
    simple_weekly = len(schedule) == 1 and schedule[0].get("type") == "weekly"
    if not simple_weekly:
        times = sorted({time for day in weekdays for time in times_by_weekday.get(day, set())})
        return [{**slot, "emission_times": times, "emission_time": times[0] if times else None}]

    grouped: dict[tuple[str, ...], list[int]] = {}
    for weekday in sorted(weekdays):
        key = tuple(sorted(times_by_weekday.get(weekday, set())))
        grouped.setdefault(key, []).append(weekday)
    if len(grouped) == 1:
        times = list(next(iter(grouped)))
        return [{**slot, "emission_times": times, "emission_time": times[0] if times else None}]

    result: list[dict[str, Any]] = []
    for index, (times_tuple, days) in enumerate(grouped.items()):
        times = list(times_tuple)
        result.append(
            {
                **slot,
                "id": slot.get("id") if index == 0 else uuid.uuid4().hex,
                "label": slot.get("label") or f"Plan {index + 1}",
                "schedule": [{"type": "weekly", "weekdays": days}],
                "emission_times": times,
                "emission_time": times[0] if times else None,
            }
        )
    return result


def _is_simple_weekly(slot: dict[str, Any]) -> bool:
    schedule = slot.get("schedule", [])
    return len(schedule) == 1 and schedule[0].get("type") == "weekly"


def _compress_weekly_slot(
    slot: dict[str, Any], pairs: set[tuple[int, str]]
) -> list[dict[str, Any]]:
    if not pairs:
        return []
    day_times: dict[int, set[str]] = {}
    for weekday, start_time in pairs:
        day_times.setdefault(weekday, set()).add(start_time)
    grouped: dict[tuple[str, ...], list[int]] = {}
    for weekday, times in sorted(day_times.items()):
        grouped.setdefault(tuple(sorted(times)), []).append(weekday)
    result: list[dict[str, Any]] = []
    for index, (times_tuple, weekdays) in enumerate(grouped.items()):
        times = list(times_tuple)
        result.append(
            {
                **slot,
                "id": slot.get("id") if index == 0 else uuid.uuid4().hex,
                "schedule": [{"type": "weekly", "weekdays": weekdays}],
                "emission_times": times,
                "emission_time": times[0],
            }
        )
    return result


def _change_occurrence(
    slots: list[dict[str, Any]],
    old_weekday: int,
    old_time: str,
    new_weekday: int | None,
    new_time: str | None,
) -> tuple[list[dict[str, Any]], bool]:
    result: list[dict[str, Any]] = []
    changed = False
    for slot in slots:
        weekdays = _slot_weekdays(slot)
        times = set(slot.get("emission_times", []))
        if changed or old_weekday not in weekdays or old_time not in times:
            result.append(slot)
            continue
        if _is_simple_weekly(slot):
            pairs = {(weekday, time) for weekday in weekdays for time in times}
            pairs.discard((old_weekday, old_time))
            if new_weekday is not None and new_time is not None:
                pairs.add((new_weekday, new_time))
            result.extend(_compress_weekly_slot(slot, pairs))
        else:
            if len(weekdays) != 1:
                raise ValueError(
                    "To jest złożony harmonogram. Zmień go w edycji Audycji."
                )
            updated = dict(slot)
            if new_weekday is None or new_time is None:
                remaining = sorted(time for time in times if time != old_time)
                if remaining:
                    updated["emission_times"] = remaining
                    updated["emission_time"] = remaining[0]
                    result.append(updated)
            else:
                updated["schedule"] = [
                    {
                        **rule,
                        "weekdays": [new_weekday if int(day) == old_weekday else int(day) for day in rule.get("weekdays", [])],
                    }
                    for rule in slot.get("schedule", [])
                ]
                updated_times = sorted({new_time if time == old_time else time for time in times})
                updated["emission_times"] = updated_times
                updated["emission_time"] = updated_times[0]
                result.append(updated)
        changed = True
    return result, changed


def _add_show_occurrence(show: dict[str, Any], entry: dict[str, Any]) -> None:
    weekday = int(entry["weekday"])
    start_time = str(entry["start_time"])
    if entry.get("show_role") == "repeat":
        patterns = list(show.get("filename_patterns", [show.get("filename_pattern", "")]))
        show.setdefault("repeats", []).append(
            {
                "id": uuid.uuid4().hex,
                "label": f"Powtórka {len(show.get('repeats', [])) + 1}",
                "folder_pattern": show.get("folder_pattern", ""),
                "filename_pattern": patterns[0] if patterns else "",
                "filename_patterns": patterns,
                "schedule": [{"type": "weekly", "weekdays": [weekday]}],
                "emission_times": [start_time],
            }
        )
    else:
        show.setdefault("premiere_slots", []).append(
            {
                "id": uuid.uuid4().hex,
                "label": f"Plan {len(show.get('premiere_slots', [])) + 1}",
                "schedule": [{"type": "weekly", "weekdays": [weekday]}],
                "emission_times": [start_time],
            }
        )


def sync_show_timetable_entry(
    database: Database,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Apply an intentional timetable edit back to the linked show schedule."""
    if after is not None:
        after = dict(after)
        try:
            weekday = int(after.get("weekday"))
        except (TypeError, ValueError) as exc:
            raise ValueError("Nieprawidłowy dzień tygodnia") from exc
        if weekday not in range(7):
            raise ValueError("Nieprawidłowy dzień tygodnia")
        times = normalize_times([after.get("start_time")])
        if not times:
            raise ValueError("Godzina rozpoczęcia jest wymagana")
        after["weekday"] = weekday
        after["start_time"] = times[0]
        after["show_role"] = "repeat" if after.get("show_role") == "repeat" else "main"
        after["duration_minutes"] = normalize_duration_minutes(
            after.get("duration_minutes"), 45
        )
    before_show_id = int(before["show_id"]) if before and before.get("show_id") else None
    after_show_id = int(after["show_id"]) if after and after.get("show_id") else None

    if before_show_id is not None:
        show = database.get_show(before_show_id)
        if show is None:
            raise ValueError("Nie znaleziono audycji")
        key = "repeats" if before.get("show_role") == "repeat" else "premiere_slots"
        slots, changed = _change_occurrence(
            list(show.get(key, [])),
            int(before["weekday"]),
            str(before["start_time"]),
            int(after["weekday"]) if after and after_show_id == before_show_id and after.get("show_role") == before.get("show_role") else None,
            str(after["start_time"]) if after and after_show_id == before_show_id and after.get("show_role") == before.get("show_role") else None,
        )
        if not changed:
            raise ValueError("Nie znaleziono tej emisji w harmonogramie audycji")
        show[key] = slots
        if after and after_show_id == before_show_id:
            show["duration_minutes"] = after["duration_minutes"]
        show["schedule"] = []
        show["emission_time"] = None
        database.update_show(before_show_id, show)

    if after_show_id is not None and not (
        before_show_id == after_show_id
        and before
        and after.get("show_role") == before.get("show_role")
    ):
        show = database.get_show(after_show_id)
        if show is None:
            raise ValueError("Nie znaleziono audycji")
        _add_show_occurrence(show, after)
        show["duration_minutes"] = after["duration_minutes"]
        show["schedule"] = []
        show["emission_time"] = None
        database.update_show(after_show_id, show)

    if after_show_id is None:
        return None
    candidates = [
        entry
        for entry in database.timetable()["entries"]
        if entry.get("show_id") == after_show_id
        and entry.get("show_role") == after.get("show_role")
        and entry.get("weekday") == int(after["weekday"])
        and entry.get("start_time") == str(after["start_time"])
    ]
    return candidates[0] if candidates else None


def supplement_empty_show_times(
    database: Database, raw_entries: list[dict[str, Any]]
) -> int:
    if database.get_setting(TIMETABLE_SHOW_TIMES_MARKER):
        return 0
    lookup = _show_lookup(database)
    grouped: dict[tuple[int, str], dict[int, set[str]]] = {}
    for entry in raw_entries:
        show_name = entry.get("show_name")
        show = lookup.get(normalized_title(show_name)) if show_name else None
        if not show:
            continue
        role = "repeat" if entry.get("show_role") == "repeat" else "main"
        grouped.setdefault((int(show["id"]), role), {}).setdefault(
            int(entry["weekday"]), set()
        ).add(str(entry["start_time"]))

    changed = 0
    for show in database.list_shows(include_inactive=True):
        show_changed = False
        main_times = grouped.get((int(show["id"]), "main"), {})
        if main_times:
            slots: list[dict[str, Any]] = []
            for slot in show.get("premiere_slots", []):
                filled = _fill_slot_times(slot, main_times)
                slots.extend(filled)
                show_changed = show_changed or filled != [slot]
            show["premiere_slots"] = slots

        repeat_times = grouped.get((int(show["id"]), "repeat"), {})
        if repeat_times:
            updated_repeats: list[dict[str, Any]] = []
            for repeat in show.get("repeats", []):
                if repeat.get("emission_times"):
                    updated_repeats.append(repeat)
                    continue
                weekdays = _slot_weekdays(repeat)
                times = sorted(
                    {time for day in weekdays for time in repeat_times.get(day, set())}
                )
                updated = {
                    **repeat,
                    "emission_times": times,
                    "emission_time": times[0] if times else None,
                }
                updated_repeats.append(updated)
                show_changed = show_changed or updated != repeat
            show["repeats"] = updated_repeats

        if show_changed:
            database.update_show(int(show["id"]), show)
            changed += 1
    database.set_setting(TIMETABLE_SHOW_TIMES_MARKER, str(changed))
    return changed


def seed_timetable_if_needed(database: Database, seed_path: str | Path) -> dict[str, int]:
    path = Path(seed_path)
    if not path.is_file():
        return {"entries": 0, "shows_supplemented": 0}
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_entries = payload.get("entries", [])
    if not isinstance(raw_entries, list):
        raise ValueError("Nieprawidłowy plik startowy ramówki")
    supplemented = supplement_empty_show_times(database, raw_entries)
    prepared, _ = _prepare_entries(database, raw_entries)
    inserted = database.seed_timetable(prepared, TIMETABLE_SEED_MARKER)
    database.rebuild_all_timetable_shows()
    return {"entries": inserted, "shows_supplemented": supplemented}
