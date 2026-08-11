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

TREND = {"▲", "▼", "△", "▽", "-", "–", "—", "N", "n"}
NOISE = {"radio eska", "hity na czasie"}


def _tokens(html: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    return [re.sub(r"\s+", " ", x).strip() for x in soup.stripped_strings if x.strip()]


def parse_eska(html: str, chart_date: date | None = None) -> dict:
    tokens = _tokens(html)
    # The page contains "Gorąca 20" in navigation as well as in the actual
    # chart heading. Pick the occurrence whose following tokens contain the
    # first chart position, rather than blindly taking first/last occurrence.
    starts = [i for i, t in enumerate(tokens) if t.casefold() == "gorąca 20".casefold()]
    start = 0
    for candidate in starts:
        look = tokens[candidate + 1 : candidate + 12]
        if "1" in look:
            start = candidate + 1
            break
    stream = tokens[start:]

    entries: list[dict] = []
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
        if k < len(stream) and stream[k] in TREND:
            k += 1

        values: list[str] = []
        while k < len(stream):
            value = stream[k].strip()
            low = value.casefold()
            if value.upper() == "PROPOZYCJE":
                break
            if value == str(pos + 1) and values:
                break
            if low in NOISE:
                if values:
                    # Ads separate some cards; once title/artist are already
                    # collected this is a safe card boundary.
                    break
                k += 1
                continue
            if value not in TREND:
                values.append(value)
            k += 1

        if len(values) < 2:
            raise ValueError(f"ESKA pozycja {pos}: za mało pól po karcie: {values!r}")
        title = values[0]
        artists = [v for v in values[1:] if v.casefold() not in NOISE]
        entries.append({"position": pos, "artist": ", ".join(artists), "title": title})
        cursor = max(k, found + 1)

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
    preview = None
    try:
        data = parse_eska(r.text)
        parsed = len(data["entries"])
        preview = data["entries"][:5]
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    return {
        "source": "ESKA",
        "http_status": r.status_code,
        "url": r.url,
        "content_type": r.headers.get("content-type", ""),
        "bytes": len(r.content),
        "parsed_entries": parsed,
        "preview": preview,
        "parse_error": error,
        "body_sha256": hashlib.sha256(r.content).hexdigest()[:16],
        "visible_start": " | ".join(tokens[:80]),
    }


def fetch_eska(timeout: int = 30) -> dict:
    r = _request(timeout=timeout)
    r.raise_for_status()
    try:
        data = parse_eska(r.text)
    except Exception as exc:
        diag = probe_eska(timeout=timeout)
        raise ValueError(
            f"ESKA: {exc}. HTTP={diag['http_status']}, parsed={diag['parsed_entries']}, "
            f"visible_start={diag['visible_start']!r}"
        ) from exc
    data["source_url"] = r.url
    return data
