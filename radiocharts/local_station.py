from __future__ import annotations

import csv
import hashlib
import io
import json
import math
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
    if hour < 0 or second >= 120:
        return None, True
    # Some reconciled logs express an exact minute boundary as 59:60.0.
    # Treat that as a valid clock value instead of an anomaly; the raw label is
    # kept verbatim for display, while sorting/comparison uses normalized seconds.
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
    minute = int(m.group(2))
    second = float(m.group(3))
    if not 0 <= hour <= 23:
        return None
    # HH:59:60.0 is just the next-hour boundary written without carrying the
    # seconds. Normalize only this seconds-overflow form. Deliberate 60+ minute
    # scheduling (08:62:47 etc.) must stay assigned to the original hour.
    if minute < 60 and second >= 60:
        carried_hour = hour + int((minute * 60.0 + second) // 3600.0)
        if 0 <= carried_hour <= 23:
            return carried_hour
    return hour


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
    """Resolve an EMAUS credit through the shared RadioCharts identity layer.

    Exact matches/aliases stay fastest, then we deliberately reuse the same
    conservative matcher used by airplay + imported Baza.  This lets the radio
    library act as a bridge between Zetta/GSelector credits and the
    chart/airplay catalogue (radio edits, suffixes, credit variants, etc.).
    """
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
    if row:
        return int(row["canonical_song_id"])
    try:
        matched = db._match_song_id(con, artist, title)
    except Exception:
        matched = None
    if matched is not None:
        # Remember the exact EMAUS spelling so later snapshots no longer need
        # fuzzy matching.  It also survives future identity merges.
        try:
            con.execute(
                """INSERT INTO song_identity_aliases(artist_key,title_key,canonical_song_id,source,created_at)
                   VALUES(?,?,?,?,?)
                   ON CONFLICT(artist_key,title_key) DO UPDATE SET
                     canonical_song_id=excluded.canonical_song_id,source=excluded.source,created_at=excluded.created_at""",
                (akey, tkey, int(matched), "emaus", datetime.now(timezone.utc).isoformat()),
            )
        except Exception:
            pass
        return int(matched)
    return None




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


def _zetta_air_time_raw(actual: datetime | None) -> str:
    """Format native Zetta ``cell[5]`` AirTime without inventing 60+ time.

    Zetta already gives an absolute wall-clock timestamp for every playable,
    ETM and TOH row.  RadioCharts must use that value directly.  Earlier builds
    rewrote it relative to a locally tracked TOH group, which created values
    such as 10:60 and could make the list jump backwards several hours when a
    wide GetLog response contained helper groups out of order.
    """
    if actual is None:
        return ""
    second = actual.second + actual.microsecond / 1_000_000
    return f"{actual.hour:02d}:{actual.minute:02d}:{second:04.1f}"


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


def _zetta_gap_value_ms(raw: object) -> float | None:
    """Normalize one native Zetta CalculatedTimes gap value to milliseconds.

    Current GetLog responses use numeric millisecond values. Older Zetta builds
    can expose the same value as a numeric string, a TimeSpan-like string or a
    small object. This function only normalizes representation; it never derives
    a gap from airtimes, runtimes or neighbouring rows.
    """
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        value = float(raw)
        return value if math.isfinite(value) else None
    if isinstance(raw, dict):
        normalized = {re.sub(r"[^a-z0-9]", "", str(k).casefold()): v for k, v in raw.items()}
        for key in ("totalmilliseconds", "milliseconds", "millisecond", "value", "gap"):
            if key in normalized:
                value = _zetta_gap_value_ms(normalized[key])
                if value is not None:
                    return value
        return None

    text = str(raw).strip()
    if not text:
        return None
    try:
        value = float(text.replace(",", "."))
        return value if math.isfinite(value) else None
    except ValueError:
        pass

    # Accept signed MM:SS(.fff) and HH:MM:SS(.fff), as sometimes emitted by
    # older/custom Zetta serializers. The result is still only the supplied
    # native value converted to milliseconds.
    m = re.fullmatch(r"([+-])?(?:(\d+):)?(\d{1,2}):(\d{1,2}(?:[.,]\d+)?)", text)
    if not m:
        return None
    sign = -1.0 if m.group(1) == "-" else 1.0
    hours = int(m.group(2) or 0)
    minutes = int(m.group(3))
    seconds = float(m.group(4).replace(",", "."))
    if minutes >= 60 or seconds >= 60:
        return None
    return sign * (hours * 3600.0 + minutes * 60.0 + seconds) * 1000.0


def _zetta_calculated_field(calculated: dict[str, Any], *names: str) -> tuple[object | None, str]:
    if not isinstance(calculated, dict):
        return None, ""
    indexed = {
        re.sub(r"[^a-z0-9]", "", str(key).casefold()): (value, str(key))
        for key, value in calculated.items()
    }
    for name in names:
        key = re.sub(r"[^a-z0-9]", "", str(name).casefold())
        if key not in indexed:
            continue
        raw, actual_name = indexed[key]
        if raw in (None, ""):
            continue
        return raw, actual_name
    return None, ""


def _zetta_native_etm_gap(calculated: dict[str, Any], etm_type: str) -> tuple[float | None, str]:
    """Return the native ETM value from GetLog ``cell[16]`` CalculatedTimes.

    This is the same field family used by Emaus Hub. HIT markers prefer
    HitETMGap and then GapToETM; other ETMs prefer GapToETM. Missing native
    values remain missing; nothing is inferred from the surrounding timeline.
    """
    kind = str(etm_type or "").strip().casefold()
    if kind == "hit":
        candidates = (
            "HitETMGap", "GapToETM", "OriginalGap",
            "ETMGap", "Gap", "GapTime", "GapMilliseconds", "GapMs",
        )
    else:
        candidates = (
            "GapToETM", "OriginalGap",
            "ETMGap", "Gap", "GapTime", "GapMilliseconds", "GapMs",
        )
    for candidate in candidates:
        raw, actual_name = _zetta_calculated_field(calculated, candidate)
        if not actual_name:
            continue
        value = _zetta_gap_value_ms(raw)
        if value is not None:
            return value, actual_name
    return None, ""


def _zetta_marker_gap(asset: dict[str, Any], calculated: dict[str, Any], etm_type: str) -> tuple[float | None, str]:
    """Return only Zetta2GO's native ``cell[16]`` CalculatedTimes ETM value.

    This deliberately mirrors Emaus Hub.  ``Asset.gap``/``Asset.ogap`` from
    ``cell[7]`` are retained in the payload for diagnostics only; RadioCharts
    must not prefer them and must never derive a gap from airtimes, runtimes or
    neighbouring events.
    """
    fallback, field = _zetta_native_etm_gap(calculated, etm_type)
    if fallback is not None:
        return fallback, f"CalculatedTimes.{field}" if field else "CalculatedTimes"
    return None, ""


def _zetta_original_gap_ms(calculated: dict[str, Any], asset: dict[str, Any] | None = None) -> float | None:
    raw, _name = _zetta_calculated_field(calculated, "OriginalGap")
    return _zetta_gap_value_ms(raw)


def _format_signed_gap_ms(value_ms: object) -> str:
    try:
        if value_ms is None:
            return ""
        milliseconds = float(value_ms)
    except (TypeError, ValueError):
        return ""
    if not math.isfinite(milliseconds):
        return ""
    seconds_total = milliseconds / 1000.0
    sign = "+" if seconds_total >= 0 else "-"
    value = abs(seconds_total)
    minutes = int(value // 60)
    seconds = value - minutes * 60
    if abs(seconds - round(seconds)) < 0.0005:
        return f"{sign}{minutes:02d}:{int(round(seconds)):02d}"
    return f"{sign}{minutes:02d}:{seconds:04.1f}".rstrip("0").rstrip(".")


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
    seen_toh_times: set[str] = set()
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

        # Zetta ``cell[5]`` is the authoritative AirTime.  Do not derive the
        # clock from TOH grouping and do not manufacture 60+ minute notation.
        # The native request hour is kept in payload metadata for diagnostics.
        raw_asset = cell[7]
        asset = raw_asset if isinstance(raw_asset, dict) else {}
        raw_asset_label = str(raw_asset or "").strip() if not isinstance(raw_asset, dict) else ""
        unscheduled_match = re.match(r"^unscheduled\s+(song|link)\b", raw_asset_label, flags=re.IGNORECASE)
        unscheduled_kind = unscheduled_match.group(1).casefold() if unscheduled_match else ""
        calculated = cell[16] if len(cell) > 16 and isinstance(cell[16], dict) else {}
        row_id = str(source.get("id") or "")
        universal_id = str(asset.get("UniversalIdentifier") or "") if asset else ""
        source_event_id = universal_id or row_id

        if entry_type == 3:  # Top of Hour helper row
            etm_type = ""
            raw_time = _zetta_air_time_raw(actual)
            # GetLog can expose more than one helper TOH row for the same clock
            # boundary. Zetta Full renders one separator, so do the same.
            toh_key = str(cell[5] or raw_time)
            if toh_key in seen_toh_times:
                continue
            seen_toh_times.add(toh_key)
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
            raw_time = _zetta_air_time_raw(actual)
            minute = actual.minute if actual is not None else 0
            second = actual.second if actual is not None else 0
            title = f"ETM_{minute:02d}:{second:02d}_{etm_type}"
            gap_ms, gap_source = _zetta_marker_gap(asset, calculated, etm_type)
            gap_field = gap_source.removeprefix("CalculatedTimes.") if gap_source.startswith("CalculatedTimes.") else ""
            gap_seconds = gap_ms / 1000.0 if gap_ms is not None else None
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
            raw_time = _zetta_air_time_raw(actual)
            runtime_raw = str(asset.get("Runtime") or "").strip()
            try:
                runtime_seconds = float(cell[15]) / 1000.0 if cell[15] not in (None, "") else _parse_duration(runtime_raw)
            except (TypeError, ValueError):
                runtime_seconds = _parse_duration(runtime_raw)
            gap_seconds = None
        elif unscheduled_kind in {"song", "link"}:
            # GSelector/Zetta exposes empty clock positions as dedicated helper
            # rows (for example entry type 19 + cell[7] == "Unscheduled Link").
            # Keep those native rows so the ETM page can list their exact
            # AirTime. They are deliberately a separate technical event type:
            # normal Scheduled/Played presets and comparison ignore them.
            event_type = "unscheduled"
            artist = ""
            title = raw_asset_label or f"Unscheduled {unscheduled_kind.title()}"
            category = "UNSCHED"
            asset_id = ""
            sponsor = ""
            raw_time = _zetta_air_time_raw(actual)
            runtime_raw = ""
            runtime_seconds = 0.0
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
            "native_air_time": str(cell[5] or ""),
            "unscheduled_kind": unscheduled_kind if event_type == "unscheduled" else "",
            "unscheduled_label": raw_asset_label if event_type == "unscheduled" else "",
            "request_hour": source.get("_radiocharts_request_hour"),
            "request_index": source.get("_radiocharts_request_index"),
            "etm_context_probe": source.get("_radiocharts_etm_context_probe"),
            "base_calculated_times": source.get("_radiocharts_base_calculated_times"),
            "schedule_hour": actual.hour if actual is not None else _schedule_hour(raw_time),
            "raw_cell": cell,
            "raw_row": source,
            "valid_for_playback": bool(cell[3]) if len(cell) > 3 else None,
            "skip": bool(cell[11]) if len(cell) > 11 else False,
            "fixed": bool(cell[12]) if len(cell) > 12 else False,
            "stretch": cell[13] if len(cell) > 13 else None,
            "calculated_times": calculated,
            "zetta_gap_ms": gap_ms if entry_type == 15 else None,
            "zetta_gap_native_ms": gap_ms if entry_type == 15 else None,
            "zetta_gap_source": gap_source if entry_type == 15 else "",
            "zetta_gap_field": gap_field if entry_type == 15 else "",
            "zetta_original_gap_ms": _zetta_original_gap_ms(calculated, asset) if entry_type == 15 else None,
            # Keep cell[7] values only for diagnostics. Displayed ETM gaps come
            # exclusively from cell[16] / CalculatedTimes, like Emaus Hub.
            "zetta_asset_gap_ms": asset.get("gap") if entry_type == 15 else None,
            "zetta_asset_original_gap_ms": asset.get("ogap") if entry_type == 15 else None,
            **(_zetta_asset_metadata(asset) if entry_type == 106 else {}),
        }
        out.append({
            "line_no": source_index,
            "sequence_no": len(out),
            "air_time_raw": raw_time,
            "air_seconds": air_seconds,
            "sort_seconds": air_seconds,
            "schedule_hour": actual.hour if actual is not None else _schedule_hour(raw_time),
            # For Zetta rows gap is a native ETM datum, never an overrun derived
            # from the formatted clock. Non-ETM rows therefore have no gap.
            "gap_seconds": (gap_ms / 1000.0) if entry_type == 15 and gap_ms is not None else None,
            "gap_raw": _format_signed_gap_ms(gap_ms) if entry_type == 15 else "",
            "etm_delta_raw": _format_signed_gap_ms(gap_ms) if entry_type == 15 else "",
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
    # ETM gaps are intentionally left exactly as Zetta2GO supplied them in
    # cell[16] / CalculatedTimes. Do not infer hour-boundary carry or rebuild
    # RESET behaviour from the surrounding timeline. Missing native value = —.
    return out


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
    """Expose only native Zetta playout/runtime values.

    Older RadioCharts builds estimated playout length from the next event start
    and from the wall clock.  That was useful as a heuristic, but it also made
    comparison/fade results depend on locally reconstructed timing.  For Zetta
    rows we now keep the data model deliberately simple: completed/fade/stopped
    events use GetLog ``cell[15]`` RuntimeMilliseconds (already stored as
    ``runtime_seconds``); CURRENT/PAUSED progress is calculated only for the
    transient UI progress bar and is not persisted as a playout fact.
    """
    if kind != "played":
        return
    for row in rows:
        if str(row.get("source_system") or "") != "zetta2go":
            continue
        try:
            status = int(row.get("zetta_status_code") or 0)
        except (TypeError, ValueError):
            status = 0
        actual: float | None = None
        if status in {3, 6, 7, 8, -3}:
            try:
                value = float(row.get("runtime_seconds")) if row.get("runtime_seconds") is not None else None
            except (TypeError, ValueError):
                value = None
            if value is not None and value >= 0:
                actual = value
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
        if str(item.get("source_system") or "") == "zetta2go":
            try:
                item["schedule_hour"] = int(meta.get("schedule_hour")) if meta.get("schedule_hour") is not None else _schedule_hour(str(item.get("air_time_raw") or ""))
            except (TypeError, ValueError):
                item["schedule_hour"] = _schedule_hour(str(item.get("air_time_raw") or ""))
            # Never reinterpret a Zetta clock label as a locally calculated gap.
            item["gap_seconds"] = None
            item["gap_raw"] = ""
        else:
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
            item["zetta_request_hour"] = meta.get("request_hour")
            item["zetta_request_index"] = meta.get("request_index")
            item["zetta_etm_context_probe"] = meta.get("etm_context_probe")
            item["play_rate_tooltip"] = str(meta.get("play_rate_tooltip") or "")
            item["duration_runtime"] = str(meta.get("duration_runtime") or "")
            item["zetta_skip"] = bool(meta.get("skip"))
            item["zetta_fixed"] = bool(meta.get("fixed"))
            item["zetta_valid_for_playback"] = meta.get("valid_for_playback")
            # Re-read the native ETM value on every display from GetLog
            # cell[16] / CalculatedTimes.  cell[7] gap/ogap are diagnostics only.
            # This also repairs snapshots imported by older RadioCharts versions.
            calculated = meta.get("calculated_times") if isinstance(meta.get("calculated_times"), dict) else {}
            if item.get("event_type") == "etm":
                marker_asset = {
                    "gap": meta.get("zetta_asset_gap_ms"),
                    "ogap": meta.get("zetta_asset_original_gap_ms"),
                }
                native_gap_ms, native_gap_source = _zetta_marker_gap(
                    marker_asset, calculated, str(meta.get("etm_type") or "")
                )
                native_gap_field = (
                    native_gap_source.removeprefix("CalculatedTimes.")
                    if native_gap_source.startswith("CalculatedTimes.") else ""
                )
                item["zetta_gap_ms"] = native_gap_ms
                item["zetta_gap_native_ms"] = native_gap_ms
                item["zetta_gap_source"] = native_gap_source or "Zetta: brak"
                item["zetta_gap_field"] = native_gap_field
                item["zetta_original_gap_ms"] = _zetta_original_gap_ms(calculated, marker_asset)
            else:
                item["zetta_gap_ms"] = None
                item["zetta_gap_native_ms"] = None
                item["zetta_gap_source"] = ""
                item["zetta_gap_field"] = ""
                item["zetta_original_gap_ms"] = None
            item["zetta_reset_local_gap_ms"] = None
            item["zetta_gap_ignore_resets_ms"] = None
            item["zetta_gap_ignore_resets_carry_ms"] = None
            item["zetta_gap_ignore_resets_reset_count"] = 0
            item["payload"] = meta
            item["mood"] = str(meta.get("mood") or "")
            item["opener"] = str(meta.get("opener") or "")
            item["texture_open"] = str(meta.get("texture_open") or "")
            item["texture_close"] = str(meta.get("texture_close") or "")
            item["category_code"] = str(meta.get("category_code") or "")
            item["etm_delta_raw"] = _format_signed_gap_ms(item.get("zetta_gap_ms")) if item.get("event_type") == "etm" else ""
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


def _identity_key(
    row: dict[str, Any],
    *,
    shared_zetta_external_ids: set[str] | None = None,
    shared_zetta_asset_ids: set[str] | None = None,
) -> tuple[str, ...]:
    """Stable identity used inside one hourly reconciliation block.

    A Zetta log-event GUID is the strongest identity *only when that same GUID
    exists on both snapshots*.  In practice the first item of an hour and some
    rebuilt log rows can receive a different GUID between cutoff and live even
    though artist/title/asset are unchanged.  Treating every Zetta GUID as
    mandatory produced the absurd ``Niezagrane`` + ``Dodane`` pair for the same
    visible song.

    We therefore use a shared GUID when available (so a replacement with the
    same log-event id can still be reported as ``Zmieniony``), and otherwise
    fall back symmetrically to the semantic identity used cross-system.
    """
    typ = str(row.get("event_type") or "other")
    if str(row.get("source_system") or "") == "zetta2go":
        ext = str(row.get("external_id") or "").strip().casefold()
        if ext and ext in (shared_zetta_external_ids or set()):
            return (typ, "zetta-event", ext)

    # Songs intentionally keep semantic artist/title identity so a historical
    # GSelector cutoff still matches the same song in Zetta Played. A changed
    # Zetta log GUID for the first song of an hour therefore does not create a
    # false missing+added pair.
    if typ == "song":
        return (
            typ,
            "text",
            db.normalize(str(row.get("artist") or "")),
            db.normalize(str(row.get("title") or "")),
        )

    if str(row.get("source_system") or "") == "zetta2go":
        # For links/jingles/traffic, AssetID is the strongest native fallback
        # when a log-event GUID was regenerated between cutoff and live.
        asset = str(row.get("asset_id") or row.get("zetta_asset_id") or "").strip().casefold()
        if asset and asset in (shared_zetta_asset_ids or set()):
            return (typ, "zetta-asset", asset)
    if typ == "etm":
        title = db.normalize(str(row.get("title") or ""))
        return (typ, "text", title)
    title = db.normalize(str(row.get("title") or ""))
    if title:
        return (typ, "text", title)
    category = db.normalize(str(row.get("category") or ""))
    ext = db.normalize(str(row.get("external_id") or ""))
    return (typ, "fallback", category, ext)


def _shared_zetta_external_ids(
    scheduled: list[dict[str, Any]],
    played: list[dict[str, Any]],
) -> set[str]:
    def ids(rows: list[dict[str, Any]]) -> set[str]:
        return {
            str(row.get("external_id") or "").strip().casefold()
            for row in rows
            if str(row.get("source_system") or "") == "zetta2go"
            and str(row.get("external_id") or "").strip()
        }
    return ids(scheduled) & ids(played)




def _shared_zetta_asset_ids(
    scheduled: list[dict[str, Any]],
    played: list[dict[str, Any]],
) -> set[str]:
    """Asset IDs safe to use symmetrically on both sides of reconciliation.

    Older immutable cutoff snapshots may not have an AssetID even when the live
    Zetta row does.  Using an AssetID on only one side makes two visibly
    identical links/jingles impossible to match.  Just like log-event GUIDs,
    AssetID is therefore authoritative only when it is actually present in both
    snapshots.
    """
    def ids(rows: list[dict[str, Any]]) -> set[str]:
        return {
            str(row.get("asset_id") or row.get("zetta_asset_id") or "").strip().casefold()
            for row in rows
            if str(row.get("source_system") or "") == "zetta2go"
            and str(row.get("asset_id") or row.get("zetta_asset_id") or "").strip()
        }
    return ids(scheduled) & ids(played)

def _occurrence_tokens(
    rows: list[dict[str, Any]],
    *,
    shared_zetta_external_ids: set[str] | None = None,
    shared_zetta_asset_ids: set[str] | None = None,
) -> tuple[list[tuple[Any, ...]], dict[tuple[Any, ...], dict[str, Any]]]:
    """Make duplicate-safe tokens: the second play of a song is a separate event."""
    seen: Counter[tuple[str, ...]] = Counter()
    tokens: list[tuple[Any, ...]] = []
    lookup: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        key = _identity_key(
            row,
            shared_zetta_external_ids=shared_zetta_external_ids,
            shared_zetta_asset_ids=shared_zetta_asset_ids,
        )
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


ZETTA_SKIP_EDIT_CODES = {102, 202, 221, 506}


def _zetta_row_is_skipped(row: dict[str, Any]) -> bool:
    if bool(row.get("zetta_skip")):
        return True
    try:
        edit_code = int(row.get("zetta_edit_code") or row.get("edit_code_int") or 0)
    except (TypeError, ValueError):
        edit_code = 0
    return edit_code in ZETTA_SKIP_EDIT_CODES


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
    # When order really changed, identity-aligning rows makes the right column
    # look as if nothing moved (Miley remains opposite Miley, Robbie opposite
    # Robbie). In that case preserve the real sequence independently on both
    # sides; the per-side status markers explain which rows moved.
    has_reorder = any("kolejność" in str(value).casefold() for value in [*schedule_status.values(), *played_status.values()])
    if has_reorder:
        size = max(len(scheduled), len(played))
        return [
            {
                "status": "Kolejność",
                "scheduled_row": scheduled[idx] if idx < len(scheduled) else None,
                "played_row": played[idx] if idx < len(played) else None,
            }
            for idx in range(size)
        ]

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


def _comparison_row_is_future(row: dict[str, Any], service_date: date | str) -> bool:
    """Whether a Scheduled row is still in the future at comparison time.

    This is only a presentation/reconciliation state.  It never changes Zetta
    data or derives playout facts.  A future Scheduled item that is not yet
    present in the live response must not be called ``Niezagrane``.
    """
    d = service_date if isinstance(service_date, date) else date.fromisoformat(str(service_date))
    today = date.today()
    if d > today:
        return True
    if d < today:
        return False
    try:
        seconds = float(row.get("sort_seconds"))
    except (TypeError, ValueError):
        return False
    now = datetime.now().astimezone()
    wall = now.hour * 3600.0 + now.minute * 60.0 + now.second + now.microsecond / 1_000_000.0
    return seconds > wall


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
        return include_technical or event_type not in {"command", "toh", "unscheduled"}

    scheduled = [row for row in scheduled_all if relevant(row)]
    played = [row for row in played_all if relevant(row)]

    # Use a Zetta log-event GUID only when the same GUID exists on both sides.
    # Otherwise fall back to semantic identity.  This avoids false
    # missing+added pairs for the same visible first item of an hour when Zetta
    # rebuilt that row and changed its GUID between cutoff and live.
    shared_external_ids = _shared_zetta_external_ids(scheduled, played)
    shared_asset_ids = _shared_zetta_asset_ids(scheduled, played)
    sched_tokens, sched_lookup = _occurrence_tokens(
        scheduled,
        shared_zetta_external_ids=shared_external_ids,
        shared_zetta_asset_ids=shared_asset_ids,
    )
    play_tokens, play_lookup = _occurrence_tokens(
        played,
        shared_zetta_external_ids=shared_external_ids,
        shared_zetta_asset_ids=shared_asset_ids,
    )
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
            if _comparison_row_is_future(sched, service_date):
                missing_status = "Oczekuje"
                missing_note = "Przyszły element Scheduled — nie oznaczamy go jako niezagrany przed emisją."
            else:
                missing_status = "Wyskipowane" if _zetta_row_is_skipped(sched) else "Niezagrane"
                missing_note = "Nie ma odpowiadającego elementu w Played tej godziny."
            schedule_status[sid] = missing_status
            rows.append({
                "status": missing_status,
                "event_type": sched["event_type"],
                "category": sched["category"],
                "artist": sched["artist"],
                "title": sched["title"],
                "song_id": sched.get("song_id"),
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
                "note": missing_note,
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
            status = "Wyskipowane" if _zetta_row_is_skipped(played_row) else "Niezagrane"
            reason = str(played_row.get("zetta_edit_name") or played_row.get("zetta_status") or "").strip()
            status_note = reason or ("Element został celowo wyskipowany." if status == "Wyskipowane" else "Zetta oznaczyła element jako niezagrany.")
        elif changed:
            status = "Zmieniony + kolejność" if moved else "Zmieniony"
            reason = str(played_row.get("zetta_edit_name") or "").strip()
            status_note = reason or "Ten sam wpis logu ma po cutoff inny asset/tytuł."
        elif zetta_status in ZETTA_UPCOMING_STATUS_CODES:
            status = "Kolejność" if moved else "Oczekuje"
            status_note = str(played_row.get("zetta_status") or "")
        elif zetta_status in {2, 9}:
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
            "song_id": sched.get("song_id") or played_row.get("song_id"),
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
            "song_id": row.get("song_id"),
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
    matched = sum(1 for row in rows if row["status"] not in {"Niezagrane", "Wyskipowane", "Dodane"})
    reordered_count = sum(1 for row in rows if "kolejność" in row["status"].casefold())
    faded_count = sum(1 for row in rows if "ścięty" in row["status"].casefold())
    changed_count = sum(1 for row in rows if "zmieniony" in row["status"].casefold())
    differences = [row for row in rows if row["status"] not in {"OK", "Oczekuje", "W trakcie"}]
    display_pairs = _comparison_display_pairs(
        scheduled, played, sched_tokens, play_tokens, sched_lookup, play_lookup, common,
        schedule_status, played_status,
    )
    detail_by_scheduled = {int(row["scheduled_id"]): row for row in rows if row.get("scheduled_id") is not None}
    detail_by_played = {int(row["played_id"]): row for row in rows if row.get("played_id") is not None}
    for pair in display_pairs:
        srow = pair.get("scheduled_row") if isinstance(pair.get("scheduled_row"), dict) else None
        prow = pair.get("played_row") if isinstance(pair.get("played_row"), dict) else None
        sid = int(srow["id"]) if srow is not None and srow.get("id") is not None else None
        pid = int(prow["id"]) if prow is not None and prow.get("id") is not None else None
        pair["scheduled_status"] = schedule_status.get(sid, "OK") if sid is not None else ""
        pair["played_status"] = played_status.get(pid, "OK") if pid is not None else ""
        detail = detail_by_played.get(pid) if pid is not None else None
        if detail is None and sid is not None:
            detail = detail_by_scheduled.get(sid)
        pair["runtime_cut"] = str((detail or {}).get("runtime_cut") or "")
        pair["runtime_cut_seconds"] = (detail or {}).get("runtime_cut_seconds")

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
        "missed": counts.get("Niezagrane", 0) + counts.get("Wyskipowane", 0),
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

    # Soft ETMs are *soft*: the item belonging to the next clock hour may start
    # a little before HH:00 (for example Scheduled 02:00:00, Played 01:59:59.5).
    # Comparing rigid hour buckets then creates the familiar false pair
    # Niezagrane + Dodane even though it is visibly the same event.  The older
    # fix only handled a unique identity within five seconds of the boundary;
    # that still failed when the same song/link occurred elsewhere in the
    # neighbouring hour.  Use the nearest matching Scheduled occurrence around
    # the boundary instead.  This changes *comparison grouping only*: native
    # Zetta AirTime and stored schedule_hour are never rewritten.
    shared_external_ids = _shared_zetta_external_ids(scheduled_rows, played_rows)
    shared_asset_ids = _shared_zetta_asset_ids(scheduled_rows, played_rows)

    def boundary_identity(row: dict[str, Any]) -> tuple[str, ...]:
        if str(row.get("event_type") or "") == "etm":
            payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
            kind = str(payload.get("etm_type") or "").strip().casefold()
            if not kind:
                title = str(row.get("title") or "")
                match = re.search(r"_(Hard|Soft|Reset|Hit|Other)$", title, flags=re.IGNORECASE)
                kind = match.group(1).casefold() if match else "etm"
            return ("etm-boundary", kind)
        return _identity_key(
            row,
            shared_zetta_external_ids=shared_external_ids,
            shared_zetta_asset_ids=shared_asset_ids,
        )

    scheduled_identity_rows: dict[tuple[str, ...], list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    for sched in scheduled_rows:
        sched_hour = sched.get("schedule_hour")
        if sched_hour is None:
            continue
        scheduled_identity_rows[boundary_identity(sched)].append((int(sched_hour), sched))

    def clock_distance(a: float, b: float) -> float:
        raw = abs(a - b)
        return min(raw, abs(86400.0 - raw))

    boundary_tolerance = 180.0
    for row in played_rows:
        hour = row.get("schedule_hour")
        if hour is None:
            continue
        target_hour = int(hour)
        try:
            played_sec = float(row.get("sort_seconds"))
        except (TypeError, ValueError):
            played_sec = None

        if played_sec is not None:
            candidates = scheduled_identity_rows.get(boundary_identity(row), [])
            same_hour_best: float | None = None
            adjacent_best: tuple[float, int] | None = None
            for candidate_hour, candidate_row in candidates:
                try:
                    scheduled_sec = float(candidate_row.get("sort_seconds"))
                except (TypeError, ValueError):
                    continue
                distance = clock_distance(played_sec, scheduled_sec)
                if candidate_hour == target_hour:
                    same_hour_best = distance if same_hour_best is None else min(same_hour_best, distance)
                    continue
                hour_gap = abs(candidate_hour - target_hour)
                adjacent = hour_gap == 1 or {candidate_hour, target_hour} == {0, 23}
                if not adjacent or distance > boundary_tolerance:
                    continue
                if adjacent_best is None or distance < adjacent_best[0]:
                    adjacent_best = (distance, candidate_hour)

            # Prefer the adjacent occurrence only when it is the clearly nearest
            # one.  This handles Soft-ETM spill across HH:00 without stealing a
            # repeated title that genuinely belongs to the current hour.
            if adjacent_best is not None and (same_hour_best is None or adjacent_best[0] + 0.25 < same_hour_best):
                target_hour = adjacent_best[1]

        played_by_hour[target_hour].append(row)

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
    """Relink EMAUS songs through the shared catalogue and create missing stubs.

    Existing chart/airplay/Baza identities are preferred (including conservative
    aliases).  A genuinely new Zetta-only song gets a shared ``songs`` row so
    it is still clickable from Schedule.  When that recording later appears in
    charts/airplay, the normal identity merge can consolidate it without losing
    the local-station history.
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
            if song_id is None and artist.strip() and title.strip():
                try:
                    song_id = db.get_or_create_song(con, artist, title)
                    cache[key] = song_id
                except Exception:
                    song_id = None
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
