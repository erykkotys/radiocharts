from __future__ import annotations

import hashlib
import re
from datetime import datetime
from io import StringIO

import pandas as pd
import requests
from bs4 import BeautifulSoup

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
    m = DATE_RANGE_RE.search(text)
    if not m:
        raise ValueError("Nie znaleziono zakresu dat OLiA/OLiS")
    start = datetime.strptime(m.group(1), "%d.%m.%Y").date().isoformat()
    end = datetime.strptime(m.group(2), "%d.%m.%Y").date().isoformat()
    return start, end


def _extract_reported_info(raw: object) -> tuple[int | None, int | None]:
    """Best-effort extraction of OLiS/OLiA's own weeks and peak fields."""
    text = re.sub(r"\s+", " ", str(raw))
    weeks = peak = None
    mw = re.search(r"TYGODNIE\s+NA\s+DANEJ\s+LI[ŚS]CIE\s*(\d+)", text, re.I)
    mp = re.search(r"NAJWY[ŻZ]SZA\s+POZYCJA\s+NA\s+LI[ŚS]CIE\s*(\d+)", text, re.I)
    if mw:
        weeks = int(mw.group(1))
    if mp:
        peak = int(mp.group(1))
    return weeks, peak


def parse_olis_html(html: str, source: str) -> dict:
    source = source.upper()
    if source not in URLS:
        raise ValueError(f"Nieznane źródło: {source}")

    soup = BeautifulSoup(html, "lxml")
    visible = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    start_date, end_date = _parse_date_range(visible)

    try:
        tables = pd.read_html(StringIO(html))
    except ValueError:
        tables = []

    chosen = None
    column_map = None
    for table in tables:
        table = _flatten_columns(table)
        pos_col = _find_col(table.columns, ("pozycja", "miejsce", "position", "rank"))
        title_col = _find_col(table.columns, ("tytul", "tytuł", "title"))
        artist_col = _find_col(table.columns, ("wykonawca", "artist"))
        if pos_col is not None and title_col is not None and artist_col is not None:
            chosen = table
            info_col = _find_col(table.columns, ("informacje", "info"))
            column_map = (pos_col, title_col, artist_col, info_col)
            break

    if chosen is None:
        heads = [list(map(str, _flatten_columns(t).columns)) for t in tables[:8]]
        raise ValueError(f"Nie znaleziono tabeli notowania {source}; wykryte nagłówki={heads}")

    pos_col, title_col, artist_col, info_col = column_map
    entries = []
    for _, row in chosen.iterrows():
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

    # Some layouts may duplicate desktop/mobile rows. Keep one row per rank.
    by_pos = {}
    for e in entries:
        by_pos.setdefault(e["position"], e)
    entries = [by_pos[p] for p in sorted(by_pos)]

    if len(entries) < 10:
        raise ValueError(f"Parser {source} odczytał tylko {len(entries)} pozycji")

    return {
        "source": source,
        "chart_date": end_date,
        "issue_key": f"{start_date}_{end_date}",
        "chart_size": 100,
        "entries": entries,
    }


def _request(source: str, timeout: int = 30):
    source = source.upper()
    if source not in URLS:
        raise ValueError(f"Nieznane źródło: {source}")
    return requests.get(URLS[source], headers=HEADERS, timeout=timeout, allow_redirects=True)


def probe_olis(source: str, timeout: int = 30) -> dict:
    source = source.upper()
    r = _request(source, timeout=timeout)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")
    visible = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    try:
        tables = pd.read_html(StringIO(r.text))
        headers = [list(map(str, _flatten_columns(t).columns)) for t in tables[:8]]
    except Exception:
        tables, headers = [], []
    date_range = None
    try:
        date_range = " → ".join(_parse_date_range(visible))
    except Exception:
        pass
    parsed_entries = None
    parse_error = None
    try:
        parsed_entries = len(parse_olis_html(r.text, source)["entries"])
    except Exception as exc:
        parse_error = f"{type(exc).__name__}: {exc}"
    return {
        "source": source,
        "http_status": r.status_code,
        "url": r.url,
        "content_type": r.headers.get("content-type", ""),
        "bytes": len(r.content),
        "date_range": date_range,
        "tables_found": len(tables),
        "table_headers": headers,
        "parsed_entries": parsed_entries,
        "parse_error": parse_error,
        "body_sha256": hashlib.sha256(r.content).hexdigest()[:16],
        "visible_start": visible[:500],
    }


def fetch_olis(source: str, timeout: int = 30) -> dict:
    source = source.upper()
    r = _request(source, timeout=timeout)
    r.raise_for_status()
    try:
        data = parse_olis_html(r.text, source)
    except Exception as exc:
        diag = probe_olis(source, timeout=timeout)
        raise ValueError(
            f"{source}: {exc}. HTTP={diag['http_status']}, date_range={diag['date_range']}, "
            f"tables={diag['tables_found']}, headers={diag['table_headers'][:2]}"
        ) from exc
    data["source_url"] = r.url
    return data
