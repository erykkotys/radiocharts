from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import requests


ZETTA_CONFIG_KEY = "zetta2go_config"
DEFAULT_ZETTA_URL = "https://emaus-zetta-srv.swdm.local/Zetta2GO/Zetta/Go"
DEFAULT_STATION_ID = "3658ac9a-335e-4839-ac18-2159ba1e4a16"
STATUS_LABELS = {
    -3: "oczekuje na rozliczenie",
    0: "nieprawidłowy",
    1: "jeszcze nie zagrano",
    2: "teraz",
    3: "zagrano",
    4: "nie zagrano",
    5: "błąd emisji",
    6: "zagrano · fade and go",
    7: "zagrano · fade",
    8: "zatrzymano",
    9: "pauza",
    10: "oczekuje",
}
EDIT_CODE_LABELS = {
    202: "Pominięto ręcznie",
    203: "Usunięto ręcznie z emisji",
    217: "Ręcznie zakończono wcześniej",
    302: "Usunięto przez przyszły ETM",
    303: "Element wygasł w sekwencerze",
}


def _json_object(value: str | None) -> dict[str, Any]:
    try:
        decoded = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def get_zetta_config(database: Any, *, include_password: bool = False) -> dict[str, Any]:
    stored = _json_object(database.get_setting(ZETTA_CONFIG_KEY, "{}"))
    result = {
        "url": str(stored.get("url") or DEFAULT_ZETTA_URL),
        "station_id": str(stored.get("station_id") or DEFAULT_STATION_ID),
        "username": str(stored.get("username") or ""),
        "password_set": bool(stored.get("password")),
    }
    result["configured"] = bool(
        result["url"] and result["station_id"] and result["username"] and result["password_set"]
    )
    if include_password:
        result["password"] = str(stored.get("password") or "")
    return result


def save_zetta_config(database: Any, payload: dict[str, Any]) -> dict[str, Any]:
    current = get_zetta_config(database, include_password=True)
    url = str(payload.get("url", current["url"]) or "").strip().rstrip("/")
    station_id = str(payload.get("station_id", current["station_id"]) or "").strip()
    username = str(payload.get("username", current["username"]) or "").strip()
    supplied_password = str(payload.get("password") or "")
    password = supplied_password if supplied_password else current.get("password", "")
    if not url.startswith(("http://", "https://")):
        raise ValueError("Adres Zetta2GO musi zaczynać się od http:// albo https://")
    if not station_id:
        raise ValueError("Podaj Station ID")
    database.set_setting(
        ZETTA_CONFIG_KEY,
        json.dumps(
            {"url": url, "station_id": station_id, "username": username, "password": password},
            ensure_ascii=False,
        ),
    )
    return get_zetta_config(database)


def _int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, dict):
        for key in ("Value", "value", "Milliseconds", "milliseconds", "Code", "code"):
            if key in value:
                return _int(value[key])
        return None
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def _object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip().startswith(("{", "[")):
        try:
            decoded = json.loads(value)
            return decoded if isinstance(decoded, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        for key in ("Text", "text", "Name", "name", "Value", "value"):
            if key in value:
                return _text(value[key])
        return ""
    return str(value).strip()


def _first(asset: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = _text(asset.get(key))
        if value:
            return value
    return ""


def _classify(entry_type: Any, asset: dict[str, Any], title: str, artist: str) -> str:
    etm_type = _first(asset, "ETMType", "etmType")
    combined = " ".join(
        _text(value)
        for value in (
            entry_type,
            title,
            artist,
            asset.get("AssetTypeID"),
            asset.get("AssetType"),
            asset.get("LogEventTypeID"),
            asset.get("Sponsor"),
            asset.get("Category"),
        )
    ).casefold()
    if etm_type or "etm" in combined:
        return "etm"
    if any(token in combined for token in ("top of hour", "top_of_hour", "topofhour", "toh")):
        return "toh"
    if any(token in combined for token in ("rekl", "spot", "commercial", "autoprom", "po_reklamie", "po reklamie")):
        return "ads"
    if any(token in combined for token in ("jingle", "dżing", "link", "liner", "sweeper", "opraw")):
        return "jingle"
    if any(token in combined for token in ("audyc", "program", "magazyn", "serwis", "wiadomo")):
        return "shows"
    if artist:
        return "music"
    return "other"


def _air_time(value: Any, day: dt.date, timezone: ZoneInfo) -> tuple[str, float | None]:
    raw = _text(value)
    if not raw:
        return "", None
    dotnet = re.search(r"/Date\(([-+]?\d+)", raw)
    if dotnet:
        moment = dt.datetime.fromtimestamp(int(dotnet.group(1)) / 1000, tz=dt.timezone.utc).astimezone(timezone)
        return moment.isoformat(), moment.timestamp()
    compact = re.fullmatch(r"(\d{1,2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?", raw)
    if compact:
        hour, minute = int(compact.group(1)), int(compact.group(2))
        second = int(compact.group(3) or 0)
        moment = dt.datetime.combine(day, dt.time(hour, minute, second), timezone)
        return moment.isoformat(), moment.timestamp()
    try:
        normalized = raw.replace("Z", "+00:00")
        moment = dt.datetime.fromisoformat(normalized)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone)
        moment = moment.astimezone(timezone)
        return moment.isoformat(), moment.timestamp()
    except ValueError:
        return raw, None


def _row_identifier(raw: dict[str, Any], cells: list[Any], hour: int, index: int) -> str:
    for value in (raw.get("id"), raw.get("ID"), raw.get("RowID")):
        if _text(value):
            return _text(value)
    asset = _object(cells[7] if len(cells) > 7 else None)
    parts = [
        _text(asset.get("UniversalIdentifier")),
        _text(asset.get("AssetID")),
        _text(cells[5] if len(cells) > 5 else ""),
        _text(cells[1] if len(cells) > 1 else ""),
        str(hour),
        str(index),
    ]
    return "|".join(parts)


def normalize_log_row(
    raw: dict[str, Any], day: dt.date, hour: int, index: int, timezone: ZoneInfo
) -> dict[str, Any]:
    cells = raw.get("cell") if isinstance(raw.get("cell"), list) else []
    cells = list(cells) + [None] * max(0, 20 - len(cells))
    asset = _object(cells[7])
    title = _first(asset, "Title", "title", "Name", "name") or _text(cells[7])
    artist = _first(asset, "Artist", "artist")
    air_time, start_timestamp = _air_time(cells[5], day, timezone)
    runtime_ms = _int(cells[15]) or _int(asset.get("Runtime")) or _int(asset.get("DurationRuntime"))
    duration_ms = _int(cells[18]) or _int(asset.get("DurationMilliseconds"))
    category = _classify(cells[0], asset, title, artist)
    return {
        "row_id": _row_identifier(raw, cells, hour, index),
        "sequence": _int(cells[1]),
        "log_event_entry_type": _text(cells[0]),
        "edit_code": _int(cells[2]),
        "valid_for_playback": cells[3],
        "air_time": air_time,
        "start_timestamp": start_timestamp,
        "status_code": _int(cells[9]),
        "runtime_ms": runtime_ms,
        "duration_ms": duration_ms,
        "asset_id": _text(asset.get("AssetID")),
        "universal_identifier": _text(asset.get("UniversalIdentifier")),
        "log_group_universal_identifier": _text(cells[17]),
        "title": title or ("TOP OF THE HOUR" if category == "toh" else "Element bez nazwy"),
        "artist": artist,
        "category": category,
        "asset": asset,
        "raw": raw,
    }


@dataclass
class ZettaClient:
    config: dict[str, Any]

    def __post_init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "EmausHub/1.0", "Accept": "application/json, text/javascript, */*; q=0.01"})
        ca_cert_file = os.environ.get("ZETTA_CA_CERT_FILE", "").strip()
        if ca_cert_file:
            ca_path = Path(ca_cert_file)
            if not ca_path.is_file():
                raise RuntimeError(
                    f"Nie znaleziono pliku CA Zetty: {ca_cert_file}. "
                    "Sprawdź ZETTA_CA_CERT_FILE i mount /data."
                )
            if not os.access(ca_path, os.R_OK):
                raise RuntimeError(f"Brak prawa odczytu pliku CA Zetty: {ca_cert_file}")
            self.session.verify = str(ca_path)
        parts = urlsplit(self.config["url"])
        prefix = parts.path.split("/Zetta2GO/", 1)[0]
        self.log_url = urlunsplit((parts.scheme, parts.netloc, f"{prefix}/Zetta2GO/Logs/GetLog", "", ""))
        self.logged_in = False

    def login(self) -> None:
        login_url = self.config["url"]
        response = self.session.get(login_url, timeout=(10, 30))
        response.raise_for_status()
        response = self.session.post(
            login_url,
            data={
                "userName": self.config["username"],
                "pwText": "",
                "password": self.config["password"],
                "isSmallFormFactor": "0",
            },
            timeout=(10, 30),
        )
        response.raise_for_status()
        self.logged_in = True

    def fetch_hour(self, day: dt.date, hour: int) -> list[dict[str, Any]]:
        for attempt in range(2):
            if not self.logged_in:
                self.login()
            response = self.session.post(
                self.log_url,
                data={
                    "stationID": self.config["station_id"],
                    "fromDateTime": f"{day.isoformat()}T{hour:02d}:00:00",
                    "toDateTime": f"{day.isoformat()}T{hour:02d}:59:59.9",
                    "_search": "false",
                    "nd": str(int(time.time() * 1000)),
                    "rows": "10000",
                    "page": "1",
                    "sidx": "",
                    "sord": "asc",
                },
                headers={"X-Requested-With": "XMLHttpRequest"},
                timeout=(10, 45),
            )
            if response.status_code in (401, 403) or "text/html" in response.headers.get("content-type", "").lower():
                self.logged_in = False
                if attempt == 0:
                    continue
                raise RuntimeError("Sesja Zetta2GO wygasła albo logowanie zostało odrzucone")
            response.raise_for_status()
            try:
                payload = response.json()
            except ValueError as exc:
                self.logged_in = False
                if attempt == 0:
                    continue
                raise RuntimeError("Zetta2GO zwróciła odpowiedź inną niż JSON") from exc
            rows = payload.get("rows", []) if isinstance(payload, dict) else []
            if not isinstance(rows, list):
                raise RuntimeError("Zetta2GO zwróciła nieprawidłowy format logu")
            return [row for row in rows if isinstance(row, dict)]
        return []


class PlayedService:
    def __init__(self, database: Any, timezone_name: str):
        self.database = database
        self.timezone = ZoneInfo(timezone_name)
        self.lock = threading.Lock()

    def configured(self) -> bool:
        return bool(get_zetta_config(self.database)["configured"])

    def refresh_hours(self, day: dt.date, hours: list[int]) -> dict[str, Any]:
        config = get_zetta_config(self.database, include_password=True)
        if not config["configured"]:
            raise ValueError("Najpierw skonfiguruj Zetta2GO w Ustawieniach")
        hours = sorted({hour for hour in hours if 0 <= hour <= 23})
        if not hours:
            return {"hours": [], "rows": 0}
        if not self.lock.acquire(blocking=False):
            return {"hours": [], "rows": 0, "already_running": True}
        try:
            client = ZettaClient(config)
            total = 0
            completed: list[int] = []
            errors: list[str] = []
            for hour in hours:
                try:
                    raw_rows = client.fetch_hour(day, hour)
                    rows = [
                        normalize_log_row(raw, day, hour, index, self.timezone)
                        for index, raw in enumerate(raw_rows)
                    ]
                    self._store_hour(config["station_id"], day, hour, rows)
                    self._store_sync(config["station_id"], day, hour, "ok", "", len(rows))
                    total += len(rows)
                    completed.append(hour)
                except Exception as exc:
                    self._store_sync(config["station_id"], day, hour, "error", str(exc), 0)
                    errors.append(f"{hour:02d}:00 — {exc}")
            if errors and not completed:
                raise RuntimeError(errors[0])
            return {"hours": completed, "rows": total, "errors": errors}
        finally:
            self.lock.release()

    def refresh_day(self, day: dt.date) -> dict[str, Any]:
        return self.refresh_hours(day, list(range(24)))

    def test_connection(self) -> dict[str, Any]:
        now = dt.datetime.now(self.timezone)
        result = self.refresh_hours(now.date(), [now.hour])
        return {"ok": True, "row_count": result.get("rows", 0), "hour": now.hour}

    def _store_hour(
        self, station_id: str, day: dt.date, hour: int, rows: list[dict[str, Any]]
    ) -> None:
        with self.database._write_lock, self.database.connect() as connection:
            connection.execute(
                "DELETE FROM zetta_played_rows WHERE station_id=? AND emission_date=? AND hour_slot=?",
                (station_id, day.isoformat(), hour),
            )
            for row in rows:
                connection.execute(
                    """
                    INSERT OR REPLACE INTO zetta_played_rows(
                        station_id, emission_date, hour_slot, row_id, sequence, air_time,
                        status_code, edit_code, runtime_ms, duration_ms, asset_id,
                        universal_identifier, log_group_universal_identifier, title, artist,
                        category, asset_json, raw_json, updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
                    """,
                    (
                        station_id,
                        day.isoformat(),
                        hour,
                        row["row_id"],
                        row["sequence"],
                        row["air_time"],
                        row["status_code"],
                        row["edit_code"],
                        row["runtime_ms"],
                        row["duration_ms"],
                        row["asset_id"],
                        row["universal_identifier"],
                        row["log_group_universal_identifier"],
                        row["title"],
                        row["artist"],
                        row["category"],
                        json.dumps(row["asset"], ensure_ascii=False),
                        json.dumps(row["raw"], ensure_ascii=False),
                    ),
                )
            connection.commit()

    def _store_sync(
        self, station_id: str, day: dt.date, hour: int, status: str, detail: str, count: int
    ) -> None:
        with self.database._write_lock, self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO zetta_sync_log(station_id, emission_date, hour_slot, status, detail, row_count, updated_at)
                VALUES(?,?,?,?,?,?,CURRENT_TIMESTAMP)
                ON CONFLICT(station_id, emission_date, hour_slot) DO UPDATE SET
                    status=excluded.status, detail=excluded.detail, row_count=excluded.row_count,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (station_id, day.isoformat(), hour, status, detail[:2000], count),
            )
            connection.commit()

    def day(self, day: dt.date) -> dict[str, Any]:
        config = get_zetta_config(self.database)
        if not config["configured"]:
            return {"configured": False, "items": [], "last_sync": None, "sync_error": ""}
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM zetta_played_rows
                WHERE station_id=? AND emission_date=?
                ORDER BY hour_slot, COALESCE(sequence, 2147483647), air_time, row_id
                """,
                (config["station_id"], day.isoformat()),
            ).fetchall()
            sync_rows = connection.execute(
                """
                SELECT * FROM zetta_sync_log
                WHERE station_id=? AND emission_date=? ORDER BY updated_at DESC
                """,
                (config["station_id"], day.isoformat()),
            ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            air_time, start_timestamp = _air_time(row["air_time"], day, self.timezone)
            asset = _json_object(row["asset_json"])
            status = row["status_code"]
            edit_code = row["edit_code"]
            items.append(
                {
                    "row_id": row["row_id"],
                    "hour": row["hour_slot"],
                    "sequence": row["sequence"],
                    "air_time": air_time,
                    "start_timestamp": start_timestamp,
                    "status_code": status,
                    "status": STATUS_LABELS.get(status, f"status {status}" if status is not None else "—"),
                    "edit_code": edit_code,
                    "edit_reason": EDIT_CODE_LABELS.get(edit_code, ""),
                    "runtime_ms": row["runtime_ms"],
                    "duration_ms": row["duration_ms"],
                    "asset_id": row["asset_id"],
                    "universal_identifier": row["universal_identifier"],
                    "log_group_universal_identifier": row["log_group_universal_identifier"],
                    "title": row["title"],
                    "artist": row["artist"],
                    "category": row["category"],
                    "etm_type": _first(asset, "ETMType", "etmType"),
                    "asset": asset,
                }
            )
        last_sync = (
            f"{str(sync_rows[0]['updated_at']).replace(' ', 'T')}Z" if sync_rows else None
        )
        errors = [row for row in sync_rows if row["status"] == "error"]
        return {
            "configured": True,
            "items": group_advertisements(items),
            "last_sync": last_sync,
            "sync_error": errors[0]["detail"] if errors else "",
        }


def group_advertisements(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: list[dict[str, Any]] = []
    index = 0
    while index < len(items):
        item = items[index]
        if item["category"] != "ads":
            grouped.append(item)
            index += 1
            continue
        children = [item]
        group_id = item.get("log_group_universal_identifier")
        cursor = index + 1
        while cursor < len(items):
            candidate = items[cursor]
            same_group = bool(group_id) and candidate.get("log_group_universal_identifier") == group_id
            if candidate["category"] != "ads" or (group_id and not same_group):
                break
            children.append(candidate)
            cursor += 1
        if len(children) == 1:
            grouped.append(item)
        else:
            runtime = sum(int(child.get("runtime_ms") or child.get("duration_ms") or 0) for child in children)
            parent = dict(children[0])
            parent.update(
                {
                    "row_id": f"ads:{children[0]['row_id']}",
                    "title": "REKLAMA / AUTOPROMOCJA",
                    "artist": "",
                    "runtime_ms": runtime or None,
                    "children": children,
                }
            )
            grouped.append(parent)
        index = cursor
    return grouped


async def played_sync_loop(service: PlayedService) -> None:
    last_full_day: dt.date | None = None
    last_full_at = 0.0
    while True:
        try:
            if service.configured():
                now = dt.datetime.now(service.timezone)
                if last_full_day != now.date() or time.monotonic() - last_full_at >= 30 * 60:
                    await asyncio.to_thread(service.refresh_day, now.date())
                    last_full_day = now.date()
                    last_full_at = time.monotonic()
                # Refresh the live window even after a full-day pass.  Grouping
                # by date also handles 23:xx/00:xx correctly, so the final
                # status of the previous day's last hour is not lost.
                live_hours: dict[dt.date, list[int]] = {}
                for moment in (
                    now - dt.timedelta(hours=1),
                    now,
                    now + dt.timedelta(hours=1),
                ):
                    live_hours.setdefault(moment.date(), []).append(moment.hour)
                for day, hours in live_hours.items():
                    await asyncio.to_thread(
                        service.refresh_hours,
                        day,
                        hours,
                    )
        except Exception:
            # Szczegóły błędu są utrwalane per godzina w zetta_sync_log.
            pass
        await asyncio.sleep(60)
