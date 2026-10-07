from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any
from urllib.parse import quote

try:
    import requests
except ModuleNotFoundError:  # Pakiet jest instalowany w obrazie produkcyjnym.
    requests = None  # type: ignore[assignment]

from .delivery import _json_response, load_delivery_config


CALENDAR_API = "https://www.googleapis.com/calendar/v3"
WRITABLE_ROLES = {"owner", "writer", "writerWithoutPrivateAccess"}


def normalize_calendar_event_payload(
    value: dict[str, Any], timezone_name: str = "Europe/Warsaw"
) -> dict[str, Any]:
    title = str(value.get("title", "")).strip()
    if not title:
        raise ValueError("Podaj nazwę wydarzenia")
    if len(title) > 300:
        raise ValueError("Nazwa wydarzenia jest zbyt długa")
    description = str(value.get("description", "")).strip()
    location = str(value.get("location", "")).strip()
    if len(description) > 8000 or len(location) > 500:
        raise ValueError("Opis lub lokalizacja są zbyt długie")

    start_date = _parse_date(value.get("start_date"), "datę rozpoczęcia")
    end_date = _parse_date(value.get("end_date") or value.get("start_date"), "datę zakończenia")
    all_day = bool(value.get("all_day"))
    if all_day:
        if end_date < start_date:
            raise ValueError("Koniec wydarzenia nie może być przed początkiem")
        start: dict[str, str] = {"date": start_date.isoformat()}
        end: dict[str, str] = {"date": (end_date + dt.timedelta(days=1)).isoformat()}
    else:
        start_time = _parse_time(value.get("start_time"), "godzinę rozpoczęcia")
        end_time = _parse_time(value.get("end_time"), "godzinę zakończenia")
        starts_at = dt.datetime.combine(start_date, start_time)
        ends_at = dt.datetime.combine(end_date, end_time)
        if ends_at <= starts_at:
            raise ValueError("Koniec wydarzenia musi być później niż początek")
        start = {"dateTime": starts_at.isoformat(timespec="seconds"), "timeZone": timezone_name}
        end = {"dateTime": ends_at.isoformat(timespec="seconds"), "timeZone": timezone_name}

    return {
        "summary": title,
        "description": description,
        "location": location,
        "start": start,
        "end": end,
    }


def normalize_google_event(item: dict[str, Any]) -> dict[str, Any]:
    start = item.get("start") if isinstance(item.get("start"), dict) else {}
    end = item.get("end") if isinstance(item.get("end"), dict) else {}
    all_day = bool(start.get("date"))
    if all_day:
        start_date = str(start.get("date", ""))
        exclusive_end = _parse_date(end.get("date") or start_date, "datę zakończenia")
        end_date = (exclusive_end - dt.timedelta(days=1)).isoformat()
        start_value = start_date
        end_value = str(end.get("date", ""))
    else:
        start_value = str(start.get("dateTime", ""))
        end_value = str(end.get("dateTime", ""))
        start_date = start_value[:10]
        end_date = end_value[:10]
    return {
        "id": str(item.get("id", "")),
        "title": str(item.get("summary") or "Bez tytułu"),
        "description": str(item.get("description") or ""),
        "location": str(item.get("location") or ""),
        "all_day": all_day,
        "start": start_value,
        "end": end_value,
        "start_date": start_date,
        "end_date": end_date,
        "html_link": str(item.get("htmlLink") or ""),
        "recurring": bool(item.get("recurringEventId")),
        "status": str(item.get("status") or "confirmed"),
    }


def _parse_date(value: Any, label: str) -> dt.date:
    try:
        return dt.date.fromisoformat(str(value or ""))
    except ValueError as exc:
        raise ValueError(f"Podaj poprawną {label}") from exc


def _parse_time(value: Any, label: str) -> dt.time:
    candidate = str(value or "").strip()
    if len(candidate) in {3, 4} and candidate.isdigit():
        candidate = f"{candidate[:-2]}:{candidate[-2:]}"
    try:
        parsed = dt.time.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError(f"Podaj poprawną {label} w formacie 24-godzinnym HH:MM") from exc
    return parsed.replace(second=0, microsecond=0)


class GoogleCalendarClient:
    def __init__(self, config_path: str | Path):
        self.config = load_delivery_config(config_path)
        if not self.config.get("calendar_refresh_token"):
            raise ValueError("Kalendarz Google nie jest połączony")
        response = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": self.config["calendar_client_id"],
                "client_secret": self.config["calendar_client_secret"],
                "refresh_token": self.config["calendar_refresh_token"],
                "grant_type": "refresh_token",
            },
            timeout=20,
        )
        payload = _json_response(response, "Nie udało się odświeżyć dostępu do Kalendarza Google")
        self.headers = {"Authorization": f"Bearer {payload['access_token']}"}
        self.calendar_id = str(self.config.get("calendar_id", "")).strip()

    def list_calendars(self) -> list[dict[str, Any]]:
        calendars: list[dict[str, Any]] = []
        page_token = ""
        while True:
            params: dict[str, Any] = {
                "maxResults": 250,
                "showDeleted": "false",
                "showHidden": "false",
            }
            if page_token:
                params["pageToken"] = page_token
            response = requests.get(
                f"{CALENDAR_API}/users/me/calendarList",
                params=params,
                headers=self.headers,
                timeout=30,
            )
            payload = _calendar_response(response, "Nie udało się pobrać listy kalendarzy")
            for item in payload.get("items", []):
                if not isinstance(item, dict) or item.get("deleted"):
                    continue
                role = str(item.get("accessRole") or "reader")
                calendars.append({
                    "id": str(item.get("id", "")),
                    "name": str(item.get("summaryOverride") or item.get("summary") or "Kalendarz"),
                    "primary": bool(item.get("primary")),
                    "access_role": role,
                    "writable": role in WRITABLE_ROLES,
                    "background_color": str(item.get("backgroundColor") or ""),
                })
            page_token = str(payload.get("nextPageToken") or "")
            if not page_token:
                break
        return sorted(calendars, key=lambda item: (not item["primary"], item["name"].casefold()))

    def list_events(self, time_min: str, time_max: str, timezone_name: str) -> list[dict[str, Any]]:
        calendar_id = self._selected_calendar()
        events: list[dict[str, Any]] = []
        page_token = ""
        while True:
            params: dict[str, Any] = {
                "timeMin": time_min,
                "timeMax": time_max,
                "singleEvents": "true",
                "orderBy": "startTime",
                "showDeleted": "false",
                "maxResults": 2500,
                "timeZone": timezone_name,
            }
            if page_token:
                params["pageToken"] = page_token
            response = requests.get(
                f"{CALENDAR_API}/calendars/{quote(calendar_id, safe='')}/events",
                params=params,
                headers=self.headers,
                timeout=30,
            )
            payload = _calendar_response(response, "Nie udało się pobrać Grafiku")
            events.extend(
                normalize_google_event(item)
                for item in payload.get("items", [])
                if isinstance(item, dict) and item.get("status") != "cancelled"
            )
            page_token = str(payload.get("nextPageToken") or "")
            if not page_token:
                break
        return events

    def create_event(self, value: dict[str, Any], timezone_name: str) -> dict[str, Any]:
        body = normalize_calendar_event_payload(value, timezone_name)
        response = requests.post(
            f"{CALENDAR_API}/calendars/{quote(self._selected_calendar(), safe='')}/events",
            params={"sendUpdates": "none"},
            headers={**self.headers, "Content-Type": "application/json"},
            json=body,
            timeout=30,
        )
        return normalize_google_event(_calendar_response(response, "Nie udało się dodać wydarzenia"))

    def update_event(
        self, event_id: str, value: dict[str, Any], timezone_name: str
    ) -> dict[str, Any]:
        if not event_id or "/" in event_id:
            raise ValueError("Nieprawidłowy identyfikator wydarzenia")
        body = normalize_calendar_event_payload(value, timezone_name)
        response = requests.patch(
            f"{CALENDAR_API}/calendars/{quote(self._selected_calendar(), safe='')}/events/{quote(event_id, safe='')}",
            params={"sendUpdates": "none"},
            headers={**self.headers, "Content-Type": "application/json"},
            json=body,
            timeout=30,
        )
        return normalize_google_event(_calendar_response(response, "Nie udało się zmienić wydarzenia"))

    def delete_event(self, event_id: str) -> None:
        if not event_id or "/" in event_id:
            raise ValueError("Nieprawidłowy identyfikator wydarzenia")
        response = requests.delete(
            f"{CALENDAR_API}/calendars/{quote(self._selected_calendar(), safe='')}/events/{quote(event_id, safe='')}",
            params={"sendUpdates": "none"},
            headers=self.headers,
            timeout=30,
        )
        if response.status_code not in {204, 404}:
            _calendar_response(response, "Nie udało się usunąć wydarzenia")

    def _selected_calendar(self) -> str:
        if not self.calendar_id:
            raise ValueError("Wybierz kalendarz Grafiku w Ustawieniach")
        return self.calendar_id


def _calendar_response(response: Any, prefix: str) -> dict[str, Any]:
    try:
        return _json_response(response, prefix)
    except RuntimeError as exc:
        detail = str(exc)
        if response.status_code == 403 and (
            "insufficient" in detail.casefold() or "scope" in detail.casefold()
        ):
            raise RuntimeError(
                "Kalendarz Google nie ma wymaganych uprawnień. Połącz konto ponownie w Ustawieniach."
            ) from exc
        raise
