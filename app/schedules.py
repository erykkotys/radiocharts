from __future__ import annotations

import calendar
import datetime as dt
import json
from typing import Any


WEEKDAY_NAMES = [
    "Poniedziałek",
    "Wtorek",
    "Środa",
    "Czwartek",
    "Piątek",
    "Sobota",
    "Niedziela",
]


def _ints(value: Any, minimum: int, maximum: int) -> list[int]:
    if not isinstance(value, list):
        return []
    result: list[int] = []
    for item in value:
        try:
            number = int(item)
        except (TypeError, ValueError):
            continue
        if minimum <= number <= maximum and number not in result:
            result.append(number)
    return result


def normalize_rules(value: Any) -> list[dict[str, Any]]:
    """Return a safe, canonical list of schedule rules."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    if not isinstance(value, list):
        return []

    normalized: list[dict[str, Any]] = []
    for raw in value:
        if not isinstance(raw, dict):
            continue
        rule_type = raw.get("type")
        if rule_type == "weekly":
            weekdays = _ints(raw.get("weekdays"), 0, 6)
            if weekdays:
                normalized.append({"type": "weekly", "weekdays": weekdays})
        elif rule_type == "nth_month":
            weekdays = _ints(raw.get("weekdays"), 0, 6)
            occurrences = _ints(raw.get("occurrences"), 1, 5)
            if weekdays and occurrences:
                normalized.append(
                    {
                        "type": "nth_month",
                        "weekdays": weekdays,
                        "occurrences": occurrences,
                    }
                )
        elif rule_type == "iso_week_parity":
            weekdays = _ints(raw.get("weekdays"), 0, 6)
            parity = raw.get("parity")
            if weekdays and parity in {"even", "odd"}:
                normalized.append(
                    {
                        "type": "iso_week_parity",
                        "weekdays": weekdays,
                        "parity": parity,
                    }
                )
        elif rule_type == "dates":
            dates: list[str] = []
            for date_text in raw.get("dates", []):
                try:
                    parsed = dt.date.fromisoformat(str(date_text))
                except ValueError:
                    continue
                canonical = parsed.isoformat()
                if canonical not in dates:
                    dates.append(canonical)
            if dates:
                normalized.append({"type": "dates", "dates": dates})
    return normalized


def nth_weekday_occurrence(day: dt.date) -> int:
    return (day.day - 1) // 7 + 1


def matches_date(rules: Any, day: dt.date) -> bool:
    for rule in normalize_rules(rules):
        rule_type = rule["type"]
        if rule_type == "weekly" and day.weekday() in rule["weekdays"]:
            return True
        if (
            rule_type == "nth_month"
            and day.weekday() in rule["weekdays"]
            and nth_weekday_occurrence(day) in rule["occurrences"]
        ):
            return True
        if rule_type == "iso_week_parity" and day.weekday() in rule["weekdays"]:
            week_is_even = day.isocalendar().week % 2 == 0
            if (rule["parity"] == "even") == week_is_even:
                return True
        if rule_type == "dates" and day.isoformat() in rule["dates"]:
            return True
    return False


def describe_rules(rules: Any) -> str:
    parts: list[str] = []
    for rule in normalize_rules(rules):
        days = ", ".join(WEEKDAY_NAMES[i][:2] for i in rule.get("weekdays", []))
        if rule["type"] == "weekly":
            parts.append(f"co tydzień: {days}")
        elif rule["type"] == "nth_month":
            nth = ", ".join(str(i) for i in rule["occurrences"])
            parts.append(f"{nth}. w miesiącu: {days}")
        elif rule["type"] == "iso_week_parity":
            parity = "parzyste tygodnie" if rule["parity"] == "even" else "nieparzyste tygodnie"
            parts.append(f"{days}, {parity}")
        elif rule["type"] == "dates":
            formatted = [dt.date.fromisoformat(item).strftime("%d.%m.%Y") for item in rule["dates"]]
            parts.append("daty: " + ", ".join(formatted))
    return " • ".join(parts) if parts else "Brak emisji"


def legacy_schedule_to_rules(value: Any) -> tuple[list[dict[str, Any]], list[str]]:
    """Convert the syntax used by the old XLS script to structured rules."""
    text = "" if value is None else str(value).strip()
    if not text or text.lower() == "nan":
        return [], []

    grouped: dict[tuple[str, str], set[int]] = {}
    dates: list[str] = []
    warnings: list[str] = []
    for token in (item.strip() for item in text.split(",")):
        if not token:
            continue
        try:
            if "@" in token:
                weekday_text, parity_pl = token.split("@", 1)
                if parity_pl == "niepatrzysty":
                    parity_pl = "nieparzysty"
                    warnings.append(f"Poprawiono literówkę w regule: {token}")
                parity = {"parzysty": "even", "nieparzysty": "odd"}.get(parity_pl)
                if parity is None:
                    raise ValueError("nieznana parzystość")
                weekday = int(weekday_text) - 1
                if weekday not in range(7):
                    raise ValueError("dzień poza zakresem")
                grouped.setdefault(("iso_week_parity", parity), set()).add(weekday)
            elif "#" in token:
                weekday_text, occurrence_text = token.split("#", 1)
                weekday = int(weekday_text) - 1
                occurrence = int(occurrence_text)
                if weekday not in range(7) or occurrence not in range(1, 6):
                    raise ValueError("wartość poza zakresem")
                grouped.setdefault(("nth_month", str(occurrence)), set()).add(weekday)
            elif "-" in token:
                dates.append(dt.date.fromisoformat(token).isoformat())
            else:
                weekday = int(token) - 1
                if weekday not in range(7):
                    raise ValueError("dzień poza zakresem")
                grouped.setdefault(("weekly", ""), set()).add(weekday)
        except (ValueError, TypeError) as exc:
            warnings.append(f"Pominięto nieprawidłową regułę „{token}”: {exc}")

    rules: list[dict[str, Any]] = []
    weekly = grouped.get(("weekly", ""))
    if weekly:
        rules.append({"type": "weekly", "weekdays": sorted(weekly)})
    for parity in ("even", "odd"):
        weekdays = grouped.get(("iso_week_parity", parity))
        if weekdays:
            rules.append(
                {"type": "iso_week_parity", "weekdays": sorted(weekdays), "parity": parity}
            )
    nth_by_weekdays: dict[tuple[int, ...], list[int]] = {}
    for occurrence in range(1, 6):
        weekdays = grouped.get(("nth_month", str(occurrence)))
        if weekdays:
            nth_by_weekdays.setdefault(tuple(sorted(weekdays)), []).append(occurrence)
    for weekdays, occurrences in nth_by_weekdays.items():
        rules.append(
            {
                "type": "nth_month",
                "weekdays": list(weekdays),
                "occurrences": occurrences,
            }
        )
    if dates:
        rules.append({"type": "dates", "dates": sorted(set(dates))})
    return rules, warnings


def month_calendar(year: int, month: int) -> list[list[int]]:
    """Small helper kept public for UI/calendar tests."""
    return calendar.Calendar(firstweekday=0).monthdayscalendar(year, month)

