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

STATION_KEY = "EMAUS"
LOCAL_KINDS = ("schedule", "played")
EVENT_TYPES = ("song", "jingle", "show", "bed", "info", "etm", "traffic", "command", "other")

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


def events_for_day(
    kind: str,
    service_date: date | str,
    *,
    hour: int | None = None,
    event_types: Iterable[str] | None = None,
    station_key: str = STATION_KEY,
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
                       runtime_raw,runtime_seconds,song_id,import_id,payload_json
                FROM local_station_events WHERE {' AND '.join(where)}
                ORDER BY sequence_no""",
            params,
        ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        try:
            raw_fields = json.loads(str(item.pop("payload_json") or "[]"))
            if not isinstance(raw_fields, list):
                raw_fields = []
        except Exception:
            raw_fields = []
        for key, _label, index in GSELECTOR_SONG_COLUMNS:
            item[key] = str(raw_fields[index]) if item.get("event_type") == "song" and len(raw_fields) > index else ""
        item["schedule_hour"] = _schedule_hour(str(item.get("air_time_raw") or ""))
        item["gap_seconds"] = _gap_overrun_seconds(str(item.get("air_time_raw") or ""))
        item["gap_raw"] = _format_gap(item["gap_seconds"])
        item["etm_delta_raw"] = str(raw_fields[2]) if item.get("event_type") == "etm" and len(raw_fields) > 2 else ""
        out.append(item)
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
            """SELECT service_date,sort_seconds,air_time_raw,artist,title,category,external_id,song_id
               FROM local_station_events
               WHERE station_key=? AND kind=? AND active=1 AND event_type='song'
                 AND service_date BETWEEN ? AND ?
               ORDER BY service_date,sort_seconds,sequence_no""",
            (station_key, kind, s, e),
        ).fetchall()

    groups: dict[tuple[str, ...], dict[str, Any]] = {}
    for row in rows:
        external_id = str(row["external_id"] or "").strip()
        artist, title = str(row["artist"] or ""), str(row["title"] or "")
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


def _identity_key(row: dict[str, Any]) -> tuple[str, ...]:
    """Stable identity used only inside one hourly reconciliation block."""
    ext = db.normalize(str(row.get("external_id") or ""))
    typ = str(row.get("event_type") or "other")
    if ext:
        return (typ, "id", ext)
    if typ == "song":
        song_id = row.get("song_id")
        if song_id is not None:
            return (typ, "song", str(int(song_id)))
        return (typ, "text", db.normalize(str(row.get("artist") or "")), db.normalize(str(row.get("title") or "")))
    return (typ, "text", db.normalize(str(row.get("category") or "")), db.normalize(str(row.get("title") or "")))


def _occurrence_tokens(rows: list[dict[str, Any]]) -> tuple[list[tuple[Any, ...]], dict[tuple[Any, ...], dict[str, Any]]]:
    """Make duplicate-safe tokens: the second play of a song is a separate event."""
    seen: Counter[tuple[str, ...]] = Counter()
    tokens: list[tuple[Any, ...]] = []
    lookup: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        key = _identity_key(row)
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
    """Detect a cut/fade only when the export gives us evidence for it."""
    text_parts = [
        str(played.get("edit_code") or ""),
        str(played.get("sound_code") or ""),
        str(played.get("extra_18") or ""),
        str(played.get("extra_19") or ""),
        str(played.get("extra_20") or ""),
        str(played.get("extra_21") or ""),
    ]
    edit_text = " ".join(text_parts).casefold()
    textual_fade = any(term in edit_text for term in ("fade", "faded", "ścięt", "sciet"))

    sr = scheduled.get("runtime_seconds")
    pr = played.get("runtime_seconds")
    cut = None
    if sr is not None and pr is not None:
        diff = float(sr) - float(pr)
        if diff > 5.0:
            cut = diff
    if textual_fade:
        return True, cut, "Faded/ścięty wg danych playout"
    if cut is not None:
        return True, cut, f"Ścięty o {_format_signed_delta(-cut).lstrip('-')} (runtime)"
    return False, None, ""


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
        return include_technical or str(row.get("event_type") or "") != "command"

    scheduled = [row for row in scheduled_all if relevant(row)]
    played = [row for row in played_all if relevant(row)]
    sched_tokens, sched_lookup = _occurrence_tokens(scheduled)
    play_tokens, play_lookup = _occurrence_tokens(played)
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
        if moved and faded:
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
            "note": fade_note,
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
    reordered_count = sum(1 for row in rows if "Kolejność" in row["status"])
    faded_count = sum(1 for row in rows if "ścięty" in row["status"].casefold())
    differences = [row for row in rows if row["status"] != "OK"]
    display_pairs = _comparison_display_pairs(
        scheduled, played, sched_tokens, play_tokens, sched_lookup, play_lookup, common,
        schedule_status, played_status,
    )

    return {
        "service_date": service_date.isoformat() if isinstance(service_date, date) else str(service_date),
        "hour": hour,
        "scheduled": len(scheduled),
        "played": len(played),
        "matched": matched,
        "missed": counts.get("Niezagrane", 0),
        "added": counts.get("Dodane", 0),
        "reordered": reordered_count,
        "faded": faded_count,
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
    played = events_for_day("played", service_date, hour=hour, station_key=station_key)
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
    played_rows = events_for_day("played", service_date, station_key=station_key)

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
        "matched": sum(int(item["matched"]) for item in hourly),
        "missed": sum(int(item["missed"]) for item in hourly),
        "added": sum(int(item["added"]) for item in hourly),
        "reordered": sum(int(item["reordered"]) for item in hourly),
        "faded": sum(int(item["faded"]) for item in hourly),
        "on_time": sum(int(item["ok"]) for item in hourly),
        "avg_abs_delta_seconds": None,
        "rows": rows,
        "hours": [
            {
                "hour": int(item["hour"]),
                "scheduled": int(item["scheduled"]),
                "played": int(item["played"]),
                "differences": int(item["differences"]),
                "missed": int(item["missed"]),
                "added": int(item["added"]),
                "reordered": int(item["reordered"]),
                "faded": int(item["faded"]),
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
               WHERE station_key=? AND active=1 AND event_type='song' AND song_id=?""",
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
