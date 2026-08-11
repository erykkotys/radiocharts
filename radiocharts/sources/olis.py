from __future__ import annotations

import hashlib
import re
from datetime import datetime
from io import StringIO

import pandas as pd
import requests
from bs4 import BeautifulSoup

from radiocharts.sources.browser import render_page

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
POS_RE = re.compile(r"^(\d{1,3})\s*(?:\(([^)]*)\))?$")

TREND_NOISE = {
    "bez zmian na liście", "bez zmian na liscie", "nowość", "nowosc", "wzrost", "spadek",
    "pozycja", "okładka", "okladka", "wykonawca", "tytuł", "tytul", "wydawca/dystrybutor",
    "wydawca / dystrybutor", "wydawca", "dystrybutor", "x",
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


def _is_position_marker(lines: list[str], idx: int, expected: int) -> bool:
    line = lines[idx]
    m = POS_RE.fullmatch(line)
    if not m or int(m.group(1)) != expected:
        return False
    # "1 (1)" is unambiguous.  A naked "1" is accepted only when the
    # following metadata looks like a chart card, not a weeks/peak value.
    if m.group(2) is not None:
        return True
    look = " ".join(lines[idx + 1 : idx + 5]).lower()
    return (
        "tygodnie na danej" in look
        or "bez zmian" in look
        or (idx + 1 < len(lines) and re.fullmatch(r"\([^)]*\)", lines[idx + 1]))
    )


def _clean_content(block: list[str]) -> tuple[list[str], int | None, int | None]:
    # OLiA/OLiS often render a label and its value as separate DOM lines, e.g.
    # ``TYGODNIE NA DANEJ LIŚCIE`` then ``15``.  Read those pairs explicitly
    # instead of relying only on one-line regexes.
    joined = " ".join(block)
    weeks, peak = _extract_reported_info(joined)

    content: list[str] = []
    pending_meta: str | None = None
    for raw in block:
        line = raw.strip()
        n = _norm(line)
        if re.fullmatch(r"\([^)]*\)", line):
            continue

        if "tygodnie na danej liscie" in n:
            pending_meta = "weeks"
            m = re.search(r"(\d{1,3})", line)
            if m:
                weeks = int(m.group(1))
                pending_meta = None
            continue
        if "najwyzsza pozycja na liscie" in n:
            pending_meta = "peak"
            m = re.search(r"(\d{1,3})", line)
            if m:
                peak = int(m.group(1))
                pending_meta = None
            continue
        if pending_meta and re.fullmatch(r"\d{1,3}", line):
            if pending_meta == "weeks":
                weeks = int(line)
            else:
                peak = int(line)
            pending_meta = None
            continue
        pending_meta = None

        if n in TREND_NOISE:
            continue
        if n.startswith("bez zmian") or n.startswith("nowosc") or n.startswith("wzrost") or n.startswith("spadek"):
            continue
        if re.fullmatch(r"[▲▼△▽+\-–—]+(?:\s*\d+)?", line):
            continue
        if re.fullmatch(r"\d{1,3}", line):
            continue
        content.append(line)
    return content, weeks, peak


def _parse_rendered_text(text: str) -> list[dict]:
    """Parse the card layout shown by OLiA/OLiS after JavaScript rendering."""
    lines = _lines(text)
    # Ignore navigation: the chart begins after the current date range/week.
    start = 0
    for i, line in enumerate(lines):
        if DATE_RANGE_RE.search(" ".join(lines[i : i + 2])):
            start = i
            break
    for i, line in enumerate(lines):
        if re.fullmatch(r"Tydzień\s+\d+", line, re.I):
            start = max(start, i)
            break

    markers: list[tuple[int, int]] = []
    cursor = start
    expected = 1
    while expected <= 100:
        found = None
        for i in range(cursor, len(lines)):
            if _is_position_marker(lines, i, expected):
                found = i
                break
        if found is None:
            break
        markers.append((expected, found))
        cursor = found + 1
        expected += 1

    entries: list[dict] = []
    for mi, (pos, idx) in enumerate(markers):
        end = markers[mi + 1][1] if mi + 1 < len(markers) else min(len(lines), idx + 40)
        block = lines[idx + 1 : end]
        content, weeks, peak = _clean_content(block)
        if len(content) < 2:
            continue
        # In the live site cards the first meaningful value is title and the
        # second is artist.  Publisher/distributor, if present, follows later.
        title, artist = content[0], content[1]
        entry = {"position": pos, "artist": artist, "title": title}
        if weeks is not None:
            entry["reported_weeks"] = weeks
        if peak is not None:
            entry["reported_peak"] = peak
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
        entries = _parse_rendered_text(text)
        parser_mode = "rendered_text"
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


def _request(source: str, timeout: int = 30):
    source = source.upper()
    if source not in URLS:
        raise ValueError(f"Nieznane źródło: {source}")
    return requests.get(URLS[source], headers=HEADERS, timeout=timeout, allow_redirects=True)


def _render(source: str):
    return render_page(URLS[source.upper()])


def probe_olis(source: str, timeout: int = 30) -> dict:
    source = source.upper()
    r = _request(source, timeout=timeout)
    r.raise_for_status()
    raw_soup = BeautifulSoup(r.text, "lxml")
    raw_visible = re.sub(r"\s+", " ", raw_soup.get_text(" ", strip=True))
    scripts = [s.get("src") for s in raw_soup.find_all("script") if s.get("src")][:12]

    rendered = None
    render_error = None
    parsed_entries = None
    parse_error = None
    date_range = None
    parser_mode = None
    rendered_lines = []
    try:
        rendered = _render(source)
        rendered_lines = _lines(rendered.text)
        start, end = _parse_date_range(rendered.text)
        date_range = f"{start} → {end}"
        parsed = parse_olis_rendered(rendered.html, rendered.text, source)
        parsed_entries = len(parsed["entries"])
        parser_mode = parsed.get("parser_mode")
    except Exception as exc:
        render_error = f"{type(exc).__name__}: {exc}"
        parse_error = render_error

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
        "parse_error": parse_error,
        "body_sha256": hashlib.sha256(r.content).hexdigest()[:16],
        "raw_visible_start": raw_visible[:350],
        "rendered_lines_start": rendered_lines[:60],
    }


def fetch_olis(source: str, timeout: int = 30) -> dict:
    source = source.upper()
    if source not in URLS:
        raise ValueError(f"Nieznane źródło: {source}")
    rendered = _render(source)
    data = parse_olis_rendered(rendered.html, rendered.text, source)
    data["source_url"] = rendered.url
    return data
