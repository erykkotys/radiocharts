from __future__ import annotations

import hashlib
import re
import time
from datetime import datetime
from io import BytesIO, StringIO

import pandas as pd
import requests
from bs4 import BeautifulSoup

from radiocharts.sources.browser import download_by_text, render_page

URLS = {
    "OLIA": "https://www.olis.pl/charts/oficjalna-lista-airplay",
    "OLIS": "https://www.olis.pl/charts/oficjalna-lista-sprzedazy/single-w-streamie",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

DATE_RANGE_RE = re.compile(r"(\d{2}\.\d{2}\.\d{4})\s+(\d{2}\.\d{2}\.\d{4})")
INT_RE = re.compile(r"^\d{1,3}$")

NOISE = {
    "bez zmian na liście", "bez zmian na liscie", "nowość", "nowosc", "wzrost", "spadek",
    "pozycja", "okładka", "okladka", "wykonawca", "tytuł", "tytul", "wydawca/dystrybutor",
    "wydawca / dystrybutor", "wydawca", "dystrybutor", "informacje", "x",
}


def _norm(value: object) -> str:
    s = str(value).strip().lower()
    s = s.replace("ł", "l").replace("ó", "o").replace("ą", "a").replace("ę", "e")
    s = s.replace("ś", "s").replace("ć", "c").replace("ń", "n").replace("ż", "z").replace("ź", "z")
    return re.sub(r"\s+", " ", s)


def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = [" ".join(str(x) for x in col if str(x) != "nan").strip() for col in df.columns]
    return df


def _find_col(columns, needles: tuple[str, ...]):
    for col in columns:
        n = _norm(col)
        if any(needle in n for needle in needles):
            return col
    return None


def _parse_date_range(text: str) -> tuple[str, str]:
    m = DATE_RANGE_RE.search(re.sub(r"\s+", " ", text))
    if not m:
        raise ValueError("Nie znaleziono zakresu dat OLiA/OLiS")
    start = datetime.strptime(m.group(1), "%d.%m.%Y").date().isoformat()
    end = datetime.strptime(m.group(2), "%d.%m.%Y").date().isoformat()
    return start, end


def _extract_reported_info(raw: object) -> tuple[int | None, int | None]:
    text = re.sub(r"\s+", " ", str(raw))
    weeks = peak = None
    mw = re.search(r"TYGODNIE\s+NA\s+DANEJ\s+LI[ŚS]CIE\s*(\d+)", text, re.I)
    mp = re.search(r"NAJWY[ŻZ]SZA\s+POZYCJA\s+NA\s+LI[ŚS]CIE\s*(\d+)", text, re.I)
    if mw:
        weeks = int(mw.group(1))
    if mp:
        peak = int(mp.group(1))
    return weeks, peak


def _parse_table(html: str) -> list[dict]:
    """Fallback for a future/static table version of the site."""
    try:
        tables = pd.read_html(StringIO(html))
    except (ValueError, ImportError):
        return []

    for table in tables:
        table = _flatten_columns(table)
        pos_col = _find_col(table.columns, ("pozycja", "miejsce", "position", "rank"))
        title_col = _find_col(table.columns, ("tytul", "tytuł", "title"))
        artist_col = _find_col(table.columns, ("wykonawca", "artist"))
        if pos_col is None or title_col is None or artist_col is None:
            continue
        info_col = _find_col(table.columns, ("informacje", "info"))
        entries = []
        for _, row in table.iterrows():
            m = re.search(r"\b(\d{1,3})\b", str(row.get(pos_col, "")))
            if not m:
                continue
            pos = int(m.group(1))
            if not 1 <= pos <= 100:
                continue
            title = str(row.get(title_col, "")).strip()
            artist = str(row.get(artist_col, "")).strip()
            if not title or title.lower() == "nan" or not artist or artist.lower() == "nan":
                continue
            entry = {"position": pos, "artist": artist, "title": title}
            if info_col is not None:
                weeks, peak = _extract_reported_info(row.get(info_col, ""))
                if weeks is not None:
                    entry["reported_weeks"] = weeks
                if peak is not None:
                    entry["reported_peak"] = peak
            entries.append(entry)
        if len(entries) >= 10:
            by_pos = {e["position"]: e for e in entries}
            return [by_pos[p] for p in sorted(by_pos)]
    return []


def _lines(text: str) -> list[str]:
    return [re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip()]


def _is_int(line: str) -> bool:
    return bool(INT_RE.fullmatch(line.strip()))


def _is_chart_position(lines: list[str], idx: int, expected: int) -> bool:
    """Detect the *current* rank, not one of the numeric metadata values.

    The rendered OLiA/OLiS cards are effectively:
      rank, title, artist, publisher(s), [previous rank], weeks, peak

    All metadata labels are hidden in the body's innerText, so the reliable
    distinction is that a real current rank is followed by a textual title.
    Metadata numbers are followed by another number until the next card.
    """
    if idx < 0 or idx >= len(lines) or lines[idx] != str(expected):
        return False
    if idx + 1 >= len(lines):
        return False
    nxt = lines[idx + 1].strip()
    if _is_int(nxt):
        return False
    n = _norm(nxt)
    if n in NOISE or n.startswith("tydzien ") or DATE_RANGE_RE.search(nxt):
        return False
    if nxt in {"<", ">"}:
        return False
    return True


def _chart_start(lines: list[str]) -> int:
    # The most stable anchor in the rendered body is "Tydzień NN".
    for i, line in enumerate(lines):
        if re.fullmatch(r"Tydzień\s+\d+", line, re.I):
            return i + 1
    # Fallback to the current date-range controls.
    for i in range(len(lines)):
        if DATE_RANGE_RE.search(" ".join(lines[i : i + 2])):
            return i + 1
    return 0


def _find_markers(lines: list[str], max_position: int = 100) -> list[tuple[int, int]]:
    markers: list[tuple[int, int]] = []
    cursor = _chart_start(lines)
    for expected in range(1, max_position + 1):
        found = None
        for i in range(cursor, len(lines)):
            if _is_chart_position(lines, i, expected):
                found = i
                break
        if found is None:
            break
        markers.append((expected, found))
        cursor = found + 1
    return markers


def _parse_card(pos: int, block: list[str]) -> dict | None:
    """Parse one rendered OLiA/OLiS card from lines between rank markers."""
    cleaned: list[str] = []
    for raw in block:
        line = raw.strip()
        n = _norm(line)
        if not line or n in NOISE:
            continue
        if n.startswith("bez zmian") or n.startswith("nowosc") or n.startswith("wzrost") or n.startswith("spadek"):
            continue
        if re.fullmatch(r"[▲▼△▽+\-–—]+(?:\s*\d+)?", line):
            continue
        cleaned.append(line)

    # The first two textual values are consistently title and artist on the
    # live site. Publisher/distributor text follows them.
    text_values = [x for x in cleaned if not _is_int(x)]
    if len(text_values) < 2:
        return None
    title, artist = text_values[0], text_values[1]

    # At the end of the card OLiA/OLiS expose numeric metadata without labels:
    #   unchanged/new: weeks, peak
    #   moved:         previous_position, weeks, peak
    numeric_tail: list[int] = []
    for line in reversed(cleaned):
        if _is_int(line):
            numeric_tail.append(int(line))
        elif numeric_tail:
            break
    numeric_tail.reverse()

    entry: dict = {"position": pos, "artist": artist, "title": title}
    if len(numeric_tail) >= 2:
        entry["reported_weeks"] = numeric_tail[-2]
        entry["reported_peak"] = numeric_tail[-1]
    if len(numeric_tail) >= 3:
        prev = numeric_tail[-3]
        if 1 <= prev <= 100:
            entry["previous_position"] = prev
    return entry


def _parse_rendered_text(text: str, max_position: int = 100) -> list[dict]:
    lines = _lines(text)
    markers = _find_markers(lines, max_position=max_position)
    entries: list[dict] = []
    for mi, (pos, idx) in enumerate(markers):
        end = markers[mi + 1][1] if mi + 1 < len(markers) else min(len(lines), idx + 40)
        entry = _parse_card(pos, lines[idx + 1 : end])
        if entry:
            entries.append(entry)
    return entries


def parse_olis_rendered(html: str, text: str, source: str) -> dict:
    source = source.upper()
    if source not in URLS:
        raise ValueError(f"Nieznane źródło: {source}")
    start_date, end_date = _parse_date_range(text)
    entries = _parse_table(html)
    parser_mode = "table"
    if len(entries) < 10:
        entries = _parse_rendered_text(text, max_position=100)
        parser_mode = "rendered_text_v2"
    if len(entries) < 10:
        raise ValueError(f"Parser {source} odczytał tylko {len(entries)} pozycji po renderowaniu JS")
    return {
        "source": source,
        "chart_date": end_date,
        "issue_key": f"{start_date}_{end_date}",
        "chart_size": 100,
        "entries": entries,
        "parser_mode": parser_mode,
    }




def _decode_export(content: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1250", "latin-1"):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def _parse_export_csv(content: bytes) -> list[dict]:
    """Parse the official OLiA/OLiS CSV export using tolerant column aliases."""
    text = _decode_export(content)
    candidates: list[pd.DataFrame] = []
    # Auto-sniff delimiter first; then common Polish CSV delimiters.
    for kwargs in (
        {"sep": None, "engine": "python"},
        {"sep": ";", "engine": "python"},
        {"sep": ",", "engine": "python"},
        {"sep": "\t", "engine": "python"},
    ):
        try:
            df = pd.read_csv(StringIO(text), **kwargs)
            if not df.empty:
                candidates.append(_flatten_columns(df))
        except Exception:
            pass
    for df in candidates:
        pos_col = _find_col(df.columns, ("pozycja", "miejsce", "position", "rank", "lp"))
        title_col = _find_col(df.columns, ("tytul", "tytuł", "title"))
        artist_col = _find_col(df.columns, ("wykonawca", "artist"))
        if pos_col is None or title_col is None or artist_col is None:
            continue
        weeks_col = _find_col(df.columns, ("tygodnie", "weeks"))
        peak_col = _find_col(df.columns, ("najwyzsza", "najwyższa", "peak"))
        prev_col = _find_col(df.columns, ("poprzednia", "previous", "last week", "lw"))
        entries: list[dict] = []
        for _, row in df.iterrows():
            m = re.search(r"\b(\d{1,3})\b", str(row.get(pos_col, "")))
            if not m:
                continue
            pos = int(m.group(1))
            if not 1 <= pos <= 100:
                continue
            title = str(row.get(title_col, "")).strip()
            artist = str(row.get(artist_col, "")).strip()
            if not title or title.lower() == "nan" or not artist or artist.lower() == "nan":
                continue
            e: dict = {"position": pos, "artist": artist, "title": title}
            for col, key in ((weeks_col, "reported_weeks"), (peak_col, "reported_peak"), (prev_col, "previous_position")):
                if col is None:
                    continue
                mm = re.search(r"\b(\d{1,3})\b", str(row.get(col, "")))
                if mm:
                    e[key] = int(mm.group(1))
            entries.append(e)
        by_pos = {e["position"]: e for e in entries}
        if len(by_pos) >= 10:
            return [by_pos[p] for p in sorted(by_pos)]
    return []


def _try_official_export(source: str) -> tuple[list[dict], dict]:
    """Try the official CSV export exposed by OLiA/OLiS."""
    meta: dict = {"attempted": True}
    try:
        exported = download_by_text(URLS[source.upper()], labels=("CSV",))
        meta.update({
            "filename": exported.filename,
            "bytes": len(exported.content),
            "via": exported.via,
            "url": exported.url,
            "head": _decode_export(exported.content)[:700],
        })
        entries = _parse_export_csv(exported.content)
        meta["parsed_entries"] = len(entries)
        return entries, meta
    except Exception as exc:
        meta["error"] = f"{type(exc).__name__}: {exc}"
        return [], meta


def _request(source: str, timeout: int = 30):
    source = source.upper()
    if source not in URLS:
        raise ValueError(f"Nieznane źródło: {source}")
    return requests.get(URLS[source], headers=HEADERS, timeout=timeout, allow_redirects=True)


def _render(source: str):
    return render_page(URLS[source.upper()], click_texts=["zobacz pełną listę"], auto_scroll=True)


def probe_olis(source: str, timeout: int = 30) -> dict:
    source = source.upper()
    r = _request(source, timeout=timeout)
    r.raise_for_status()
    raw_soup = BeautifulSoup(r.text, "lxml")
    raw_visible = re.sub(r"\s+", " ", raw_soup.get_text(" ", strip=True))
    scripts = [s.get("src") for s in raw_soup.find_all("script") if s.get("src")][:12]

    rendered = None
    parsed_entries = None
    parse_error = None
    date_range = None
    parser_mode = None
    preview = None
    rendered_lines: list[str] = []
    try:
        rendered = _render(source)
        rendered_lines = _lines(rendered.text)
        start, end = _parse_date_range(rendered.text)
        date_range = f"{start} → {end}"
        parsed = parse_olis_rendered(rendered.html, rendered.text, source)
        parsed_entries = len(parsed["entries"])
        parser_mode = parsed.get("parser_mode")
        preview = parsed["entries"][:5]
    except Exception as exc:
        parse_error = f"{type(exc).__name__}: {exc}"

    export_meta = None
    export_preview = None
    if (parsed_entries or 0) < 50:
        export_entries, export_meta = _try_official_export(source)
        if export_entries:
            export_preview = export_entries[:5]

    return {
        "source": source,
        "http_status": r.status_code,
        "url": r.url,
        "content_type": r.headers.get("content-type", ""),
        "bytes": len(r.content),
        "raw_has_chart": bool(DATE_RANGE_RE.search(raw_visible)),
        "script_srcs": scripts,
        "rendered": rendered is not None,
        "rendered_status": rendered.status if rendered else None,
        "rendered_url": rendered.url if rendered else None,
        "rendered_title": rendered.title if rendered else None,
        "date_range": date_range,
        "parsed_entries": parsed_entries,
        "parser_mode": parser_mode,
        "preview": preview,
        "export": export_meta,
        "export_preview": export_preview,
        "parse_error": parse_error,
        "body_sha256": hashlib.sha256(r.content).hexdigest()[:16],
        "raw_visible_start": raw_visible[:350],
        "rendered_lines_start": rendered_lines[:80],
        "rendered_lines_tail": rendered_lines[-40:] if rendered_lines else [],
    }


def fetch_olis(source: str, timeout: int = 30) -> dict:
    source = source.upper()
    if source not in URLS:
        raise ValueError(f"Nieznane źródło: {source}")

    # The public page initially exposes only ~12 rows and hydrates controls asynchronously.
    # The official CSV export is therefore the authoritative first choice. Retry because
    # the export control itself is JavaScript-driven and occasionally appears late.
    export_errors: list[str] = []
    export_entries: list[dict] = []
    export_meta: dict | None = None
    for attempt in range(1, 4):
        entries, meta = _try_official_export(source)
        export_meta = meta
        if len(entries) >= 50:
            export_entries = entries
            break
        export_errors.append(str(meta.get("error") or f"tylko {len(entries)} pozycji"))
        if attempt < 3:
            time.sleep(1.0 * attempt)

    # Render once for the issue date/key and as a fallback if the full DOM happened to load.
    rendered = _render(source)
    data = parse_olis_rendered(rendered.html, rendered.text, source)
    if len(export_entries) >= 50:
        data["entries"] = export_entries
        data["parser_mode"] = "official_csv_export_retry"
        data["export_meta"] = export_meta
    elif len(data["entries"]) < 50:
        raise ValueError(
            f"Parser {source} odczytał tylko {len(data['entries'])} pozycji; "
            f"oficjalny CSV nie dał pełnej listy po 3 próbach: {' | '.join(export_errors[-3:])}"
        )
    data["source_url"] = rendered.url
    return data
