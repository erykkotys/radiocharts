from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from filelock import FileLock

from radiocharts import db
from radiocharts.zetta2go import (
    EDIT_CODE_NAMES as ZETTA_EDIT_CODE_NAMES,
    NONPLAYED_STATUS_CODES as ZETTA_NONPLAYED_STATUS_CODES,
    PLAYED_STATUS_CODES as ZETTA_PLAYED_STATUS_CODES,
    UPCOMING_STATUS_CODES as ZETTA_UPCOMING_STATUS_CODES,
    STATUS_NAMES as ZETTA_STATUS_NAMES,
    Zetta2GoClient,
    settings as zetta2go_settings,
)

STATION_KEY = "EMAUS"
LOCAL_KINDS = ("schedule", "played")
EVENT_TYPES = ("song", "jingle", "show", "bed", "info", "etm", "toh", "traffic", "command", "other")

# Current EMAUS/GSelector Song sub-format.  The first 17 positions are stable
# in the export used by RadioCharts; four trailing technical fields are kept
# verbatim because their exact GSelector labels can vary with the sub-format.
GSELECTOR_SONG_COLUMNS: tuple[tuple[str, str, int], ...] = (
    ("mood", "Mood", 2),
    ("opener", "Opener", 3),
    ("timing", "Timing", 6),
    ("content", "Content", 7),
    ("energy", "Energy", 8),
    ("texture_close", "Texture Close", 9),
    ("texture_open", "Texture Open", 10),
    ("edit_code", "Edit Code", 11),
    ("exact_time_raw", "Exact Time", 12),
    ("sound_code", "Sound Code", 13),
    ("runtime_raw", "Runtime", 14),
    ("vocal", "Vocal", 15),
    ("external_id", "ID", 16),
    ("extra_18", "Pole 18", 17),
    ("extra_19", "Pole 19", 18),
    ("extra_20", "Pole 20", 19),
    ("extra_21", "Pole 21", 20),
)


@dataclass(frozen=True)
class ParsedLocalStationFile:
    filename: str
    days: list[list[dict[str, Any]]]
    row_count: int
    event_counts: dict[str, int]
    warnings: list[str]
    inferred_start: date | None = None
    inferred_end: date | None = None


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _decode(data: bytes | str) -> str:
    if isinstance(data, str):
        return data
    for enc in ("utf-8-sig", "utf-8", "cp1250"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _split_export_days(text: str) -> list[str]:
    """Split a GSelector multi-day export.

    GSelector writes a UTF-8 BOM at the start of every daily file. When several
    dates are exported into one range/file, those BOMs survive in the combined
    text. They are therefore a much safer day boundary than looking for a time
    going from 23:xx back to 00:xx (60+ minutes/hour can produce odd values).
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    chunks = [part for part in re.split("\ufeff", normalized) if part.strip()]
    return chunks or ([normalized] if normalized.strip() else [])


def _filename_date_range(filename: str, *, today: date | None = None) -> tuple[date | None, date | None]:
    ref = today or date.today()
    name = Path(filename or "").name

    # 2026-09-30_2026-10-12 / 20260930-20261012
    iso_span = re.search(
        r"(?<!\d)(20\d{2})[-_.]?(1[0-2]|0?[1-9])[-_.]?([0-2]?\d|3[01])[^0-9]+"
        r"(20\d{2})[-_.]?(1[0-2]|0?[1-9])[-_.]?([0-2]?\d|3[01])(?!\d)",
        name,
    )
    if iso_span:
        try:
            start = date(int(iso_span.group(1)), int(iso_span.group(2)), int(iso_span.group(3)))
            end = date(int(iso_span.group(4)), int(iso_span.group(5)), int(iso_span.group(6)))
            return start, end
        except ValueError:
            pass

    # 2026-09-30 / 20260930
    iso = re.search(r"(?<!\d)(20\d{2})[-_.]?(1[0-2]|0?[1-9])[-_.]?([0-2]?\d|3[01])(?!\d)", name)
    if iso:
        try:
            d = date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
            return d, d
        except ValueError:
            pass

    # 30.09-12.10 (year comes from current date; crossing Dec->Jan is handled).
    span = re.search(r"(?<!\d)([0-3]?\d)[._-]([01]?\d)\s*[-–]\s*([0-3]?\d)[._-]([01]?\d)(?!\d)", name)
    if span:
        try:
            start = date(ref.year, int(span.group(2)), int(span.group(1)))
            end_year = ref.year + (1 if int(span.group(4)) < int(span.group(2)) else 0)
            end = date(end_year, int(span.group(4)), int(span.group(3)))
            return start, end
        except ValueError:
            pass

    # 28.09 / 28-09
    single = re.search(r"(?<!\d)([0-3]?\d)[._-]([01]?\d)(?!\d)", name)
    if single:
        try:
            d = date(ref.year, int(single.group(2)), int(single.group(1)))
            return d, d
        except ValueError:
            pass
    return None, None


def _parse_time(raw: str) -> tuple[float | None, bool]:
    value = str(raw or "").strip().lstrip("\ufeff").strip('"')
    m = re.fullmatch(r"(\d{1,2}):(\d+):(\d{1,2}(?:\.\d+)?)", value)
    if not m:
        return None, bool(value)
    hour, minute, second = int(m.group(1)), int(m.group(2)), float(m.group(3))
    if hour < 0 or second >= 60:
        return None, True
    # With GSelector's "60+ minutes/hour" option a value such as 08:62:47.3
    # is deliberate: the 08 hour is 2:47.3 over.  Keep it sortable, but do
    # NOT mark the normal 60+ representation as an anomaly.  Values in the
    # hundreds/thousands of minutes (seen in one reconciled export as 1439)
    # are still treated as malformed and kept only as raw text.
    if minute >= 180:
        return None, True
    total = hour * 3600.0 + minute * 60.0 + second
    return total % 86400.0, hour >= 24


def _schedule_hour(raw: str) -> int | None:
    value = str(raw or "").strip().lstrip("\ufeff").strip('"')
    m = re.fullmatch(r"(\d{1,2}):(\d+):(\d{1,2}(?:\.\d+)?)", value)
    if not m:
        return None
    hour = int(m.group(1))
    return hour if 0 <= hour <= 23 else None


def _gap_overrun_seconds(raw: str) -> float | None:
    """Return overtime beyond HH:59:59 as a positive duration.

    GSelector's 60+ minutes/hour display deliberately keeps an event in its
    scheduling hour, so 08:62:47.3 means +02:47.3 overtime for the 08 hour.
    """
    value = str(raw or "").strip().lstrip("\ufeff").strip('"')
    m = re.fullmatch(r"(\d{1,2}):(\d+):(\d{1,2}(?:\.\d+)?)", value)
    if not m:
        return None
    minute, second = int(m.group(2)), float(m.group(3))
    if 60 <= minute < 180 and second < 60:
        return (minute - 60) * 60.0 + second
    return None


def _format_gap(seconds: float | None) -> str:
    if seconds is None:
        return ""
    value = max(0.0, float(seconds))
    minutes = int(value // 60)
    secs = value - minutes * 60
    if abs(secs - round(secs)) < 1e-9:
        return f"+{minutes:02d}:{int(round(secs)):02d}"
    return f"+{minutes:02d}:{secs:04.1f}"


def _parse_duration(raw: str) -> float | None:
    value = str(raw or "").strip()
    m = re.fullmatch(r"(?:(\d+):)?(\d{1,2}):(\d{1,2}(?:\.\d+)?)", value)
    if not m:
        m2 = re.fullmatch(r"(\d+):(\d{1,2}(?:\.\d+)?)", value)
        if not m2:
            return None
        return int(m2.group(1)) * 60.0 + float(m2.group(2))
    hours = int(m.group(1) or 0)
    return hours * 3600.0 + int(m.group(2)) * 60.0 + float(m.group(3))


def _event_type(row: list[str]) -> str:
    second = str(row[1] if len(row) > 1 else "").strip()
    upper = second.upper()
    if second.startswith("ETM_"):
        return "etm"
    if upper == "ZETTA PLAY ASSET":
        return "command"
    if "SPOT BLOCK" in upper:
        return "traffic"
    # Song rows in the current RadioCharts export have the long Song sub-format
    # (artist=column 5, title=column 6). This remains intentionally structural,
    # not category-hardcoded, so future music categories still import as songs.
    if len(row) >= 17 and str(row[4]).strip() and str(row[5]).strip():
        return "song"
    if "AUDYCJ" in upper or upper.startswith(("A15/", "A30/")):
        return "show"
    if upper.startswith(("POD/", "P30/", "P60/")) or "PODKŁAD" in upper or "PODKLAD" in upper:
        return "bed"
    if upper.startswith("INT/") or "INFORMACJE" in upper:
        return "info"
    if upper.startswith(("J", "JL")) or "JINGLE" in upper:
        return "jingle"
    low = second.casefold().strip()
    if low in {"reklama", "po_reklamie", "autopromocja"} or "reklam" in low:
        return "traffic"
    return "other"


def _event_fields(row: list[str], line_no: int) -> dict[str, Any]:
    values = [str(v).strip() for v in row]
    air_raw = values[0].lstrip("\ufeff").strip('"') if values else ""
    air_seconds, odd_time = _parse_time(air_raw)
    typ = _event_type(values)
    category = values[1] if len(values) > 1 else ""
    artist = ""
    title = ""
    external_id = ""
    exact_raw = ""
    runtime_raw = ""

    if typ == "song":
        artist = values[4] if len(values) > 4 else ""
        title = values[5] if len(values) > 5 else ""
        exact_raw = values[12] if len(values) > 12 else ""
        runtime_raw = values[14] if len(values) > 14 else ""
        external_id = values[16] if len(values) > 16 else ""
    elif typ == "etm":
        title = category
        category = "ETM"
        external_id = values[3] if len(values) > 3 else ""
    elif typ == "command":
        title = category
        category = "Zetta"
        external_id = values[2] if len(values) > 2 else ""
    else:
        title = values[2] if len(values) > 2 else category
        external_id = values[4] if len(values) > 4 else ""

    exact_seconds, exact_odd = _parse_time(exact_raw) if exact_raw else (None, False)
    if air_seconds is None and exact_seconds is not None:
        # Keep air_time_raw untouched but make the row sortable by its reliable
        # Exact Time when GSelector emitted an obviously broken Air Time.
        sort_seconds = exact_seconds
    else:
        sort_seconds = air_seconds

    projected = {
        key: (values[index] if typ == "song" and len(values) > index else "")
        for key, _label, index in GSELECTOR_SONG_COLUMNS
    }
    return {
        "line_no": int(line_no),
        "air_time_raw": air_raw,
        "air_seconds": air_seconds,
        "sort_seconds": sort_seconds,
        "schedule_hour": _schedule_hour(air_raw),
        "gap_seconds": _gap_overrun_seconds(air_raw),
        "gap_raw": _format_gap(_gap_overrun_seconds(air_raw)),
        "etm_delta_raw": (values[2] if typ == "etm" and len(values) > 2 else ""),
        "time_anomaly": bool(odd_time or exact_odd),
        "event_type": typ,
        "category": category,
        "artist": artist,
        "title": title,
        "external_id": external_id,
        "exact_time_raw": exact_raw,
        "exact_seconds": exact_seconds,
        "runtime_raw": runtime_raw,
        "runtime_seconds": _parse_duration(runtime_raw) if runtime_raw else None,
        "raw_fields": values,
        **projected,
    }


def _mark_traffic_groups(events: list[dict[str, Any]]) -> None:
    """Mark bare spot rows that share an Air Time with an advertising marker."""
    start = 0
    while start < len(events):
        raw_time = str(events[start].get("air_time_raw") or "")
        end = start + 1
        while end < len(events) and str(events[end].get("air_time_raw") or "") == raw_time:
            end += 1
        group = events[start:end]
        if any(item.get("event_type") == "traffic" for item in group):
            for item in group:
                if item.get("event_type") in {"other", "traffic"}:
                    item["event_type"] = "traffic"
        start = end


def parse_gselector_export(data: bytes | str, filename: str = "") -> ParsedLocalStationFile:
    text = _decode(data)
    chunks = _split_export_days(text)
    warnings: list[str] = []
    days: list[list[dict[str, Any]]] = []
    counts: Counter[str] = Counter()
    total_rows = 0

    for day_index, chunk in enumerate(chunks):
        reader = csv.reader(io.StringIO(chunk), delimiter="\t", quotechar='"')
        parsed_day: list[dict[str, Any]] = []
        for line_no, row in enumerate(reader, start=1):
            if not row or not any(str(v).strip() for v in row):
                continue
            event = _event_fields(row, line_no)
            event["day_index"] = day_index
            event["sequence_no"] = len(parsed_day)
            parsed_day.append(event)
            counts[event["event_type"]] += 1
            total_rows += 1
        if parsed_day:
            _mark_traffic_groups(parsed_day)
            days.append(parsed_day)

    start, end = _filename_date_range(filename)
    if start and end:
        expected = (end - start).days + 1
        if expected != len(days):
            warnings.append(
                f"Nazwa pliku sugeruje {expected} dni ({start.isoformat()}–{end.isoformat()}), "
                f"a eksport zawiera {len(days)} bloków dziennych."
            )
    elif len(days) > 1:
        warnings.append("Nie udało się odczytać zakresu dat z nazwy pliku — wybierz datę początkową ręcznie.")

    anomalous = sum(1 for day in days for event in day if event["time_anomaly"])
    if anomalous:
        warnings.append(
            f"{anomalous} wierszy ma nietypowy/uszkodzony zapis czasu; surowy czas zostaje zachowany. "
            "Normalny zapis 60+ minutes/hour nie jest traktowany jako błąd."
        )

    return ParsedLocalStationFile(
        filename=filename,
        days=days,
        row_count=total_rows,
        event_counts=dict(counts),
        warnings=warnings,
        inferred_start=start,
        inferred_end=end,
    )


def preview_import(data: bytes | str, filename: str = "") -> dict[str, Any]:
    parsed = parse_gselector_export(data, filename)
    return {
        "filename": filename,
        "rows": parsed.row_count,
        "days": len(parsed.days),
        "event_counts": parsed.event_counts,
        "warnings": parsed.warnings,
        "inferred_start": parsed.inferred_start.isoformat() if parsed.inferred_start else None,
        "inferred_end": parsed.inferred_end.isoformat() if parsed.inferred_end else None,
    }


def _existing_song_id(con, artist: str, title: str) -> int | None:
    akey, tkey = db.normalize(artist), db.normalize(title)
    if not akey or not tkey:
        return None
    row = con.execute("SELECT id FROM songs WHERE artist_key=? AND title_key=?", (akey, tkey)).fetchone()
    if row:
        return int(row["id"])
    row = con.execute(
        """SELECT canonical_song_id FROM song_identity_aliases
           WHERE artist_key=? AND title_key=? LIMIT 1""",
        (akey, tkey),
    ).fetchone()
    return int(row["canonical_song_id"]) if row else None




def _parse_iso_datetime(raw: Any) -> datetime | None:
    value = str(raw or "").strip()
    if not value:
        return None
    # .NET often emits seven fractional digits; Python datetime stores six.
    value = re.sub(r"(\.\d{6})\d+(?=([+-]\d\d:\d\d)?$)", r"\1", value)
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _time_raw_from_group(actual: datetime | None, group_hour: int | None) -> str:
    if actual is None:
        return ""
    if group_hour is None:
        return f"{actual.hour:02d}:{actual.minute:02d}:{actual.second + actual.microsecond / 1_000_000:04.1f}"
    start = actual.replace(hour=int(group_hour), minute=0, second=0, microsecond=0)
    elapsed = (actual - start).total_seconds()
    # 23:xx log entries can legitimately air after midnight while still
    # belonging to the previous scheduling hour.
    if elapsed < -3600:
        elapsed += 86400
    if elapsed < 0:
        # Keep odd backtimed values readable instead of inventing negative minutes.
        return f"{actual.hour:02d}:{actual.minute:02d}:{actual.second + actual.microsecond / 1_000_000:04.1f}"
    minute = int(elapsed // 60)
    second = elapsed - minute * 60
    return f"{int(group_hour):02d}:{minute:02d}:{second:04.1f}"


def _zetta_event_type(asset: dict[str, Any]) -> str:
    asset_type = int(asset.get("AssetTypeID") or 0)
    title = str(asset.get("Title") or "")
    upper = title.upper()
    if asset_type == 1:
        return "song"
    if asset_type == 2:
        return "traffic"
    if "JINGLE" in upper:
        return "jingle"
    if "INFORMACJE" in upper or "SERWIS" in upper:
        return "info"
    if "PODKŁAD" in upper or "PODKLAD" in upper:
        return "bed"
    if "AUDYCJ" in upper or "WYWIAD" in upper:
        return "show"
    return "other"


def _asset_text(asset: dict[str, Any], *names: str) -> str:
    """Best-effort case-insensitive lookup in Zetta asset metadata.

    Different Zetta builds expose scheduler metadata under slightly different
    field names.  GetLog on EMAUS currently returns only a compact asset object,
    but keeping these aliases here means richer fields are picked up
    automatically when the server includes them.
    """
    if not isinstance(asset, dict):
        return ""
    wanted = {str(name).casefold().replace("_", "").replace(" ", "") for name in names}

    def scan(obj: dict[str, Any], depth: int = 0) -> str:
        for key, value in obj.items():
            norm = str(key).casefold().replace("_", "").replace(" ", "")
            if norm in wanted and value not in (None, ""):
                if isinstance(value, dict):
                    for subkey in ("Name", "Code", "Value", "Description", "Title"):
                        if value.get(subkey) not in (None, ""):
                            return str(value.get(subkey)).strip()
                elif not isinstance(value, (list, tuple, set)):
                    return str(value).strip()
        if depth < 2:
            for value in obj.values():
                if isinstance(value, dict):
                    found = scan(value, depth + 1)
                    if found:
                        return found
        return ""

    return scan(asset)


def _zetta_asset_metadata(asset: dict[str, Any]) -> dict[str, str]:
    return {
        "category_code": _asset_text(asset, "CategoryCode", "Category", "GSelectorCategoryCode", "GSelectorCategory", "SchedulerCategory", "SongCategory", "LinkCategory"),
        "mood": _asset_text(asset, "Mood", "MoodName", "GSelectorMood"),
        "opener": _asset_text(asset, "Opener", "OpenerCode", "GSelectorOpener"),
        "texture_open": _asset_text(asset, "TextureOpen", "OpenTexture", "Texture Open", "GSelectorTextureOpen"),
        "texture_close": _asset_text(asset, "TextureClose", "CloseTexture", "Texture Close", "GSelectorTextureClose"),
    }


def _zetta_category(event_type: str, asset: dict[str, Any]) -> str:
    exact = _zetta_asset_metadata(asset).get("category_code", "").strip()
    if exact:
        return exact
    if event_type == "song":
        return "Zetta / Song"
    if event_type == "traffic":
        sponsor = str(asset.get("Sponsor") or "").strip()
        return f"Zetta / Reklama{(' / ' + sponsor) if sponsor else ''}"
    if event_type == "show":
        return "AUD"
    return f"Zetta / {event_type.title()}"


def parse_zetta2go_log(
    payload: dict[str, Any],
    service_date: date | str,
    *,
    kind: str = "played",
) -> list[dict[str, Any]]:
    """Normalize Zetta2GO GetLog JSON into local_station event dictionaries.

    ``schedule`` snapshots intentionally retain READY/future events because the
    last pre-emission snapshot is the immutable comparison baseline. ``played``
    live snapshots also retain READY/WAITING rows in storage: the normal Played
    timeline filters them out, while reconciliation can immediately detect a
    post-cutoff insert/delete before its airtime arrives.
    """
    if kind not in LOCAL_KINDS:
        raise ValueError(kind)
    d = service_date if isinstance(service_date, date) else date.fromisoformat(str(service_date))
    source_rows = payload.get("rows") if isinstance(payload, dict) else None
    if not isinstance(source_rows, list):
        raise ValueError("Zetta2GO GetLog: brak tablicy rows.")

    out: list[dict[str, Any]] = []
    current_group_hour: int | None = None
    for source_index, source in enumerate(source_rows, start=1):
        if not isinstance(source, dict):
            continue
        cell = source.get("cell")
        if not isinstance(cell, list) or len(cell) < 19:
            continue
        try:
            entry_type = int(cell[0] or 0)
        except (TypeError, ValueError):
            entry_type = 0
        try:
            status_code = int(cell[9])
        except (TypeError, ValueError):
            status_code = 0
        try:
            edit_code = int(cell[2] or 0)
        except (TypeError, ValueError):
            edit_code = 0
        actual = _parse_iso_datetime(cell[5])

        # TOH rows define the scheduling hour. Using that hour instead of the
        # wall-clock AirTime preserves 60+ minutes/hour semantics in comparisons.
        # Keep the marker as a first-class row as well; the whole-day playlist
        # uses it as a strong visual separator just like Zetta2GO.
        if entry_type == 3 and actual is not None:
            current_group_hour = actual.hour

        raw_asset = cell[7]
        asset = raw_asset if isinstance(raw_asset, dict) else {}
        row_id = str(source.get("id") or "")
        universal_id = str(asset.get("UniversalIdentifier") or "") if asset else ""
        source_event_id = universal_id or row_id

        if entry_type == 3:  # Top of Hour helper row
            etm_type = ""
            raw_time = _time_raw_from_group(actual, current_group_hour)
            title = "Top of the hour"
            gap_seconds = None
            event_type = "toh"
            artist = ""
            category = "TOH"
            runtime_seconds = 0.0
            runtime_raw = ""
            asset_id = ""
            sponsor = ""
        elif entry_type == 15:  # Exact Time Marker
            etm_type = str(asset.get("ETMType") or "").strip() or "Other"
            raw_time = _time_raw_from_group(actual, current_group_hour)
            minute = actual.minute if actual is not None else 0
            second = actual.second if actual is not None else 0
            title = f"ETM_{minute:02d}:{second:02d}_{etm_type}"
            gap_ms = asset.get("gap")
            try:
                gap_seconds = float(gap_ms) / 1000.0 if gap_ms is not None else None
            except (TypeError, ValueError):
                gap_seconds = None
            event_type = "etm"
            artist = ""
            category = "ETM"
            runtime_seconds = 0.0
            runtime_raw = ""
            asset_id = ""
            sponsor = ""
        elif entry_type == 106:  # playable asset, including nested traffic spots
            if not asset:
                continue
            event_type = _zetta_event_type(asset)
            artist = str(asset.get("Artist") or "").strip()
            title = str(asset.get("Title") or "").strip()
            category = _zetta_category(event_type, asset)
            asset_id = str(asset.get("AssetID") or "").strip()
            sponsor = str(asset.get("Sponsor") or "").strip()
            raw_time = _time_raw_from_group(actual, current_group_hour)
            runtime_raw = str(asset.get("Runtime") or "").strip()
            try:
                runtime_seconds = float(cell[15]) / 1000.0 if cell[15] not in (None, "") else _parse_duration(runtime_raw)
            except (TypeError, ValueError):
                runtime_seconds = _parse_duration(runtime_raw)
            gap_seconds = None
        else:
            # Spot Block parents, TOH and helper rows are not audio files. Their
            # playable children (entry type 106) are already returned separately.
            continue

        air_seconds, odd_time = _parse_time(raw_time)
        try:
            duration_ms = float(cell[18]) if cell[18] not in (None, "") else None
        except (TypeError, ValueError):
            duration_ms = None
        calculated = cell[16] if isinstance(cell[16], dict) else {}
        meta = {
            "source_system": "zetta2go",
            "snapshot_kind": kind,
            "row_id": row_id,
            "source_event_id": source_event_id,
            "log_event_entry_type": entry_type,
            "etm_type": etm_type if entry_type == 15 else "",
            "status_code": status_code,
            "status_name": ZETTA_STATUS_NAMES.get(status_code, f"STATUS_{status_code}"),
            "edit_code": edit_code,
            "edit_code_name": ZETTA_EDIT_CODE_NAMES.get(edit_code, f"EditCode {edit_code}" if edit_code else ""),
            "asset_id": asset_id,
            "asset_type_id": int(asset.get("AssetTypeID") or 0) if asset else 0,
            "universal_identifier": universal_id,
            "sponsor": sponsor,
            "play_rate_tooltip": str(asset.get("PlayRateToolTip") or "") if asset else "",
            "duration_runtime": str(asset.get("DurationRuntime") or "") if asset else "",
            "duration_ms": duration_ms,
            "valid_for_playback": bool(cell[3]) if len(cell) > 3 else None,
            "skip": bool(cell[11]) if len(cell) > 11 else False,
            "fixed": bool(cell[12]) if len(cell) > 12 else False,
            "stretch": cell[13] if len(cell) > 13 else None,
            "calculated_times": calculated,
            "zetta_gap_ms": asset.get("gap") if entry_type == 15 else None,
            "zetta_original_gap_ms": asset.get("ogap") if entry_type == 15 else None,
            **(_zetta_asset_metadata(asset) if entry_type == 106 else {}),
        }
        out.append({
            "line_no": source_index,
            "sequence_no": len(out),
            "air_time_raw": raw_time,
            "air_seconds": air_seconds,
            "sort_seconds": air_seconds,
            "schedule_hour": current_group_hour if current_group_hour is not None else _schedule_hour(raw_time),
            "gap_seconds": _gap_overrun_seconds(raw_time),
            "gap_raw": _format_gap(_gap_overrun_seconds(raw_time)),
            "etm_delta_raw": _format_gap(abs(gap_seconds)) if gap_seconds is not None and gap_seconds >= 0 else (
                ("-" + _format_gap(abs(gap_seconds)).lstrip("+")) if gap_seconds is not None else ""
            ),
            "time_anomaly": bool(odd_time),
            "event_type": event_type,
            "category": category,
            "artist": artist,
            "title": title,
            # For Zetta->Zetta reconciliation this is the stable log-event GUID,
            # not the asset GUID. It survives airtime/status changes and gives us
            # exact matching. Cross-system GSelector fallback still uses text.
            "external_id": source_event_id,
            "asset_id": asset_id,
            "exact_time_raw": "",
            "exact_seconds": None,
            "runtime_raw": runtime_raw,
            "runtime_seconds": runtime_seconds,
            "source_system": "zetta2go",
            "play_status_code": status_code,
            "edit_code_int": edit_code,
            "payload": meta,
        })
    _apply_zetta_hour_boundary_gap_carry(out, payload)
    _annotate_zetta_ignore_reset_gaps(out, payload)
    return out


def _zetta_etm_offset_seconds(row: dict[str, Any]) -> float | None:
    """Seconds from the row's scheduling-hour start for a native Zetta ETM."""
    raw = str(row.get("air_time_raw") or "").strip()
    m = re.fullmatch(r"\d{1,2}:(\d+):(\d{1,2}(?:\.\d+)?)", raw)
    if not m:
        return None
    minute = int(m.group(1))
    second = float(m.group(2))
    if second >= 60 or minute >= 180:
        return None
    return minute * 60.0 + second


def _zetta_event_clock_seconds(row: dict[str, Any]) -> float | None:
    """Return unwrapped clock seconds for a parsed Zetta row.

    Unlike ``air_seconds`` this deliberately keeps 60+ minute notation
    unwrapped, so ``15:60:26`` sorts just after ``15:59:59`` and before
    ``16:00`` without losing the scheduling-hour context.
    """
    raw = str(row.get("air_time_raw") or "").strip()
    m = re.fullmatch(r"(\d{1,2}):(\d+):(\d{1,2}(?:\.\d+)?)", raw)
    if not m:
        return None
    hour = int(m.group(1))
    minute = int(m.group(2))
    second = float(m.group(3))
    if second >= 60 or minute >= 180:
        return None
    return hour * 3600.0 + minute * 60.0 + second



def _annotate_zetta_reset_local_gaps(events: list[dict[str, Any]]) -> None:
    """Derive RESET carry from the first playable that follows the marker.

    In Zetta a RESET is informational: it changes the displayed/calculation
    baseline, but it does not force the sequencer to start exactly at the RESET
    wall-clock time.  The most robust observable carry is therefore the offset
    of the first playable row after RESET relative to the RESET clock itself.

    Example: RESET 08:15:00 followed by the next playable at 08:15:34 means a
    +34 s carry.  This is exactly the amount that should survive when the UI
    asks to "ignore RESETs".

    Raw ``Asset.gap`` is retained only as a fallback if there is no playable
    row before the next timing anchor.  It is not preferred because real future
    logs can expose large context-dependent values which are unsafe to sum.
    """
    pending: tuple[dict[str, Any], float] | None = None

    def finalize_pending(*, fallback_to_native: bool = True) -> None:
        nonlocal pending
        if pending is None:
            return
        reset_row, _reset_clock = pending
        meta = reset_row.get("payload") if isinstance(reset_row.get("payload"), dict) else {}
        if meta.get("zetta_reset_local_gap_ms") is None and fallback_to_native:
            raw_gap = meta.get("zetta_gap_native_ms")
            if raw_gap is None:
                raw_gap = meta.get("zetta_gap_ms")
            try:
                value = float(raw_gap) if raw_gap is not None else None
            except (TypeError, ValueError):
                value = None
            if value is not None:
                meta["zetta_reset_local_gap_ms"] = value
                meta["zetta_reset_local_gap_source"] = "native_fallback"
                reset_row["payload"] = meta
        pending = None

    for row in events:
        if str(row.get("source_system") or "") != "zetta2go":
            continue

        if row.get("event_type") == "etm":
            meta = row.get("payload") if isinstance(row.get("payload"), dict) else {}
            etm_type = str(meta.get("etm_type") or "").strip().casefold()
            if etm_type == "reset":
                # If two RESETs are adjacent, the earlier one has no playable
                # row from which to derive carry; keep its native value only as
                # a fallback rather than inventing a timeline delta.
                finalize_pending()
                clock = _zetta_event_clock_seconds(row)
                if clock is not None:
                    pending = (row, clock)
                continue
            if etm_type in {"hard", "soft"}:
                finalize_pending()
                continue
            # HIT remains informational and does not close a RESET segment.
            continue

        if pending is None:
            continue

        meta = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        if bool(meta.get("skip")):
            continue
        clock = _zetta_event_clock_seconds(row)
        if clock is None:
            continue

        reset_row, reset_clock = pending
        reset_meta = reset_row.get("payload") if isinstance(reset_row.get("payload"), dict) else {}
        local_gap_ms = (clock - reset_clock) * 1000.0
        reset_meta["zetta_reset_local_gap_ms"] = local_gap_ms
        reset_meta["zetta_reset_local_gap_source"] = "next_playable_airtime"
        reset_row["payload"] = reset_meta
        pending = None

    finalize_pending()


def _raw_zetta_previous_hour_carry(payload: dict[str, Any]) -> tuple[float | None, str]:
    """Return (gap_ms, source) for 00:00 from the previous day's 23h rows.

    Prefer a final RESET near 59:59, but derive its carry from the first
    playable after the RESET.  If there is no usable boundary RESET, use only
    the last playable which *started before* 24:00.  Rows already starting at
    60+ minutes belong to the overrun/next clock context and must not inflate
    the boundary gap by tens of minutes.
    """
    rows = payload.get("radiocharts_previous_hour_rows") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return None, ""

    last_control = 0.0
    playable: list[tuple[float, float]] = []
    boundary_reset: dict[str, Any] | None = None
    pending_reset: tuple[dict[str, Any], datetime] | None = None

    def native_reset_gap(source: dict[str, Any]) -> float | None:
        cell = source.get("cell") if isinstance(source, dict) else None
        asset = cell[7] if isinstance(cell, list) and len(cell) > 7 and isinstance(cell[7], dict) else {}
        try:
            return float(asset.get("gap")) if asset.get("gap") is not None else None
        except (TypeError, ValueError):
            return None

    for source in rows:
        if not isinstance(source, dict):
            continue
        cell = source.get("cell")
        if not isinstance(cell, list) or len(cell) < 19:
            continue
        try:
            entry_type = int(cell[0] or 0)
        except (TypeError, ValueError):
            entry_type = 0
        actual = _parse_iso_datetime(cell[5])
        if actual is None:
            continue
        actual = actual.replace(tzinfo=None)
        offset = actual.minute * 60.0 + actual.second + actual.microsecond / 1_000_000.0

        if entry_type == 15:
            asset = cell[7] if isinstance(cell[7], dict) else {}
            etm_type = str(asset.get("ETMType") or "").strip().casefold()
            if etm_type in {"hard", "soft"}:
                if offset < 3600.0:
                    last_control = max(last_control, offset)
                pending_reset = None
                continue
            if etm_type == "reset":
                reset_info = {
                    "offset": offset,
                    "native_gap_ms": native_reset_gap(source),
                    "local_gap_ms": None,
                }
                pending_reset = (reset_info, actual)
                if 3590.0 <= offset <= 3600.0:
                    boundary_reset = reset_info
                continue
            continue

        if entry_type != 106:
            continue
        try:
            skipped = bool(cell[11])
        except Exception:
            skipped = False
        if skipped:
            continue

        runtime_ms = cell[15] if cell[15] not in (None, "") else cell[18]
        try:
            duration = float(runtime_ms) / 1000.0
        except (TypeError, ValueError):
            duration = 0.0
        if duration > 0 and offset < 3600.0:
            playable.append((offset, duration))

        if pending_reset is not None:
            info, reset_time = pending_reset
            info["local_gap_ms"] = (actual - reset_time).total_seconds() * 1000.0
            pending_reset = None

    if boundary_reset is not None:
        gap_ms = boundary_reset.get("native_gap_ms")
        if gap_ms is None:
            gap_ms = boundary_reset.get("local_gap_ms")
        try:
            gap_ms_f = float(gap_ms) if gap_ms is not None else None
        except (TypeError, ValueError):
            gap_ms_f = None
        if gap_ms_f is not None:
            offset = float(boundary_reset["offset"])
            return gap_ms_f - (3600.0 - offset) * 1000.0, "previous_hour_reset"

    ends = [
        offset + duration
        for offset, duration in playable
        if last_control <= offset < 3600.0
    ]
    if not ends:
        return None, ""
    return (max(ends) - 3600.0) * 1000.0, "previous_hour_tail"

def _apply_zetta_hour_boundary_gap_carry(events: list[dict[str, Any]], payload: dict[str, Any]) -> None:
    """Restore the cross-hour gap that Zetta2GO's hourly grid zeroes at TOH.

    Preferred source: the final RESET around 59:59, using the offset of the
    first playable after that RESET and adjusting it to the exact 60:00
    boundary. Daytime clocks often have no such RESET, so the fallback uses the
    last playable that actually *starts before* 60:00 after the final Hard/Soft
    control ETM. Queued rows whose start time is already 60+ are deliberately
    excluded because they are not the audio crossing the timing anchor.
    """
    # Derive a fallback local RESET delta for rare responses where Zetta does
    # not include Asset.gap. Native Zetta gap remains the preferred source.
    _annotate_zetta_reset_local_gaps(events)

    resets_by_hour: dict[int, tuple[float, float]] = {}
    controls_by_hour: dict[int, float] = {}
    playable_by_hour: dict[int, list[tuple[float, float]]] = {}

    for row in events:
        hour = row.get("schedule_hour")
        if not isinstance(hour, int):
            continue
        if row.get("event_type") == "etm":
            meta = row.get("payload") if isinstance(row.get("payload"), dict) else {}
            etm_type = str(meta.get("etm_type") or "").strip().casefold()
            offset = _zetta_etm_offset_seconds(row)
            if offset is None:
                continue
            if etm_type in {"hard", "soft"} and offset < 3600.0:
                controls_by_hour[hour] = max(controls_by_hour.get(hour, 0.0), offset)
            if etm_type == "reset" and 3590.0 <= offset <= 3600.0:
                # Zetta's own RESET gap is authoritative.  Do not infer a
                # RESET delta from the next row: a RESET can sit inside a long
                # running item, so the next playable may legitimately be tens
                # of minutes later.
                gap = meta.get("zetta_gap_ms")
                if gap is None:
                    gap = meta.get("zetta_reset_local_gap_ms")
                if gap is None:
                    continue
                try:
                    gap_ms = float(gap)
                except (TypeError, ValueError):
                    continue
                current = resets_by_hour.get(hour)
                if current is None or offset > current[0]:
                    resets_by_hour[hour] = (offset, gap_ms)
            continue

        meta = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        if bool(meta.get("skip")):
            continue
        offset = _zetta_etm_offset_seconds(row)
        if offset is None:
            # Same HH:MM:SS representation is used for playable rows.
            raw = str(row.get("air_time_raw") or "").strip()
            m = re.fullmatch(r"\d{1,2}:(\d+):(\d{1,2}(?:\.\d+)?)", raw)
            if not m:
                continue
            offset = int(m.group(1)) * 60.0 + float(m.group(2))
        # RuntimeMilliseconds / runtime_seconds is the effective scheduled
        # length to the next-play point. DurationMilliseconds is the full asset
        # duration and overstates tails when trims/segues are present.
        try:
            duration = float(row.get("runtime_seconds") or 0.0)
        except (TypeError, ValueError):
            duration = 0.0
        if duration <= 0:
            duration_ms = meta.get("duration_ms")
            try:
                duration = float(duration_ms) / 1000.0 if duration_ms not in (None, "") else 0.0
            except (TypeError, ValueError):
                duration = 0.0
        if duration > 0:
            playable_by_hour.setdefault(hour, []).append((offset, duration))

    midnight_carry, midnight_source = _raw_zetta_previous_hour_carry(payload)

    for row in events:
        if row.get("event_type") != "etm":
            continue
        meta = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        etm_type = str(meta.get("etm_type") or "").strip().casefold()
        if etm_type not in {"hard", "soft"}:
            continue
        offset = _zetta_etm_offset_seconds(row)
        if offset is None or abs(offset) > 0.05:
            continue
        native_gap = meta.get("zetta_gap_ms")
        try:
            native_gap_f = float(native_gap) if native_gap is not None else None
        except (TypeError, ValueError):
            native_gap_f = None
        if native_gap_f is not None and abs(native_gap_f) >= 0.5:
            continue

        hour = row.get("schedule_hour")
        if not isinstance(hour, int):
            continue
        if hour == 0:
            derived_ms = midnight_carry
            source = midnight_source
            source_hour = 23
        else:
            previous_hour = hour - 1
            previous_reset = resets_by_hour.get(previous_hour)
            if previous_reset is not None:
                reset_offset, reset_gap_ms = previous_reset
                derived_ms = reset_gap_ms - (3600.0 - reset_offset) * 1000.0
                source = "previous_hour_reset"
            else:
                last_control = controls_by_hour.get(previous_hour, 0.0)
                ends = [
                    start + duration
                    for start, duration in playable_by_hour.get(previous_hour, [])
                    # Only an element which started before the boundary can be
                    # the one actually crossing the next Hard/Soft. Rows with
                    # 60+ minute start times are queued overrun rows and were
                    # the source of false +17/+30/+50 minute values.
                    if last_control <= start < 3600.0
                ]
                derived_ms = (max(ends) - 3600.0) * 1000.0 if ends else None
                source = "previous_hour_tail" if ends else ""
            source_hour = previous_hour

        if derived_ms is None:
            continue
        meta["zetta_gap_native_ms"] = native_gap
        meta["zetta_gap_ms"] = derived_ms
        meta["zetta_gap_source"] = source
        meta["zetta_gap_source_hour"] = source_hour
        row["payload"] = meta
        gap_seconds = derived_ms / 1000.0
        sign = "+" if gap_seconds >= 0 else "-"
        value = abs(gap_seconds)
        minutes = int(value // 60)
        seconds = value - minutes * 60
        row["etm_delta_raw"] = f"{sign}{minutes:02d}:{seconds:04.1f}".rstrip("0").rstrip(".")



def _raw_zetta_reset_carry(rows: list[dict[str, Any]] | None) -> tuple[float, float | None, int]:
    """Return RESET carry since the last Hard/Soft in raw Zetta grid rows.

    For the ``Ignoruj resety`` diagnostic the authoritative quantity is the gap
    attached by Zetta to each RESET marker.  RESET changes Zetta's calculation
    baseline but does not force playout to that wall-clock time, so consecutive
    RESET gaps are deltas that must be accumulated until the next Hard/Soft.

    If Zetta did not provide ``Asset.gap`` for a RESET, do not invent a value
    from the visual timeline: underfilled/backtimed logs can place rows on both
    sides of a RESET and such reconstruction produced false +30/+50 minute
    carries.  Missing RESET gaps are therefore safely ignored.
    """
    carry_ms = 0.0
    last_reset_ms: float | None = None
    reset_count = 0

    for source in rows or []:
        if not isinstance(source, dict):
            continue
        cell = source.get("cell")
        if not isinstance(cell, list) or len(cell) < 8:
            continue
        try:
            entry_type = int(cell[0] or 0)
        except (TypeError, ValueError):
            entry_type = 0
        if entry_type != 15:
            continue
        asset = cell[7] if isinstance(cell[7], dict) else {}
        etm_type = str(asset.get("ETMType") or "").strip().casefold()
        if etm_type in {"hard", "soft"}:
            carry_ms = 0.0
            last_reset_ms = None
            reset_count = 0
            continue
        if etm_type != "reset":
            continue
        try:
            gap_ms = float(asset.get("gap")) if asset.get("gap") is not None else None
        except (TypeError, ValueError):
            gap_ms = None
        if gap_ms is None:
            continue
        carry_ms += gap_ms
        last_reset_ms = gap_ms
        reset_count += 1

    return carry_ms, last_reset_ms, reset_count

def _annotate_zetta_ignore_reset_gaps(events: list[dict[str, Any]], payload: dict[str, Any]) -> None:
    """Precompute Hard/Soft gaps for the UI's ``Ignoruj resety`` switch.

    Carry comes directly from Zetta's RESET ``Asset.gap`` values.  The marker
    resets Zetta's gap calculation, not the actual playout clock; therefore the
    RESET deltas are accumulated until the next Hard/Soft anchor.  Missing RESET
    gaps are ignored instead of being reconstructed from row airtimes.
    """
    previous_rows = payload.get("radiocharts_previous_hour_rows") if isinstance(payload, dict) else None
    carry_ms, last_reset_ms, reset_count = _raw_zetta_reset_carry(
        previous_rows if isinstance(previous_rows, list) else None
    )
    missing_reset_count = 0

    for row in events:
        if row.get("event_type") != "etm":
            continue
        meta = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        etm_type = str(meta.get("etm_type") or "").strip().casefold()
        if etm_type == "reset":
            try:
                gap_ms = float(meta.get("zetta_gap_ms")) if meta.get("zetta_gap_ms") is not None else None
            except (TypeError, ValueError):
                gap_ms = None
            if gap_ms is None:
                missing_reset_count += 1
            else:
                carry_ms += gap_ms
                last_reset_ms = gap_ms
                reset_count += 1
            continue
        if etm_type not in {"hard", "soft"}:
            continue

        base = meta.get("zetta_gap_ms")
        try:
            base_ms = float(base) if base is not None else None
        except (TypeError, ValueError):
            base_ms = None
        if base_ms is not None:
            correction_ms = carry_ms
            source = str(meta.get("zetta_gap_source") or "native")
            # A HH:00 value restored by 1.2.12 from the final ~59:59 RESET
            # already contains that RESET's own delta; add only earlier RESETs.
            if source == "previous_hour_reset" and last_reset_ms is not None:
                correction_ms -= last_reset_ms
            meta["zetta_gap_ignore_resets_ms"] = base_ms + correction_ms
            meta["zetta_gap_ignore_resets_carry_ms"] = correction_ms
            meta["zetta_gap_ignore_resets_reset_count"] = reset_count
            meta["zetta_gap_ignore_resets_missing_reset_count"] = missing_reset_count
            row["payload"] = meta

        carry_ms = 0.0
        last_reset_ms = None
        reset_count = 0
        missing_reset_count = 0


def _zetta_snapshot_digest(events: list[dict[str, Any]]) -> str:
    """Hash only fields that define the visible log state.

    Volatile heartbeat/sync counters are deliberately absent, so minute polling
    does not write SQLite when nothing user-visible changed.
    """
    digest_input = [
        {
            "id": e["external_id"], "air": e["air_time_raw"], "type": e["event_type"],
            "artist": e["artist"], "title": e["title"], "asset": e["asset_id"],
            "status": e["play_status_code"], "edit": e["edit_code_int"],
            "runtime": e["runtime_seconds"],
            "skip": bool((e.get("payload") or {}).get("skip")),
            "gap": (e.get("payload") or {}).get("zetta_gap_ms"),
        }
        for e in events
    ]
    raw = json.dumps(digest_input, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def import_zetta2go_snapshot(
    payload: dict[str, Any],
    *,
    service_date: date | str,
    kind: str = "played",
    station_key: str = STATION_KEY,
    source_name: str | None = None,
    source: str | None = None,
    replace_live: bool = False,
) -> dict[str, Any]:
    """Persist one Zetta day.

    Scheduled snapshots are versioned/archived. Live Played polling reuses one
    per-day import row and replaces its event rows in-place, avoiding hundreds
    of archived snapshots per day while still keeping the latest live state.
    """
    if kind not in LOCAL_KINDS:
        raise ValueError(kind)
    d = service_date if isinstance(service_date, date) else date.fromisoformat(str(service_date))
    events = parse_zetta2go_log(payload, d, kind=kind)
    digest = _zetta_snapshot_digest(events)
    imported_at = _utcnow()
    source_name = source_name or (f"Zetta2GO Live {d.isoformat()}" if kind == "played" else f"Zetta2GO Scheduled {d.isoformat()}")
    source = source or ("zetta2go-live" if replace_live else "zetta2go")
    stable_live_hash = (
        f"zetta2go-live:{station_key}:{d.isoformat()}"
        if replace_live else f"zetta2go:{d.isoformat()}:{digest}"
    )

    db.init_db()
    with db.connect() as con:
        existing = con.execute(
            """SELECT id,date_from,date_to,row_count,source_hash FROM local_station_imports
               WHERE station_key=? AND kind=? AND source_hash=? LIMIT 1""",
            (station_key, kind, stable_live_hash),
        ).fetchone()

        if existing and not replace_live:
            # The schedule can legitimately return to a previous exact state.
            # Reactivate it and stamp the latest fetch (important for cutoff).
            import_id = int(existing["id"])
            con.execute(
                "UPDATE local_station_events SET active=0 WHERE station_key=? AND kind=? AND service_date=? AND active=1",
                (station_key, kind, d.isoformat()),
            )
            con.execute("UPDATE local_station_events SET active=1 WHERE import_id=?", (import_id,))
            con.execute(
                """UPDATE local_station_imports SET source_name=?,source=?,imported_at=?,row_count=? WHERE id=?""",
                (source_name, source, imported_at, len(events), import_id),
            )
            return {
                "import_id": import_id, "duplicate": True, "reactivated": True, "kind": kind,
                "date_from": d.isoformat(), "date_to": d.isoformat(), "days": 1, "rows": len(events),
                "linked_songs": 0,
            }

        if existing and replace_live:
            import_id = int(existing["id"])
            old_digest_row = con.execute(
                "SELECT warnings_json FROM local_station_imports WHERE id=?", (import_id,)
            ).fetchone()
            try:
                old_meta = json.loads(str(old_digest_row["warnings_json"] or "{}")) if old_digest_row else {}
            except Exception:
                old_meta = {}
            if isinstance(old_meta, dict) and old_meta.get("content_hash") == digest:
                # No SQLite write at all when a minute poll is identical. This
                # keeps local_station_revision stable and avoids pointless UI
                # cache invalidations while the log has not changed.
                return {
                    "import_id": import_id, "duplicate": True, "unchanged": True, "kind": kind,
                    "date_from": d.isoformat(), "date_to": d.isoformat(), "days": 1, "rows": int(existing["row_count"]),
                    "linked_songs": 0,
                }
            con.execute(
                "UPDATE local_station_events SET active=0 WHERE station_key=? AND kind=? AND service_date=? AND active=1 AND import_id<>?",
                (station_key, kind, d.isoformat(), import_id),
            )
            con.execute("DELETE FROM local_station_events WHERE import_id=?", (import_id,))
            con.execute(
                """UPDATE local_station_imports
                   SET source_name=?,date_from=?,date_to=?,day_count=1,row_count=?,warnings_json=?,source=?,imported_at=?
                   WHERE id=?""",
                (source_name, d.isoformat(), d.isoformat(), len(events), json.dumps({"content_hash": digest}), source, imported_at, import_id),
            )
        else:
            con.execute(
                "UPDATE local_station_events SET active=0 WHERE station_key=? AND kind=? AND service_date=? AND active=1",
                (station_key, kind, d.isoformat()),
            )
            cur = con.execute(
                """INSERT INTO local_station_imports(
                       station_key,kind,source_name,source_hash,date_from,date_to,day_count,row_count,
                       warnings_json,source,imported_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    station_key, kind, source_name, stable_live_hash, d.isoformat(), d.isoformat(), 1, len(events),
                    json.dumps({"content_hash": digest}) if replace_live else "[]", source, imported_at,
                ),
            )
            import_id = int(cur.lastrowid)

        linked_songs = 0
        for event in events:
            song_id = None
            if event["event_type"] == "song":
                song_id = _existing_song_id(con, event["artist"], event["title"])
                linked_songs += int(song_id is not None)
            con.execute(
                """INSERT INTO local_station_events(
                       import_id,station_key,kind,service_date,sequence_no,line_no,
                       air_time_raw,air_seconds,sort_seconds,time_anomaly,event_type,category,
                       artist,title,external_id,exact_time_raw,exact_seconds,runtime_raw,runtime_seconds,
                       song_id,payload_json,source_system,play_status_code,edit_code_int,asset_id,active,created_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    import_id, station_key, kind, d.isoformat(), int(event["sequence_no"]), int(event["line_no"]),
                    event["air_time_raw"], event["air_seconds"], event["sort_seconds"], int(bool(event["time_anomaly"])),
                    event["event_type"], event["category"], event["artist"], event["title"], event["external_id"],
                    event["exact_time_raw"], event["exact_seconds"], event["runtime_raw"], event["runtime_seconds"], song_id,
                    json.dumps(event["payload"], ensure_ascii=False), "zetta2go", event["play_status_code"],
                    event["edit_code_int"], event["asset_id"], 1, imported_at,
                ),
            )

    played_count = sum(1 for e in events if e["event_type"] == "etm" or e["play_status_code"] in ZETTA_PLAYED_STATUS_CODES)
    nonplayed_count = sum(1 for e in events if e["play_status_code"] in ZETTA_NONPLAYED_STATUS_CODES)
    upcoming_count = sum(1 for e in events if e["play_status_code"] in ZETTA_UPCOMING_STATUS_CODES)
    return {
        "import_id": import_id, "duplicate": False, "kind": kind, "date_from": d.isoformat(), "date_to": d.isoformat(),
        "days": 1, "rows": len(events), "played_rows": played_count, "nonplayed_rows": nonplayed_count,
        "upcoming_rows": upcoming_count, "linked_songs": linked_songs,
    }


def sync_zetta2go_day(
    service_date: date | str,
    *,
    station_key: str = STATION_KEY,
    kind: str = "played",
    replace_live: bool | None = None,
    source: str | None = None,
    source_name: str | None = None,
    client: Zetta2GoClient | None = None,
) -> dict[str, Any]:
    cfg = zetta2go_settings()
    if not cfg.configured:
        raise RuntimeError("Brak konfiguracji Zetta2GO. Ustaw ZETTA2GO_USERNAME i ZETTA2GO_PASSWORD.")
    d = service_date if isinstance(service_date, date) else date.fromisoformat(str(service_date))
    own_client = client is None
    zclient = client or Zetta2GoClient(cfg)
    try:
        if own_client:
            login = zclient.login()
        else:
            login = {"ok": True, "reused_session": True}
        payload = zclient.get_log(d)
    finally:
        if own_client:
            zclient.close()
    result = import_zetta2go_snapshot(
        payload, service_date=d, kind=kind, station_key=station_key,
        source_name=source_name, source=source,
        replace_live=(kind == "played") if replace_live is None else bool(replace_live),
    )
    result["login"] = login
    result["records"] = int(payload.get("records") or len(payload.get("rows") or []))
    return result


def sync_zetta2go_schedule_horizon(
    base_date: date | None = None,
    *,
    station_key: str = STATION_KEY,
    horizon_days: int | None = None,
    mark_cutoff: bool = True,
) -> dict[str, Any]:
    """Refresh future Zetta schedules; tomorrow is always the cutoff snapshot.

    The job never rewrites today's Scheduled baseline. Running it every day at
    23:59 therefore makes the D+1 fetch the final pre-emission snapshot; any
    later change is visible only in the live log and becomes an intervention.
    """
    cfg = zetta2go_settings()
    if not cfg.configured:
        raise RuntimeError("Brak konfiguracji Zetta2GO. Ustaw ZETTA2GO_USERNAME i ZETTA2GO_PASSWORD.")
    if not cfg.schedule_enabled:
        return {"ok": True, "disabled": True, "days": []}
    base = base_date or date.today()
    horizon = max(1, min(31, int(horizon_days or cfg.schedule_horizon_days)))
    results: list[dict[str, Any]] = []
    with Zetta2GoClient(cfg) as client:
        client.login()
        for offset in range(1, horizon + 1):
            d = base + timedelta(days=offset)
            cutoff = bool(mark_cutoff and offset == 1)
            payload = client.get_log(d)
            item = import_zetta2go_snapshot(
                payload, service_date=d, kind="schedule", station_key=station_key,
                source_name=f"Zetta2GO {'CUTOFF' if cutoff else 'forecast'} {d.isoformat()}",
                source="zetta2go-cutoff" if cutoff else "zetta2go-forecast",
                replace_live=False,
            )
            item["cutoff"] = cutoff
            item["service_date"] = d.isoformat()
            item["records"] = int(payload.get("records") or len(payload.get("rows") or []))
            results.append(item)
    return {
        "ok": True, "base_date": base.isoformat(), "horizon_days": horizon,
        "cutoff_date": (base + timedelta(days=1)).isoformat() if mark_cutoff else None, "days": results,
    }


def sync_zetta2go_live(service_date: date | None = None, *, station_key: str = STATION_KEY) -> dict[str, Any]:
    cfg = zetta2go_settings()
    if not cfg.live_enabled:
        return {"ok": True, "disabled": True}
    d = service_date or date.today()
    return sync_zetta2go_day(
        d, station_key=station_key, kind="played", replace_live=True,
        source="zetta2go-live", source_name=f"Zetta2GO Live {d.isoformat()}",
    )


def test_zetta2go_connection() -> dict[str, Any]:
    cfg = zetta2go_settings()
    if not cfg.configured:
        return {"ok": False, "configured": False, "message": "Brak loginu/hasła Zetta2GO."}
    with Zetta2GoClient(cfg) as client:
        login = client.login()
        payload = client.get_log(date.today())
    return {
        "ok": True, "configured": True, "login": login,
        "records": int(payload.get("records") or len(payload.get("rows") or [])),
        "station_id": cfg.station_id, "base_url": cfg.base_url,
    }

def import_gselector_export(
    data: bytes | str,
    *,
    filename: str,
    kind: str,
    start_date: date | str | None = None,
    station_key: str = STATION_KEY,
    source: str = "manual",
) -> dict[str, Any]:
    if kind not in LOCAL_KINDS:
        raise ValueError(f"Nieobsługiwany rodzaj importu: {kind!r}")
    raw_bytes = data.encode("utf-8") if isinstance(data, str) else bytes(data)
    parsed = parse_gselector_export(raw_bytes, filename)
    if not parsed.days:
        raise ValueError("Plik nie zawiera żadnych wierszy GSelectora.")

    if isinstance(start_date, str) and start_date:
        start = date.fromisoformat(start_date)
    elif isinstance(start_date, date):
        start = start_date
    else:
        start = parsed.inferred_start
    if start is None:
        raise ValueError("Nie udało się ustalić daty początkowej importu.")

    assigned_dates = [start + timedelta(days=i) for i in range(len(parsed.days))]
    digest = hashlib.sha256(raw_bytes).hexdigest()
    imported_at = _utcnow()

    db.init_db()
    with db.connect() as con:
        existing = con.execute(
            """SELECT id,date_from,date_to,row_count FROM local_station_imports
               WHERE station_key=? AND kind=? AND source_hash=? LIMIT 1""",
            (station_key, kind, digest),
        ).fetchone()
        if existing:
            return {
                "import_id": int(existing["id"]),
                "duplicate": True,
                "kind": kind,
                "date_from": str(existing["date_from"]),
                "date_to": str(existing["date_to"]),
                "days": len(parsed.days),
                "rows": int(existing["row_count"]),
                "event_counts": parsed.event_counts,
                "warnings": parsed.warnings,
            }

        cur = con.execute(
            """INSERT INTO local_station_imports(
                   station_key,kind,source_name,source_hash,date_from,date_to,day_count,row_count,
                   warnings_json,source,imported_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                station_key,
                kind,
                Path(filename).name,
                digest,
                assigned_dates[0].isoformat(),
                assigned_dates[-1].isoformat(),
                len(assigned_dates),
                parsed.row_count,
                json.dumps(parsed.warnings, ensure_ascii=False),
                source,
                imported_at,
            ),
        )
        import_id = int(cur.lastrowid)

        # A later import is the new current snapshot for every covered day. Old
        # rows remain archived (active=0), so plan revisions are never lost.
        for service_date in assigned_dates:
            con.execute(
                """UPDATE local_station_events SET active=0
                   WHERE station_key=? AND kind=? AND service_date=? AND active=1""",
                (station_key, kind, service_date.isoformat()),
            )

        linked_songs = 0
        for service_date, events in zip(assigned_dates, parsed.days):
            for event in events:
                song_id = None
                if event["event_type"] == "song":
                    song_id = _existing_song_id(con, event["artist"], event["title"])
                    linked_songs += int(song_id is not None)
                con.execute(
                    """INSERT INTO local_station_events(
                           import_id,station_key,kind,service_date,sequence_no,line_no,
                           air_time_raw,air_seconds,sort_seconds,time_anomaly,event_type,category,
                           artist,title,external_id,exact_time_raw,exact_seconds,runtime_raw,runtime_seconds,
                           song_id,payload_json,active,created_at
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        import_id,
                        station_key,
                        kind,
                        service_date.isoformat(),
                        int(event["sequence_no"]),
                        int(event["line_no"]),
                        event["air_time_raw"],
                        event["air_seconds"],
                        event["sort_seconds"],
                        int(bool(event["time_anomaly"])),
                        event["event_type"],
                        event["category"],
                        event["artist"],
                        event["title"],
                        event["external_id"],
                        event["exact_time_raw"],
                        event["exact_seconds"],
                        event["runtime_raw"],
                        event["runtime_seconds"],
                        song_id,
                        json.dumps(event["raw_fields"], ensure_ascii=False),
                        1,
                        imported_at,
                    ),
                )

    return {
        "import_id": import_id,
        "duplicate": False,
        "kind": kind,
        "date_from": assigned_dates[0].isoformat(),
        "date_to": assigned_dates[-1].isoformat(),
        "days": len(assigned_dates),
        "rows": parsed.row_count,
        "linked_songs": linked_songs,
        "event_counts": parsed.event_counts,
        "warnings": parsed.warnings,
    }


def local_station_revision(station_key: str = STATION_KEY) -> str:
    """Cheap cache key for EMAUS/GSelector-derived UI data.

    The import table is append-only except for explicit delete/restore operations.
    max id + row count + newest timestamp therefore invalidates cached dates,
    timelines and comparisons after every import/delete without scanning events.
    """
    db.init_db()
    with db.connect() as con:
        row = con.execute(
            """SELECT COALESCE(MAX(id),0) AS max_id,COUNT(*) AS n,
                      COALESCE(MAX(imported_at),'') AS newest
               FROM local_station_imports WHERE station_key=?""",
            (station_key,),
        ).fetchone()
    if not row:
        return "0|0|"
    return f"{int(row['max_id'] or 0)}|{int(row['n'] or 0)}|{str(row['newest'] or '')}"


def available_dates(kind: str, station_key: str = STATION_KEY) -> list[str]:
    db.init_db()
    with db.connect() as con:
        rows = con.execute(
            """SELECT DISTINCT service_date FROM local_station_events
               WHERE station_key=? AND kind=? AND active=1 ORDER BY service_date""",
            (station_key, kind),
        ).fetchall()
    return [str(row["service_date"]) for row in rows]


def import_history(station_key: str = STATION_KEY, limit: int = 50) -> list[dict[str, Any]]:
    db.init_db()
    with db.connect() as con:
        rows = con.execute(
            """SELECT id,kind,source_name,date_from,date_to,day_count,row_count,source,imported_at,warnings_json
               FROM local_station_imports WHERE station_key=?
               ORDER BY id DESC LIMIT ?""",
            (station_key, max(1, int(limit))),
        ).fetchall()
    return [dict(row) for row in rows]



def _raw_fields_from_payload(payload_json: Any) -> list[Any]:
    try:
        payload = json.loads(str(payload_json or "[]"))
    except Exception:
        return []
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("raw_fields"), list):
        return payload["raw_fields"]
    return []


def _gselector_fallback_maps(rows: Iterable[Any]) -> tuple[dict[tuple[str, str], dict[str, str]], dict[tuple[str, str, str], dict[str, str]], dict[tuple[str, str], dict[str, str]]]:
    """Build latest-known GSelector coding maps for Zetta rows.

    Song metadata prefers canonical ``song_id`` when available, then falls back
    to normalized artist/title. Non-song links/jingles use event type + title.
    Rows are supplied newest-first, so ``setdefault`` preserves the latest code.
    """
    by_song_id: dict[tuple[str, str], dict[str, str]] = {}
    by_song_text: dict[tuple[str, str, str], dict[str, str]] = {}
    by_event_title: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        item = dict(row)
        event_type = str(item.get("event_type") or "")
        artist = str(item.get("artist") or "")
        title = str(item.get("title") or "")
        raw = _raw_fields_from_payload(item.get("payload_json"))
        meta: dict[str, str] = {
            "category": str(item.get("category") or ""),
            "category_code": str(item.get("category") or "").split("/", 1)[0].strip(),
        }
        if event_type == "song":
            for key, _label, index in GSELECTOR_SONG_COLUMNS:
                if len(raw) > index and raw[index] not in (None, ""):
                    meta[key] = str(raw[index]).strip()
            sid = item.get("song_id")
            if sid is not None:
                by_song_id.setdefault(("song_id", str(int(sid))), meta)
            by_song_text.setdefault(("song", db.normalize(artist), db.normalize(title)), meta)
        elif title:
            by_event_title.setdefault((event_type, db.normalize(title)), meta)
    return by_song_id, by_song_text, by_event_title


def _apply_zetta_metadata_fallback(out: list[dict[str, Any]], fallback_rows: Iterable[Any]) -> None:
    by_song_id, by_song_text, by_event_title = _gselector_fallback_maps(fallback_rows)
    for item in out:
        if str(item.get("source_system") or "") != "zetta2go":
            continue
        event_type = str(item.get("event_type") or "")
        if event_type in {"etm", "toh"}:
            item["category_code"] = _local_category_code(item)
            continue
        fallback: dict[str, str] = {}
        if event_type == "song" and item.get("song_id") is not None:
            fallback = by_song_id.get(("song_id", str(int(item["song_id"])))) or {}
        if not fallback and event_type == "song":
            fallback = by_song_text.get(("song", db.normalize(str(item.get("artist") or "")), db.normalize(str(item.get("title") or "")))) or {}
        if not fallback and item.get("title"):
            fallback = by_event_title.get((event_type, db.normalize(str(item.get("title") or "")))) or {}

        for key in ("mood", "opener", "texture_open", "texture_close"):
            if not str(item.get(key) or "").strip():
                item[key] = str(fallback.get(key) or "")
        current_category = str(item.get("category") or "")
        if (not current_category or current_category.startswith("Zetta /")) and fallback.get("category"):
            item["category"] = str(fallback["category"])
        native_code = str(item.get("category_code") or "").strip()
        item["category_code"] = native_code or str(fallback.get("category_code") or "") or _local_category_code(item)


def _local_category_code(item: dict[str, Any]) -> str:
    event_type = str(item.get("event_type") or "")
    if event_type == "etm":
        meta = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        return str(meta.get("etm_type") or "ETM").upper()
    if event_type == "toh":
        return "TOH"
    category = str(item.get("category") or "").strip()
    if category and not category.startswith("Zetta /"):
        return category.split("/", 1)[0].strip()
    return {
        "song": "SONG",
        "jingle": "JINGLE",
        "show": "AUD",
        "bed": "POD",
        "info": "INFO",
        "traffic": "REKL",
        "command": "CMD",
    }.get(event_type, category.split("/", 1)[-1].strip().upper() if category else event_type.upper())


def _format_played_seconds(value: float | None) -> str:
    if value is None:
        return ""
    try:
        total = max(0.0, float(value))
    except (TypeError, ValueError):
        return ""
    minutes = int(total // 60)
    seconds = total - minutes * 60
    if abs(seconds - round(seconds)) < .05:
        return f"{minutes:02d}:{int(round(seconds)):02d}"
    return f"{minutes:02d}:{seconds:04.1f}".rstrip("0").rstrip(".")


def _annotate_played_lengths(rows: list[dict[str, Any]], service_date: str, kind: str) -> None:
    """Add a practical playout-duration estimate to Zetta Played rows.

    GetLog exposes the scheduled/effective runtime, but this build does not
    expose a separate AirStopTime column.  For finished/current playout rows we
    therefore use Zetta's effective runtime for ordinary completed plays. For
    explicit fade/stopped statuses, the next actually-aired event start can be
    used as a shorter estimate, but only when it implies a material cut (>=10 s
    and >=10%). This avoids calling ordinary crossfades a shortened play. Current
    rows use wall-clock elapsed time and are refreshed by the Streamlit fragment.
    """
    if kind != "played":
        return
    def unwrapped_start(row: dict[str, Any]) -> float | None:
        raw = str(row.get("air_time_raw") or "").strip()
        match = re.fullmatch(r"(\d{1,2}):(\d+):(\d{1,2}(?:\.\d+)?)", raw)
        if match:
            return int(match.group(1)) * 3600.0 + int(match.group(2)) * 60.0 + float(match.group(3))
        try:
            return float(row.get("sort_seconds")) if row.get("sort_seconds") is not None else None
        except (TypeError, ValueError):
            return None

    candidates = [
        row for row in rows
        if str(row.get("source_system") or "") == "zetta2go"
        and str(row.get("event_type") or "") not in {"etm", "toh", "command"}
        and int(row.get("zetta_status_code") or 0) in ZETTA_PLAYED_STATUS_CODES
        and unwrapped_start(row) is not None
    ]
    candidates.sort(key=lambda row: int(row.get("sequence_no") or 0))
    now = datetime.now().astimezone()
    is_today = str(service_date) == now.date().isoformat()

    for index, row in enumerate(candidates):
        start = float(unwrapped_start(row) or 0.0)
        next_start: float | None = None
        for nxt in candidates[index + 1:]:
            probe_raw = unwrapped_start(nxt)
            if probe_raw is None:
                continue
            probe = float(probe_raw)
            if probe < start - 12 * 3600:
                probe += 86400
            if probe > start + 0.05:
                next_start = probe
                break
        delta = (next_start - start) if next_start is not None else None
        status = int(row.get("zetta_status_code") or 0)
        if is_today and status in {-3, 2, 9}:
            elapsed_now = now.hour * 3600 + now.minute * 60 + now.second + now.microsecond / 1_000_000 - start
            if elapsed_now < -12 * 3600:
                elapsed_now += 86400
            if elapsed_now >= 0:
                delta = elapsed_now

        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        max_duration = None
        for candidate in (
            row.get("runtime_seconds"),
            (float(payload.get("duration_ms")) / 1000.0 if payload.get("duration_ms") not in (None, "") else None),
        ):
            try:
                val = float(candidate) if candidate is not None else None
            except (TypeError, ValueError):
                val = None
            if val is not None and val > 0:
                max_duration = val
                break
        # For an ordinary completed play, the effective Zetta runtime is the
        # best value we have. The next event may begin a few seconds earlier
        # because of a normal segue/crossfade, which does *not* mean the first
        # asset stopped at that instant. Only cut-like Zetta statuses (fade /
        # stopped) may use the next actual start as a shorter playout estimate,
        # and even then only for a material cut (>=10 s and >=10%).
        if is_today and status in {-3, 2, 9} and delta is not None and delta >= 0:
            actual = min(delta, max_duration) if max_duration is not None else delta
        elif status in {6, 7, 8} and delta is not None and delta >= 0 and max_duration is not None:
            cut_seconds = max_duration - delta
            cut_ratio = cut_seconds / max_duration if max_duration > 0 else 0.0
            actual = max(0.0, delta) if cut_seconds >= 10.0 and cut_ratio >= 0.10 else max_duration
        elif status in {3, 6, 7, 8} and max_duration is not None:
            actual = max_duration
        else:
            actual = None
        row["played_seconds"] = actual
        row["played_raw"] = _format_played_seconds(actual)


def events_for_day(
    kind: str,
    service_date: date | str,
    *,
    hour: int | None = None,
    event_types: Iterable[str] | None = None,
    station_key: str = STATION_KEY,
    include_nonplayed: bool = False,
) -> list[dict[str, Any]]:
    if kind not in LOCAL_KINDS:
        raise ValueError(kind)
    d = service_date.isoformat() if isinstance(service_date, date) else str(service_date)
    params: list[Any] = [station_key, kind, d]
    where = ["station_key=?", "kind=?", "service_date=?", "active=1"]
    types = [str(x) for x in (event_types or []) if str(x)]
    if types:
        where.append("event_type IN (%s)" % ",".join("?" for _ in types))
        params.extend(types)
    db.init_db()
    with db.connect() as con:
        rows = con.execute(
            f"""SELECT id,service_date,sequence_no,line_no,air_time_raw,air_seconds,sort_seconds,
                       time_anomaly,event_type,category,artist,title,external_id,exact_time_raw,
                       runtime_raw,runtime_seconds,song_id,import_id,payload_json,
                       source_system,play_status_code,edit_code_int,asset_id
                FROM local_station_events WHERE {' AND '.join(where)}
                ORDER BY sequence_no""",
            params,
        ).fetchall()
        fallback_rows = []
        if any(str(row["source_system"] or "") == "zetta2go" for row in rows):
            # Zetta GetLog is intentionally compact and some installations do
            # not include GSelector coding fields (category/mood/opener/texture)
            # in the Asset object. Keep the latest imported GSelector coding as
            # a local fallback, matched by canonical song/text identity.
            fallback_rows = con.execute(
                """SELECT service_date,sequence_no,event_type,category,artist,title,song_id,payload_json
                   FROM local_station_events
                   WHERE station_key=? AND source_system<>'zetta2go'
                   ORDER BY service_date DESC, sequence_no DESC
                   LIMIT 30000""",
                (station_key,),
            ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        meta: dict[str, Any] = {}
        try:
            payload = json.loads(str(item.pop("payload_json") or "[]"))
            if isinstance(payload, list):
                raw_fields = payload
            elif isinstance(payload, dict):
                raw_fields = payload.get("raw_fields") if isinstance(payload.get("raw_fields"), list) else []
                meta = payload
            else:
                raw_fields = []
        except Exception:
            raw_fields = []
        if str(item.get("source_system") or "") != "zetta2go":
            for key, _label, index in GSELECTOR_SONG_COLUMNS:
                item[key] = str(raw_fields[index]) if item.get("event_type") == "song" and len(raw_fields) > index else ""
        else:
            # Do not let empty GSelector projections overwrite native Zetta
            # event GUID/runtime fields already stored in the row.
            for key, _label, _index in GSELECTOR_SONG_COLUMNS:
                item.setdefault(key, "")
        item["schedule_hour"] = _schedule_hour(str(item.get("air_time_raw") or ""))
        item["gap_seconds"] = _gap_overrun_seconds(str(item.get("air_time_raw") or ""))
        item["gap_raw"] = _format_gap(item["gap_seconds"])
        if str(item.get("source_system") or "") == "zetta2go":
            status_code = int(item.get("play_status_code") or 0)
            item["zetta_status_code"] = status_code
            item["zetta_status"] = ZETTA_STATUS_NAMES.get(status_code, f"STATUS_{status_code}")
            edit_int = int(item.get("edit_code_int") or 0)
            item["zetta_edit_code"] = edit_int
            item["zetta_edit_name"] = ZETTA_EDIT_CODE_NAMES.get(edit_int, f"EditCode {edit_int}" if edit_int else "")
            item["edit_code"] = " · ".join(x for x in [str(edit_int) if edit_int else "", item["zetta_edit_name"]] if x)
            item["zetta_asset_id"] = str(item.get("asset_id") or meta.get("asset_id") or "")
            item["play_rate_tooltip"] = str(meta.get("play_rate_tooltip") or "")
            item["duration_runtime"] = str(meta.get("duration_runtime") or "")
            item["zetta_skip"] = bool(meta.get("skip"))
            item["zetta_fixed"] = bool(meta.get("fixed"))
            item["zetta_valid_for_playback"] = meta.get("valid_for_playback")
            item["zetta_gap_source"] = str(meta.get("zetta_gap_source") or "native")
            item["zetta_gap_ms"] = meta.get("zetta_gap_ms")
            item["zetta_gap_native_ms"] = meta.get("zetta_gap_native_ms")
            item["zetta_reset_local_gap_ms"] = meta.get("zetta_reset_local_gap_ms")
            item["zetta_gap_ignore_resets_ms"] = meta.get("zetta_gap_ignore_resets_ms")
            item["zetta_gap_ignore_resets_carry_ms"] = meta.get("zetta_gap_ignore_resets_carry_ms")
            item["zetta_gap_ignore_resets_reset_count"] = int(meta.get("zetta_gap_ignore_resets_reset_count") or 0)
            item["payload"] = meta
            item["mood"] = str(meta.get("mood") or "")
            item["opener"] = str(meta.get("opener") or "")
            item["texture_open"] = str(meta.get("texture_open") or "")
            item["texture_close"] = str(meta.get("texture_close") or "")
            item["category_code"] = str(meta.get("category_code") or "")
            item["etm_delta_raw"] = ""
            if item.get("event_type") == "etm":
                gap_ms = meta.get("zetta_gap_ms")
                try:
                    if gap_ms is not None:
                        gap_seconds = float(gap_ms) / 1000.0
                        sign = "+" if gap_seconds >= 0 else "-"
                        value = abs(gap_seconds)
                        minutes = int(value // 60)
                        seconds = value - minutes * 60
                        item["etm_delta_raw"] = f"{sign}{minutes:02d}:{seconds:04.1f}".rstrip("0").rstrip(".")
                except (TypeError, ValueError):
                    pass
            # Stored NOT_PLAYED/EVENT_ERROR rows are useful for reconciliation
            # reasons, but the normal Played timeline/statistics must not count
            # them as emissions.
            if kind == "played" and not include_nonplayed and item.get("event_type") != "etm" and status_code not in ZETTA_PLAYED_STATUS_CODES:
                continue
        else:
            item["zetta_status_code"] = None
            item["zetta_status"] = ""
            item["zetta_edit_code"] = None
            item["zetta_edit_name"] = ""
            item["zetta_asset_id"] = ""
            item["etm_delta_raw"] = str(raw_fields[2]) if item.get("event_type") == "etm" and len(raw_fields) > 2 else ""
        out.append(item)
    if fallback_rows:
        _apply_zetta_metadata_fallback(out, fallback_rows)
    for item in out:
        if not str(item.get("category_code") or "").strip():
            item["category_code"] = _local_category_code(item)
    _annotate_played_lengths(out, d, kind)

    # Older imports may predate complete traffic-block classification. Reapply
    # the same-time grouping on read so users do not have to re-import files.
    _mark_traffic_groups(out)
    if hour is not None:
        # Filter by GSelector's scheduling hour, not normalized wall-clock time.
        # Thus 08:62:47 remains in the 08 hour as an explicit +02:47 overtime.
        out = [r for r in out if r.get("schedule_hour") == int(hour)]
    return out


def day_summary(kind: str, service_date: date | str, station_key: str = STATION_KEY) -> dict[str, Any]:
    rows = events_for_day(kind, service_date, station_key=station_key)
    counts = Counter(str(r.get("event_type") or "other") for r in rows)
    return {
        "events": len(rows),
        "songs": counts.get("song", 0),
        "jingles": counts.get("jingle", 0),
        "shows": counts.get("show", 0),
        "traffic": counts.get("traffic", 0),
        "event_counts": dict(counts),
    }


def song_stats(
    kind: str,
    start: date | str,
    end: date | str,
    *,
    station_key: str = STATION_KEY,
) -> list[dict[str, Any]]:
    s = start.isoformat() if isinstance(start, date) else str(start)
    e = end.isoformat() if isinstance(end, date) else str(end)
    if s > e:
        s, e = e, s
    db.init_db()
    with db.connect() as con:
        rows = con.execute(
            """SELECT service_date,sort_seconds,air_time_raw,artist,title,category,external_id,song_id,source_system
               FROM local_station_events
               WHERE station_key=? AND kind=? AND active=1 AND event_type='song'
                 AND service_date BETWEEN ? AND ?
                 AND (source_system<>'zetta2go' OR play_status_code IN (-3,2,3,6,7,8,9))
               ORDER BY service_date,sort_seconds,sequence_no""",
            (station_key, kind, s, e),
        ).fetchall()

    groups: dict[tuple[str, ...], dict[str, Any]] = {}
    for row in rows:
        external_id = str(row["external_id"] or "").strip()
        artist, title = str(row["artist"] or ""), str(row["title"] or "")
        if str(row["source_system"] or "") == "zetta2go":
            identity = ("song", str(int(row["song_id"]))) if row["song_id"] is not None else ("text", db.normalize(artist), db.normalize(title))
        else:
            identity = ("id", db.normalize(external_id)) if external_id else ("text", db.normalize(artist), db.normalize(title))
        item = groups.setdefault(identity, {
            "artist": artist,
            "title": title,
            "external_id": external_id,
            "song_id": row["song_id"],
            "plays": 0,
            "days": set(),
            "categories": Counter(),
            "first": None,
            "last": None,
            "hours": Counter(),
            "per_day": Counter(),
        })
        item["plays"] += 1
        day = str(row["service_date"])
        item["days"].add(day)
        item["per_day"][day] += 1
        cat = str(row["category"] or "")
        if cat:
            item["categories"][cat] += 1
        sec = row["sort_seconds"]
        raw_hour = _schedule_hour(str(row["air_time_raw"] or ""))
        if raw_hour is not None:
            item["hours"][raw_hour] += 1
        elif sec is not None:
            item["hours"][int(float(sec) // 3600) % 24] += 1
        stamp = (day, float(sec) if sec is not None else 999999.0)
        if item["first"] is None or stamp < item["first"]:
            item["first"] = stamp
        if item["last"] is None or stamp > item["last"]:
            item["last"] = stamp

    period_days = max(1, (date.fromisoformat(e) - date.fromisoformat(s)).days + 1)
    out: list[dict[str, Any]] = []
    for item in groups.values():
        peak_hour = item["hours"].most_common(1)[0][0] if item["hours"] else None
        top_category = item["categories"].most_common(1)[0][0] if item["categories"] else ""
        out.append({
            "artist": item["artist"],
            "title": item["title"],
            "category": top_category,
            "external_id": item["external_id"],
            "song_id": item["song_id"],
            "plays": int(item["plays"]),
            "days_with_play": len(item["days"]),
            "per_calendar_day": round(item["plays"] / period_days, 2),
            "avg_active_day": round(item["plays"] / max(1, len(item["days"])), 2),
            "max_day": max(item["per_day"].values()) if item["per_day"] else 0,
            "peak_hour": peak_hour,
        })
    out.sort(key=lambda r: (-int(r["plays"]), db.normalize(str(r["artist"])), db.normalize(str(r["title"]))))
    return out


def _identity_key(row: dict[str, Any], *, native_zetta_pair: bool = False) -> tuple[str, ...]:
    """Stable identity used inside one hourly reconciliation block.

    Zetta log-event GUIDs are perfect only when *both* comparison sides come
    from Zetta2GO.  For historical cutoffs imported from GSelector the GUID
    namespace does not exist on the Scheduled side, so matching must fall back
    to the symmetric artist/title identity.  The old code chose the GUID for
    every Zetta row independently, which made a GSelector-vs-Zetta day look like
    every single item had been deleted and re-added.
    """
    typ = str(row.get("event_type") or "other")
    if native_zetta_pair and str(row.get("source_system") or "") == "zetta2go":
        ext = str(row.get("external_id") or "").strip()
        if ext:
            return (typ, "zetta-event", ext.casefold())

    if typ == "song":
        # Text identity is intentionally used for cross-system reconciliation.
        # GSelector song IDs and Zetta GUIDs are unrelated namespaces, while the
        # normalized credit/title pair is shared by both exports.
        return (
            typ,
            "text",
            db.normalize(str(row.get("artist") or "")),
            db.normalize(str(row.get("title") or "")),
        )
    if typ == "etm":
        title = db.normalize(str(row.get("title") or ""))
        # Imported Zetta ETM titles are synthesized to the same MM:SS/type form
        # as GSelector. External IDs intentionally do not participate here.
        return (typ, "text", title)
    title = db.normalize(str(row.get("title") or ""))
    if title:
        return (typ, "text", title)
    category = db.normalize(str(row.get("category") or ""))
    ext = db.normalize(str(row.get("external_id") or ""))
    return (typ, "fallback", category, ext)


def _occurrence_tokens(
    rows: list[dict[str, Any]],
    *,
    native_zetta_pair: bool = False,
) -> tuple[list[tuple[Any, ...]], dict[tuple[Any, ...], dict[str, Any]]]:
    """Make duplicate-safe tokens: the second play of a song is a separate event."""
    seen: Counter[tuple[str, ...]] = Counter()
    tokens: list[tuple[Any, ...]] = []
    lookup: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        key = _identity_key(row, native_zetta_pair=native_zetta_pair)
        seen[key] += 1
        token: tuple[Any, ...] = (*key, "occ", int(seen[key]))
        tokens.append(token)
        lookup[token] = row
    return tokens, lookup


def _format_signed_delta(seconds: float | None) -> str:
    if seconds is None:
        return ""
    value = int(round(float(seconds)))
    sign = "+" if value >= 0 else "-"
    value = abs(value)
    minutes, secs = divmod(value, 60)
    return f"{sign}{minutes}:{secs:02d}"


def _fade_info(scheduled: dict[str, Any], played: dict[str, Any]) -> tuple[bool, float | None, str]:
    """Detect only a *meaningful* early cut of a song.

    A few seconds shorter runtime is normal in radio automation because of
    trim/segue/crossfade points.  Treat a song as cut only when the played
    runtime is at least 10% shorter *and* the missing part is at least 10 s.
    Zetta's FADE/STOPPED status is still useful evidence, but it does not by
    itself turn a normal crossfade into a comparison error.
    """
    if str(scheduled.get("event_type") or "") != "song":
        return False, None, ""

    text_parts = [
        str(played.get("edit_code") or ""),
        str(played.get("sound_code") or ""),
        str(played.get("extra_18") or ""),
        str(played.get("extra_19") or ""),
        str(played.get("extra_20") or ""),
        str(played.get("extra_21") or ""),
    ]
    edit_text = " ".join(text_parts).casefold()
    zetta_status = int(played.get("zetta_status_code") or 0)
    zetta_edit = int(played.get("zetta_edit_code") or 0)
    textual_fade = any(term in edit_text for term in ("fade", "faded", "ścięt", "sciet"))
    zetta_fade = zetta_status in {6, 7, 8} or zetta_edit == 217

    sr = scheduled.get("runtime_seconds")
    # Prefer the derived actual playout span (next aired start / live elapsed)
    # over Zetta's nominal RuntimeMilliseconds. This is what lets comparison
    # catch a song cut by 1/3 or 1/2 while ignoring normal few-second segues.
    pr = played.get("played_seconds")
    if pr is None:
        pr = played.get("runtime_seconds")
    cut: float | None = None
    significant = False
    try:
        planned = float(sr) if sr is not None else 0.0
        actual = float(pr) if pr is not None else 0.0
    except (TypeError, ValueError):
        planned = actual = 0.0
    if planned > 0 and actual >= 0:
        diff = planned - actual
        threshold = max(10.0, planned * 0.10)
        if diff >= threshold:
            cut = diff
            significant = True

    if not significant:
        return False, None, ""
    if zetta_fade:
        label = ZETTA_STATUS_NAMES.get(zetta_status, "")
        reason = played.get("zetta_edit_name") or label or "Zetta"
        return True, cut, f"{reason} · ucięto {round((cut / planned) * 100)}%"
    if textual_fade:
        return True, cut, f"Faded/ścięty wg danych playout · ucięto {round((cut / planned) * 100)}%"
    return True, cut, f"Ścięty o {_format_signed_delta(-cut).lstrip('-')} ({round((cut / planned) * 100)}% runtime)"


def _comparison_display_pairs(
    scheduled: list[dict[str, Any]],
    played: list[dict[str, Any]],
    sched_tokens: list[tuple[Any, int]],
    play_tokens: list[tuple[Any, int]],
    sched_lookup: dict[tuple[Any, int], dict[str, Any]],
    play_lookup: dict[tuple[Any, int], dict[str, Any]],
    common: set[tuple[Any, int]],
    schedule_status: dict[int, str],
    played_status: dict[int, str],
) -> list[dict[str, Any]]:
    """Build identity-aligned rows for the two-column visual comparison.

    Common events are displayed opposite the same event even after a reorder.
    Missing Scheduled events get a ghost copy on Played; Played-only additions
    get a ghost copy on Scheduled. Added events are inserted close to their
    real Played position where possible.
    """
    play_pos = {token: idx for idx, token in enumerate(play_tokens)}
    emitted_added: set[tuple[Any, int]] = set()
    pairs: list[dict[str, Any]] = []
    play_cursor = -1

    def add_played_only(token: tuple[Any, int]) -> None:
        if token in emitted_added or token in common:
            return
        prow = play_lookup[token]
        pid = int(prow["id"])
        pairs.append({
            "status": played_status.get(pid, "Dodane"),
            "scheduled_row": None,
            "played_row": prow,
        })
        emitted_added.add(token)

    for token in sched_tokens:
        srow = sched_lookup[token]
        sid = int(srow["id"])
        if token not in common:
            pairs.append({
                "status": schedule_status.get(sid, "Niezagrane"),
                "scheduled_row": srow,
                "played_row": None,
            })
            continue

        target = play_pos[token]
        if target > play_cursor:
            for ptoken in play_tokens[play_cursor + 1:target]:
                add_played_only(ptoken)
            play_cursor = target

        prow = play_lookup[token]
        pid = int(prow["id"])
        pairs.append({
            "status": schedule_status.get(sid, played_status.get(pid, "OK")),
            "scheduled_row": srow,
            "played_row": prow,
        })

    for token in play_tokens:
        add_played_only(token)
    return pairs


def _compare_hour_rows(
    service_date: date | str,
    hour: int,
    scheduled_all: list[dict[str, Any]],
    played_all: list[dict[str, Any]],
    *,
    include_technical: bool = False,
) -> dict[str, Any]:
    """Compare two already-loaded rows lists for one GSelector hour."""
    hour = int(hour)

    def relevant(row: dict[str, Any]) -> bool:
        event_type = str(row.get("event_type") or "")
        return include_technical or event_type not in {"command", "toh"}

    scheduled = [row for row in scheduled_all if relevant(row)]
    played = [row for row in played_all if relevant(row)]

    # Exact Zetta log-event GUIDs are meaningful only for Zetta-vs-Zetta.
    # Historical Scheduled data may still come from GSelector, while Played is
    # already sourced from Zetta2GO; in that mixed case use symmetric text
    # identity instead of declaring the whole hour deleted+added.
    native_zetta_pair = bool(scheduled and played) and all(
        str(row.get("source_system") or "") == "zetta2go"
        for row in [*scheduled, *played]
    )
    sched_tokens, sched_lookup = _occurrence_tokens(scheduled, native_zetta_pair=native_zetta_pair)
    play_tokens, play_lookup = _occurrence_tokens(played, native_zetta_pair=native_zetta_pair)
    common = set(sched_tokens) & set(play_tokens)

    # Added/missing events are removed before ranking, so they do not make all
    # following rows look reordered. Only true swaps/moves change common ranks.
    sched_common = [token for token in sched_tokens if token in common]
    play_common = [token for token in play_tokens if token in common]
    sched_rank = {token: idx for idx, token in enumerate(sched_common)}
    play_rank = {token: idx for idx, token in enumerate(play_common)}
    reordered = {token for token in common if sched_rank.get(token) != play_rank.get(token)}

    rows: list[dict[str, Any]] = []
    schedule_status: dict[int, str] = {}
    played_status: dict[int, str] = {}

    for token in sched_tokens:
        sched = sched_lookup[token]
        sid = int(sched["id"])
        if token not in common:
            schedule_status[sid] = "Niezagrane"
            rows.append({
                "status": "Niezagrane",
                "event_type": sched["event_type"],
                "category": sched["category"],
                "artist": sched["artist"],
                "title": sched["title"],
                "scheduled_time": sched["air_time_raw"],
                "played_time": "",
                "start_delta_seconds": None,
                "start_delta": "",
                "runtime_cut_seconds": None,
                "runtime_cut": "",
                "scheduled_position": int(sched.get("sequence_no") or 0) + 1,
                "played_position": None,
                "scheduled_id": sid,
                "played_id": None,
                "external_id": sched.get("external_id") or "",
                "note": "Nie ma odpowiadającego elementu w Played tej godziny.",
            })
            continue

        played_row = play_lookup[token]
        pid = int(played_row["id"])
        delta = None
        if sched.get("sort_seconds") is not None and played_row.get("sort_seconds") is not None:
            delta = float(played_row["sort_seconds"]) - float(sched["sort_seconds"])
        faded, cut_seconds, fade_note = _fade_info(sched, played_row)
        moved = token in reordered
        zetta_status = played_row.get("zetta_status_code")
        try:
            zetta_status = int(zetta_status) if zetta_status is not None else None
        except (TypeError, ValueError):
            zetta_status = None

        same_zetta_event = (
            str(sched.get("source_system") or "") == "zetta2go"
            and str(played_row.get("source_system") or "") == "zetta2go"
            and str(sched.get("external_id") or "")
            and str(sched.get("external_id") or "") == str(played_row.get("external_id") or "")
        )
        changed = False
        if same_zetta_event:
            sched_asset = str(sched.get("asset_id") or "")
            play_asset = str(played_row.get("asset_id") or "")
            changed = bool(sched_asset and play_asset and sched_asset != play_asset)
            changed = changed or db.normalize(str(sched.get("artist") or "")) != db.normalize(str(played_row.get("artist") or ""))
            changed = changed or db.normalize(str(sched.get("title") or "")) != db.normalize(str(played_row.get("title") or ""))

        status_note = fade_note
        if zetta_status in ZETTA_NONPLAYED_STATUS_CODES:
            status = "Niezagrane"
            reason = str(played_row.get("zetta_edit_name") or played_row.get("zetta_status") or "").strip()
            status_note = reason or "Zetta oznaczyła element jako niezagrany."
        elif changed:
            status = "Zmieniony + kolejność" if moved else "Zmieniony"
            reason = str(played_row.get("zetta_edit_name") or "").strip()
            status_note = reason or "Ten sam wpis logu ma po cutoff inny asset/tytuł."
        elif zetta_status in ZETTA_UPCOMING_STATUS_CODES:
            status = "Kolejność" if moved else "Oczekuje"
            status_note = str(played_row.get("zetta_status") or "")
        elif zetta_status in {-3, 2, 9}:
            if moved:
                status = "Kolejność + w trakcie"
            else:
                status = "W trakcie"
            status_note = str(played_row.get("zetta_status") or "")
        elif moved and faded:
            status = "Kolejność + ścięty"
        elif moved:
            status = "Kolejność"
        elif faded:
            status = "Ścięty"
        else:
            status = "OK"
        schedule_status[sid] = status
        played_status[pid] = status
        rows.append({
            "status": status,
            "event_type": sched["event_type"],
            "category": sched["category"],
            "artist": sched["artist"],
            "title": sched["title"],
            "scheduled_time": sched["air_time_raw"],
            "played_time": played_row["air_time_raw"],
            "start_delta_seconds": round(delta, 1) if delta is not None else None,
            "start_delta": _format_signed_delta(delta),
            "runtime_cut_seconds": round(cut_seconds, 1) if cut_seconds is not None else None,
            "runtime_cut": (_format_signed_delta(-cut_seconds) if cut_seconds is not None else ""),
            "scheduled_position": int(sched.get("sequence_no") or 0) + 1,
            "played_position": int(played_row.get("sequence_no") or 0) + 1,
            "scheduled_id": sid,
            "played_id": pid,
            "external_id": sched.get("external_id") or played_row.get("external_id") or "",
            "note": status_note,
        })

    for token in play_tokens:
        if token in common:
            continue
        row = play_lookup[token]
        pid = int(row["id"])
        played_status[pid] = "Dodane"
        rows.append({
            "status": "Dodane",
            "event_type": row["event_type"],
            "category": row["category"],
            "artist": row["artist"],
            "title": row["title"],
            "scheduled_time": "",
            "played_time": row["air_time_raw"],
            "start_delta_seconds": None,
            "start_delta": "",
            "runtime_cut_seconds": None,
            "runtime_cut": "",
            "scheduled_position": None,
            "played_position": int(row.get("sequence_no") or 0) + 1,
            "scheduled_id": None,
            "played_id": pid,
            "external_id": row.get("external_id") or "",
            "note": "Element pojawił się w Played, ale nie było go w Scheduled tej godziny.",
        })

    counts = Counter(row["status"] for row in rows)
    matched = sum(1 for row in rows if row["status"] not in {"Niezagrane", "Dodane"})
    reordered_count = sum(1 for row in rows if "kolejność" in row["status"].casefold())
    faded_count = sum(1 for row in rows if "ścięty" in row["status"].casefold())
    changed_count = sum(1 for row in rows if "zmieniony" in row["status"].casefold())
    differences = [row for row in rows if row["status"] not in {"OK", "Oczekuje", "W trakcie"}]
    display_pairs = _comparison_display_pairs(
        scheduled, played, sched_tokens, play_tokens, sched_lookup, play_lookup, common,
        schedule_status, played_status,
    )

    if played and all(str(row.get("source_system") or "") == "zetta2go" for row in played):
        played_actual = sum(
            1 for row in played
            if int(row.get("zetta_status_code") or 0) in ZETTA_PLAYED_STATUS_CODES
        )
    else:
        # Manual/GSelector Played imports are historical by definition.
        played_actual = len(played)

    return {
        "service_date": service_date.isoformat() if isinstance(service_date, date) else str(service_date),
        "hour": hour,
        "scheduled": len(scheduled),
        "played": len(played),
        "played_actual": played_actual,
        "matched": matched,
        "missed": counts.get("Niezagrane", 0),
        "added": counts.get("Dodane", 0),
        "reordered": reordered_count,
        "faded": faded_count,
        "changed": changed_count,
        "waiting": counts.get("Oczekuje", 0),
        "in_progress": counts.get("W trakcie", 0),
        "ok": counts.get("OK", 0),
        "differences": len(differences),
        "rows": rows,
        "difference_rows": differences,
        "scheduled_rows": scheduled,
        "played_rows": played,
        "schedule_status": schedule_status,
        "played_status": played_status,
        "display_pairs": display_pairs,
    }


def compare_hour(
    service_date: date | str,
    hour: int,
    station_key: str = STATION_KEY,
    *,
    include_technical: bool = False,
) -> dict[str, Any]:
    """Compare Scheduled vs Played inside one GSelector hour block.

    Time is not a matching criterion. Matching uses identity plus occurrence
    number, and order is evaluated only among events that exist on both sides.
    """
    hour = int(hour)
    if not 0 <= hour <= 23:
        raise ValueError("hour must be 0..23")

    scheduled = events_for_day("schedule", service_date, hour=hour, station_key=station_key)
    played = events_for_day("played", service_date, hour=hour, station_key=station_key, include_nonplayed=True)
    return _compare_hour_rows(
        service_date,
        hour,
        scheduled,
        played,
        include_technical=include_technical,
    )

def compare_day(
    service_date: date | str,
    station_key: str = STATION_KEY,
    *,
    include_hour_details: bool = False,
) -> dict[str, Any]:
    """Daily summary built from 24 independent hour blocks.

    Scheduled and Played are loaded once per day and then partitioned in memory.
    The old implementation reopened SQLite and decoded the full payload 48
    times (2 sides × 24 hours), which made the comparison tab needlessly slow.
    """
    scheduled_rows = events_for_day("schedule", service_date, station_key=station_key)
    played_rows = events_for_day("played", service_date, station_key=station_key, include_nonplayed=True)

    scheduled_by_hour: dict[int, list[dict[str, Any]]] = defaultdict(list)
    played_by_hour: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in scheduled_rows:
        hour = row.get("schedule_hour")
        if hour is not None:
            scheduled_by_hour[int(hour)].append(row)
    for row in played_rows:
        hour = row.get("schedule_hour")
        if hour is not None:
            played_by_hour[int(hour)].append(row)

    hourly = [
        _compare_hour_rows(
            service_date,
            hour,
            scheduled_by_hour.get(hour, []),
            played_by_hour.get(hour, []),
        )
        for hour in range(24)
    ]
    rows = [row for item in hourly for row in item["rows"]]
    result = {
        "service_date": service_date.isoformat() if isinstance(service_date, date) else str(service_date),
        "scheduled": sum(int(item["scheduled"]) for item in hourly),
        "played": sum(int(item["played"]) for item in hourly),
        "played_actual": sum(int(item.get("played_actual") or 0) for item in hourly),
        "matched": sum(int(item["matched"]) for item in hourly),
        "missed": sum(int(item["missed"]) for item in hourly),
        "added": sum(int(item["added"]) for item in hourly),
        "reordered": sum(int(item["reordered"]) for item in hourly),
        "faded": sum(int(item["faded"]) for item in hourly),
        "changed": sum(int(item.get("changed") or 0) for item in hourly),
        "waiting": sum(int(item.get("waiting") or 0) for item in hourly),
        "in_progress": sum(int(item.get("in_progress") or 0) for item in hourly),
        "on_time": sum(int(item["ok"]) for item in hourly),
        "avg_abs_delta_seconds": None,
        "rows": rows,
        "hours": [
            {
                "hour": int(item["hour"]),
                "scheduled": int(item["scheduled"]),
                "played": int(item["played"]),
                "played_actual": int(item.get("played_actual") or 0),
                "differences": int(item["differences"]),
                "missed": int(item["missed"]),
                "added": int(item["added"]),
                "reordered": int(item["reordered"]),
                "faded": int(item["faded"]),
                "changed": int(item.get("changed") or 0),
                "waiting": int(item.get("waiting") or 0),
                "in_progress": int(item.get("in_progress") or 0),
            }
            for item in hourly
        ],
    }
    if include_hour_details:
        result["hour_details"] = hourly
    return result


def delete_import(import_id: int, station_key: str = STATION_KEY) -> dict[str, Any]:
    """Delete one import and reactivate the previous snapshot for its days."""
    db.init_db()
    iid = int(import_id)
    with db.connect() as con:
        info = con.execute(
            """SELECT id,station_key,kind,source_name,date_from,date_to,row_count
               FROM local_station_imports WHERE id=? AND station_key=?""",
            (iid, station_key),
        ).fetchone()
        if not info:
            raise ValueError(f"Nie znaleziono importu #{iid} dla {station_key}.")
        affected_rows = con.execute(
            "SELECT DISTINCT service_date FROM local_station_events WHERE import_id=? ORDER BY service_date",
            (iid,),
        ).fetchall()
        affected_dates = [str(row["service_date"]) for row in affected_rows]
        kind = str(info["kind"])
        con.execute("DELETE FROM local_station_imports WHERE id=?", (iid,))

        restored = 0
        for service_date in affected_dates:
            con.execute(
                """UPDATE local_station_events SET active=0
                   WHERE station_key=? AND kind=? AND service_date=?""",
                (station_key, kind, service_date),
            )
            previous = con.execute(
                """SELECT e.import_id
                   FROM local_station_events e
                   JOIN local_station_imports i ON i.id=e.import_id
                   WHERE e.station_key=? AND e.kind=? AND e.service_date=?
                   ORDER BY i.imported_at DESC, i.id DESC LIMIT 1""",
                (station_key, kind, service_date),
            ).fetchone()
            if previous:
                con.execute(
                    """UPDATE local_station_events SET active=1
                       WHERE import_id=? AND service_date=?""",
                    (int(previous["import_id"]), service_date),
                )
                restored += 1

    return {
        "deleted_import_id": iid,
        "kind": kind,
        "source_name": str(info["source_name"]),
        "date_from": str(info["date_from"]),
        "date_to": str(info["date_to"]),
        "rows": int(info["row_count"]),
        "affected_days": len(affected_dates),
        "restored_days": restored,
    }


def ensure_song_links_current(station_key: str = STATION_KEY) -> dict[str, int]:
    """Relink previously unmatched EMAUS songs against current identities.

    The pass is intentionally cheap and repeatable (only NULL song_id rows are
    inspected), so newly-created RadioCharts songs and later alias merges can be
    picked up without re-importing the GSelector files.
    """
    db.init_db()
    with db.connect() as con:
        rows = con.execute(
            """SELECT id,artist,title FROM local_station_events
               WHERE station_key=? AND event_type='song' AND song_id IS NULL""",
            (station_key,),
        ).fetchall()
        linked = 0
        cache: dict[tuple[str, str], int | None] = {}
        for row in rows:
            artist, title = str(row["artist"] or ""), str(row["title"] or "")
            key = (db.normalize(artist), db.normalize(title))
            if key not in cache:
                cache[key] = _existing_song_id(con, artist, title)
            song_id = cache[key]
            if song_id is not None:
                con.execute("UPDATE local_station_events SET song_id=? WHERE id=?", (int(song_id), int(row["id"])))
                linked += 1
    return {"checked": len(rows), "linked": linked}


def song_activity(
    song_id: int,
    start: date | str | None = None,
    end: date | str | None = None,
    *,
    station_key: str = STATION_KEY,
) -> dict[str, Any]:
    """Scheduled/played EMAUS activity for one canonical RadioCharts song."""
    db.init_db()
    sid = int(song_id)
    with db.connect() as con:
        bounds = con.execute(
            """SELECT MIN(service_date) AS dmin, MAX(service_date) AS dmax
               FROM local_station_events
               WHERE station_key=? AND active=1 AND event_type='song' AND song_id=?
                 AND (kind<>'played' OR source_system<>'zetta2go' OR play_status_code IN (-3,2,3,6,7,8,9))""",
            (station_key, sid),
        ).fetchone()
        if not bounds or not bounds["dmin"]:
            return {"song_id": sid, "date_from": None, "date_to": None, "scheduled": 0, "played": 0, "daily": []}
        s = (start.isoformat() if isinstance(start, date) else str(start)) if start else str(bounds["dmin"])
        e = (end.isoformat() if isinstance(end, date) else str(end)) if end else str(bounds["dmax"])
        if s > e:
            s, e = e, s
        rows = con.execute(
            """SELECT kind,service_date,air_time_raw,sort_seconds,category
               FROM local_station_events
               WHERE station_key=? AND active=1 AND event_type='song' AND song_id=?
                 AND service_date BETWEEN ? AND ?
                 AND (kind<>'played' OR source_system<>'zetta2go' OR play_status_code IN (-3,2,3,6,7,8,9))
               ORDER BY service_date,sequence_no""",
            (station_key, sid, s, e),
        ).fetchall()

    daily_map: dict[str, dict[str, Any]] = {}
    scheduled_times: list[tuple[str, float, str]] = []
    played_times: list[tuple[str, float, str]] = []
    for row in rows:
        day = str(row["service_date"])
        item = daily_map.setdefault(day, {"date": day, "scheduled": 0, "played": 0})
        kind = str(row["kind"] or "")
        if kind in {"schedule", "played"}:
            item["scheduled" if kind == "schedule" else "played"] += 1
        sec = float(row["sort_seconds"]) if row["sort_seconds"] is not None else 999999.0
        stamp = (day, sec, str(row["air_time_raw"] or ""))
        if kind == "schedule":
            scheduled_times.append(stamp)
        elif kind == "played":
            played_times.append(stamp)

    today_iso = date.today().isoformat()
    future = [x for x in scheduled_times if x[0] >= today_iso]
    next_sched = min(future, default=None)
    last_played = max(played_times, default=None)
    period_days = max(1, (date.fromisoformat(e) - date.fromisoformat(s)).days + 1)
    played_count = len(played_times)
    return {
        "song_id": sid,
        "date_from": s,
        "date_to": e,
        "scheduled": len(scheduled_times),
        "played": played_count,
        "scheduled_days": sum(1 for x in daily_map.values() if x["scheduled"]),
        "played_days": sum(1 for x in daily_map.values() if x["played"]),
        "played_per_day": round(played_count / period_days, 2),
        "last_played": (f"{last_played[0]} {last_played[2]}" if last_played else None),
        "next_scheduled": (f"{next_sched[0]} {next_sched[2]}" if next_sched else None),
        "daily": [daily_map[k] for k in sorted(daily_map)],
    }

def ensure_seed_data() -> dict[str, Any]:
    """One-shot production seed for the files supplied with RadioCharts 1.2.0."""
    db.init_db()
    marker = "local_station_seed_20260930_v1"
    lock = FileLock(f"{db.DB_PATH}.local-station-seed.lock", timeout=60)
    with lock:
        # Web and API containers can start together. Re-check the marker inside
        # a cross-process lock so both cannot try to seed the same SQLite file.
        with db.connect() as con:
            row = con.execute("SELECT value FROM app_meta WHERE key=?", (marker,)).fetchone()
            if row:
                return {"seeded": False, "status": str(row["value"])}

        data_dir = Path(__file__).resolve().parent / "data"
        seed_specs = [
            (data_dir / "gselector_schedule_2026-09-30_2026-10-12.tsv", "schedule", date(2026, 9, 30)),
            (data_dir / "gselector_played_2026-09-28.tsv", "played", date(2026, 9, 28)),
        ]
        summaries: list[str] = []
        for path, kind, start in seed_specs:
            if not path.exists():
                summaries.append(f"{kind}:missing")
                continue
            result = import_gselector_export(
                path.read_bytes(), filename=path.name, kind=kind, start_date=start, source="seed-1.2.0"
            )
            summaries.append(f"{kind}:{result['rows']}rows/{result['days']}days")

        value = ";".join(summaries) or "missing"
        with db.connect() as con:
            con.execute("INSERT OR REPLACE INTO app_meta(key,value) VALUES(?,?)", (marker, value))
        return {"seeded": True, "status": value}
