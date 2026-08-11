from __future__ import annotations

import hashlib
import re
from datetime import date

import requests
from bs4 import BeautifulSoup

URL = "https://www.eska.pl/goraca20/"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.7",
}

TREND = {"▲", "▼", "△", "▽", "-", "N", "n"}
NOISE = {"radio eska", "hity na czasie"}


def _tokens(html: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    return [re.sub(r"\s+", " ", x).strip() for x in soup.stripped_strings if x.strip()]


def parse_eska(html: str, chart_date: date | None = None) -> dict:
    tokens = _tokens(html)
    # Start after the chart heading, avoiding menu/navigation occurrences.
    starts = [i for i, t in enumerate(tokens) if t.lower() == "gorąca 20"]
    start = starts[-1] + 1 if starts else 0
    stream = tokens[start:]

    entries = []
    cursor = 0
    for pos in range(1, 21):
        found = None
        for j in range(cursor, len(stream)):
            if stream[j].upper() == "PROPOZYCJE":
                break
            if stream[j] == str(pos):
                found = j
                break
        if found is None:
            break

        k = found + 1
        while k < len(stream) and stream[k] in TREND:
            k += 1
        values = []
        while k < len(stream):
            value = stream[k].strip()
            low = value.lower()
            if value.upper() == "PROPOZYCJE":
                break
            if low in NOISE:
                k += 1
                # Noise separates one chart card from the next.
                if values:
                    break
                continue
            if value == str(pos + 1) and values:
                break
            if value not in TREND:
                values.append(value)
            k += 1

        if len(values) < 2:
            break
        title = values[0]
        artists = [v for v in values[1:] if v.lower() not in NOISE]
        entries.append({"position": pos, "artist": ", ".join(artists), "title": title})
        cursor = k

    if len(entries) < 10:
        raise ValueError(f"Parser ESKA odczytał tylko {len(entries)} pozycji")

    d = chart_date or date.today()
    return {
        "source": "ESKA",
        "chart_date": d,
        "issue_key": d.isoformat(),
        "chart_size": 20,
        "entries": entries,
    }


def _request(timeout: int = 30):
    return requests.get(URL, headers=HEADERS, timeout=timeout, allow_redirects=True)


def probe_eska(timeout: int = 30) -> dict:
    r = _request(timeout=timeout)
    r.raise_for_status()
    tokens = _tokens(r.text)
    parsed = None
    error = None
    try:
        parsed = len(parse_eska(r.text)["entries"])
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    return {
        "http_status": r.status_code,
        "url": r.url,
        "content_type": r.headers.get("content-type", ""),
        "bytes": len(r.content),
        "parsed_entries": parsed,
        "parse_error": error,
        "body_sha256": hashlib.sha256(r.content).hexdigest()[:16],
        "visible_start": " | ".join(tokens[:45]),
    }


def fetch_eska(timeout: int = 30) -> dict:
    r = _request(timeout=timeout)
    r.raise_for_status()
    try:
        data = parse_eska(r.text)
    except Exception as exc:
        diag = probe_eska(timeout=timeout)
        raise ValueError(
            f"ESKA: {exc}. HTTP={diag['http_status']}, visible_start={diag['visible_start']!r}"
        ) from exc
    data["source_url"] = r.url
    return data
