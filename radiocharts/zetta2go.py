from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time, timedelta, timezone
from typing import Any
from urllib.parse import urljoin

import requests

from radiocharts.config import load_config
import radiocharts.db as rcdb

DEFAULT_BASE_URL = "https://emaus-zetta-srv.swdm.local/Zetta2GO"
DEFAULT_STATION_ID = "3658ac9a-335e-4839-ac18-2159ba1e4a16"

SETTING_KEYS = {
    "url": "zetta2go.url",
    "station_id": "zetta2go.station_id",
    "username": "zetta2go.username",
    "password": "zetta2go.password",
    "verify_tls": "zetta2go.verify_tls",
    "timeout": "zetta2go.timeout",
    "schedule_horizon_days": "zetta2go.schedule_horizon_days",
    "live_enabled": "zetta2go.live_enabled",
    "schedule_enabled": "zetta2go.schedule_enabled",
}

# Values exposed by Zetta2GO's own eventStatusCodes enum.
STATUS_NAMES: dict[int, str] = {
    -3: "PENDING_PLAYED",
    0: "INVALID",
    1: "READY",
    2: "CURRENT",
    3: "PLAYED",
    4: "NOT_PLAYED",
    5: "EVENT_ERROR",
    6: "PLAYED_FADE_N_GO",
    7: "PLAYED_FADE",
    8: "PLAYED_STOPPED",
    9: "PAUSED",
    10: "WAITING_CURRENT",
}

# Edit codes exposed by Zetta2GO's own editCodes enum. Keep the full mapping
# locally so imported snapshots remain readable even when the web UI is offline.
EDIT_CODE_NAMES: dict[int, str] = {
    0: "Invalid",
    100: "Scheduler - Import",
    101: "Scheduler - Move",
    102: "Scheduler - Skipped",
    103: "Scheduler - Insert",
    200: "User - Insert",
    201: "User - Move",
    202: "User - Skipped",
    203: "User - Ejected",
    204: "User - Copy",
    205: "User - Synch to Selection Past",
    206: "User - Synch to Selection Future",
    207: "External App Modify",
    208: "External App Insert",
    209: "User Resolved",
    210: "User - Replace Same Category",
    211: "User - Replace Different Category",
    212: "User - Replace Different Event Type",
    213: "User - Juggle",
    214: "User - Move Manual Start",
    215: "User - Manual Start No Chain Control",
    216: "User - Replace",
    217: "User - Faded Early",
    220: "Mini-Log - Insert By User",
    221: "Mini-Log - Skipped",
    222: "Mini-Log - Deleted",
    223: "Mini-Log - Insert By Clock",
    240: "Hot Keys - Inject",
    241: "Stacks - Inject",
    242: "Z-Player - Inject",
    300: "Sequencer - Insert - Fill",
    301: "Sequencer - Move",
    302: "Sequencer - Event dropped due to (execution of) future ETM",
    303: "Sequencer - Expired",
    304: "Sequencer - Insert - GPIO",
    305: "Sequencer - Live Event - Invalid Mode",
    306: "Sequencer - Insert - Master Fill",
    401: "Flat File Load - Insert",
    402: "Flat File Merge",
    501: "Splits - Insert",
    502: "Splits - Cued By Asset",
    503: "Splits - Cued By Tags",
    504: "Splits - Cued By Position",
    505: "Splits - Cued By ThirdParty",
    506: "Splits - Skipped",
    507: "Splits - Played on Client",
    508: "Splits - Cued By ETM",
}

PLAYED_STATUS_CODES = {-3, 2, 3, 6, 7, 8, 9}
NONPLAYED_STATUS_CODES = {4, 5}
UPCOMING_STATUS_CODES = {1, 10}
KNOWN_STATUS_CODES = set(STATUS_NAMES)


@dataclass(frozen=True)
class Zetta2GoSettings:
    base_url: str
    station_id: str
    username: str
    password: str
    verify_tls: bool | str
    timeout: float = 15.0
    schedule_horizon_days: int = 14
    live_enabled: bool = True
    schedule_enabled: bool = True

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.station_id and self.username and self.password)


def _bool_env(value: str | None, default: bool = True) -> bool:
    if value is None or str(value).strip() == "":
        return default
    return str(value).strip().casefold() not in {"0", "false", "no", "off"}


def _persistent_settings() -> dict[str, str]:
    try:
        raw = rcdb.get_app_settings(set(SETTING_KEYS.values()))
    except Exception:
        return {}
    return {name: raw[key] for name, key in SETTING_KEYS.items() if key in raw}


def save_settings(
    *,
    username: str,
    password: str,
    base_url: str = DEFAULT_BASE_URL,
    station_id: str = DEFAULT_STATION_ID,
    verify_tls: bool = True,
    schedule_horizon_days: int = 14,
    live_enabled: bool = True,
    schedule_enabled: bool = True,
) -> None:
    """Persist Zetta2GO settings entered in the RadioCharts Settings page.

    They live in the shared SQLite DB, so the web and worker containers read the
    same values.  UI values intentionally take precedence over legacy env/YAML
    settings once the user has saved them.
    """
    rcdb.set_app_settings({
        SETTING_KEYS["url"]: str(base_url).strip().rstrip("/"),
        SETTING_KEYS["station_id"]: str(station_id).strip(),
        SETTING_KEYS["username"]: str(username).strip(),
        SETTING_KEYS["password"]: str(password),
        SETTING_KEYS["verify_tls"]: "true" if verify_tls else "false",
        SETTING_KEYS["schedule_horizon_days"]: str(min(31, max(1, int(schedule_horizon_days)))),
        SETTING_KEYS["live_enabled"]: "true" if live_enabled else "false",
        SETTING_KEYS["schedule_enabled"]: "true" if schedule_enabled else "false",
    })


def settings() -> Zetta2GoSettings:
    try:
        cfg = load_config()
    except Exception:
        cfg = {}
    local_cfg = (cfg.get("emaus") or {}).get("zetta2go") or {}
    saved = _persistent_settings()

    def pick(name: str, env_name: str, yaml_name: str, default: object = "") -> object:
        if name in saved:
            return saved[name]
        env_value = os.getenv(env_name)
        if env_value is not None and str(env_value).strip() != "":
            return env_value
        if yaml_name in local_cfg:
            return local_cfg.get(yaml_name)
        return default

    base_url = str(pick("url", "ZETTA2GO_URL", "url", DEFAULT_BASE_URL) or DEFAULT_BASE_URL).rstrip("/")
    station_id = str(pick("station_id", "ZETTA2GO_STATION_ID", "station_id", DEFAULT_STATION_ID) or DEFAULT_STATION_ID).strip()
    username = str(pick("username", "ZETTA2GO_USERNAME", "username", "") or "").strip()
    password = str(pick("password", "ZETTA2GO_PASSWORD", "password", "") or "")

    # CA bundle remains an advanced deployment-only override.  The normal UI
    # exposes just certificate verification on/off.
    ca_bundle = str(os.getenv("ZETTA2GO_CA_BUNDLE") or local_cfg.get("ca_bundle") or "").strip()
    if ca_bundle:
        verify_tls: bool | str = ca_bundle
    else:
        verify_raw = pick("verify_tls", "ZETTA2GO_VERIFY_TLS", "verify_tls", True)
        verify_tls = _bool_env(str(verify_raw) if verify_raw is not None else None, True)

    timeout_raw = pick("timeout", "ZETTA2GO_TIMEOUT", "timeout", 15)
    try:
        timeout = max(3.0, float(timeout_raw))
    except (TypeError, ValueError):
        timeout = 15.0

    horizon_raw = pick("schedule_horizon_days", "ZETTA2GO_SCHEDULE_HORIZON_DAYS", "schedule_horizon_days", 14)
    try:
        schedule_horizon_days = min(31, max(1, int(horizon_raw)))
    except (TypeError, ValueError):
        schedule_horizon_days = 14
    live_raw = pick("live_enabled", "ZETTA2GO_LIVE_ENABLED", "live_enabled", True)
    schedule_raw = pick("schedule_enabled", "ZETTA2GO_SCHEDULE_ENABLED", "schedule_enabled", True)
    live_enabled = _bool_env(str(live_raw) if live_raw is not None else None, True)
    schedule_enabled = _bool_env(str(schedule_raw) if schedule_raw is not None else None, True)
    return Zetta2GoSettings(
        base_url, station_id, username, password, verify_tls, timeout,
        schedule_horizon_days, live_enabled, schedule_enabled,
    )


class Zetta2GoClient:
    def __init__(self, cfg: Zetta2GoSettings | None = None):
        self.cfg = cfg or settings()
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "RadioCharts/Zetta2GO",
            "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.7",
        })
        self._logged_in = False

    def _url(self, path: str) -> str:
        return urljoin(self.cfg.base_url.rstrip("/") + "/", path.lstrip("/"))

    def login(self) -> dict[str, Any]:
        if not self.cfg.configured:
            raise RuntimeError("Zetta2GO nie jest skonfigurowane (brak loginu/hasła lub station ID).")
        login_url = self._url("Zetta/Go")
        # First GET establishes ASP.NET_SessionId. Zetta2GO then accepts the
        # classic form POST with userName/password.
        first = self.session.get(login_url, timeout=self.cfg.timeout, verify=self.cfg.verify_tls)
        first.raise_for_status()
        response = self.session.post(
            login_url,
            data={
                "userName": self.cfg.username,
                "pwText": "",
                "password": self.cfg.password,
                "isSmallFormFactor": "0",
            },
            headers={"Referer": login_url},
            timeout=self.cfg.timeout,
            verify=self.cfg.verify_tls,
        )
        response.raise_for_status()
        cookie_names = set(self.session.cookies.keys())
        if "Zetta2Go" not in cookie_names:
            # A failed login returns the form again with HTTP 200, so status code
            # alone is not a useful success signal.
            raise RuntimeError("Logowanie Zetta2GO nie powiodło się (brak cookie Zetta2Go).")
        self._logged_in = True
        return {
            "ok": True,
            "status_code": response.status_code,
            "cookies": sorted(cookie_names),
        }

    def get_log_range(self, start: datetime, end: datetime) -> dict[str, Any]:
        if not self._logged_in:
            self.login()
        if end < start:
            raise ValueError("end must be >= start")
        endpoint = self._url("Logs/GetLog")
        payload = {
            "stationID": self.cfg.station_id,
            "fromDateTime": start.replace(tzinfo=None).isoformat(timespec="milliseconds"),
            "toDateTime": end.replace(tzinfo=None).isoformat(timespec="milliseconds"),
            "_search": "false",
            "nd": str(int(time.time() * 1000)),
            "rows": "10000",
            "page": "1",
            "sidx": "",
            "sord": "asc",
        }
        response = self.session.post(
            endpoint,
            data=payload,
            headers={
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": self._url("Zetta/Go"),
            },
            timeout=self.cfg.timeout,
            verify=self.cfg.verify_tls,
        )
        response.raise_for_status()
        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError("Zetta2GO GetLog nie zwrócił JSON-a; sesja mogła wygasnąć.") from exc
        if not isinstance(data, dict) or "rows" not in data:
            raise RuntimeError("Nieoczekiwany format odpowiedzi Zetta2GO GetLog.")
        return data

    def get_log(self, service_date: date | str) -> dict[str, Any]:
        """Fetch one complete broadcast day from Zetta2GO.

        Zetta2GO needs preceding log context to calculate the inline value on an
        ETM that sits exactly on an hour boundary.  Asking for that context is
        safe only if the lead-in rows are *not* merged into the target hour: the
        log can legitimately contain 60+ minute rows that still belong to the
        previous scheduling hour.  Merging the whole two-hour response made
        those rows leak into the next hour and destroyed Scheduled/Played
        reconciliation.

        Therefore every target hour is still fetched with one hour of lead-in,
        but from that response RadioCharts keeps only the rows in the target
        TOH (Top-of-Hour) group.  The preceding group exists solely so Zetta can
        calculate native ETM fields.  No local gap/carry reconstruction is done.
        """
        d = service_date if isinstance(service_date, date) else date.fromisoformat(str(service_date))
        merged_rows: list[dict[str, Any]] = []
        last_payload: dict[str, Any] = {}
        dropped_context_rows = 0
        target_groups_found = 0

        def row_entry_type(row: dict[str, Any]) -> int:
            cell = row.get("cell")
            if not isinstance(cell, list) or not cell:
                return 0
            try:
                return int(cell[0] or 0)
            except (TypeError, ValueError):
                return 0

        def row_air_datetime(row: dict[str, Any]) -> datetime | None:
            cell = row.get("cell")
            if not isinstance(cell, list) or len(cell) <= 5:
                return None
            raw = str(cell[5] or "").strip()
            if not raw:
                return None
            try:
                return datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                return None

        def target_group_rows(rows: list[dict[str, Any]], hour: int) -> list[dict[str, Any]]:
            """Keep only the requested scheduling-hour group from a lead-in response.

            A TOH row (entry type 3) changes the current logical scheduling hour.
            This is deliberately different from filtering by wall-clock AirTime:
            rows such as 10:60:38 can still belong to the 10 scheduling hour.
            """
            selected: list[dict[str, Any]] = []
            current_group_hour: int | None = None
            current_group_date: date | None = None
            saw_target_toh = False
            for row in rows:
                if not isinstance(row, dict):
                    continue
                dt = row_air_datetime(row)
                if row_entry_type(row) == 3 and dt is not None:
                    current_group_hour = dt.hour
                    current_group_date = dt.date()
                    if current_group_date == d and current_group_hour == hour:
                        saw_target_toh = True
                if current_group_date == d and current_group_hour == hour:
                    # A boundary ETM can leak into the previous scheduling
                    # group without a following TOH row in the truncated
                    # response. Unlike ordinary 60+ audio rows, an ETM belongs
                    # to its own wall-clock hour, so never claim a next-hour ETM
                    # for the previous target group.
                    if row_entry_type(row) == 15 and dt is not None and dt.hour != hour:
                        continue
                    selected.append(row)
            if selected:
                return selected

            # Defensive fallback for installations/responses that omit TOH helper
            # rows.  Use wall-clock hour only when we cannot identify a TOH group.
            # This fallback must never run when a target TOH was actually seen.
            if not saw_target_toh:
                return [
                    row for row in rows
                    if isinstance(row, dict)
                    and (dt := row_air_datetime(row)) is not None
                    and dt.date() == d and dt.hour == hour
                ]
            return []

        # Preserve the predecessor metadata used by diagnostics/backward
        # compatibility. It is never merged into the requested day.
        prev_day = d - timedelta(days=1)
        prev_start = datetime.combine(prev_day, dt_time(23, 0, 0))
        prev_end = datetime.combine(prev_day, dt_time(23, 59, 59, 900000))
        prev_payload = self.get_log_range(prev_start, prev_end)
        previous_hour_rows = prev_payload.get("rows") if isinstance(prev_payload, dict) else []
        if not isinstance(previous_hour_rows, list):
            previous_hour_rows = []

        seen_ids: set[str] = set()
        for hour in range(24):
            target_start = datetime.combine(d, dt_time(hour, 0, 0))
            start = target_start - timedelta(hours=1)
            end = datetime.combine(d, dt_time(hour, 59, 59, 900000))
            payload = self.get_log_range(start, end)
            last_payload = payload
            rows = payload.get("rows") if isinstance(payload, dict) else None
            if not isinstance(rows, list):
                continue
            selected = target_group_rows(rows, hour)
            dropped_context_rows += max(0, len(rows) - len(selected))
            if any(row_entry_type(row) == 3 for row in selected):
                target_groups_found += 1
            for row in selected:
                row_id = str(row.get("id") or "").strip()
                if row_id and row_id in seen_ids:
                    continue
                if row_id:
                    seen_ids.add(row_id)
                merged_rows.append(row)

        return {
            "total": 1,
            "page": 1,
            "records": len(merged_rows),
            "rows": merged_rows,
            "userdata": last_payload.get("userdata") if isinstance(last_payload, dict) else None,
            "radiocharts_hourly_fetch": True,
            "radiocharts_target_toh_groups": target_groups_found,
            "radiocharts_context_rows_dropped": dropped_context_rows,
            # Kept for compatibility with existing diagnostics/tests. Boundary
            # duplicates are no longer merged at all; context groups are dropped.
            "radiocharts_boundary_etm_duplicates_resolved": 0,
            "radiocharts_previous_hour_rows": previous_hour_rows,
        }

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> "Zetta2GoClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
