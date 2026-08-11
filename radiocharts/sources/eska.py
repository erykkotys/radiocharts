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


def _find_chart_start(tokens: list[str]) -> int:
    starts = [i for i, t in enumerate(tokens) if t.casefold() == "gorąca 20".casefold()]
    # Pick the heading followed soon by rank 1 + a trend marker + title.
    for candidate in starts:
        look = tokens[candidate + 1 : candidate + 20]
        for j, value in enumerate(look[:-2]):
            if value == "1" and look[j + 1] in TREND:
                return candidate + 1 + j
    # Fallback: first 1 followed by a trend marker anywhere after a heading.
    base = starts[-1] + 1 if starts else 0
    for i in range(base, len(tokens) - 1):
        if tokens[i] == "1" and tokens[i + 1] in TREND:
            return i
    return base


def parse_eska(html: str, chart_date: date | None = None) -> dict:
    tokens = _tokens(html)
    start = _find_chart_start(tokens)
    stream = tokens[start:]

    entries: list[dict] = []
    cursor = 0
    for pos in range(1, 21):
        found = None
        for j in range(cursor, len(stream) - 1):
            if stream[j].upper() == "PROPOZYCJE":
                break
            # A real rank is followed by the trend token on the live page.
            if stream[j] == str(pos) and stream[j + 1] in TREND:
                found = j
                break
        if found is None:
            break

        k = found + 2  # rank + trend
        values: list[str] = []
        while k < len(stream):
            value = stream[k].strip()
            low = value.casefold()
            if value.upper() == "PROPOZYCJE":
                break
            # Next card: rank + trend. Do not confuse arbitrary numbers in ads.
            if (
                pos < 20
                and value == str(pos + 1)
                and k + 1 < len(stream)
                and stream[k + 1] in TREND
                and values
            ):
                break
            if low in NOISE:
                k += 1
                continue
            if value not in TREND:
                values.append(value)
            k += 1

        if len(values) < 2:
            raise ValueError(
                f"ESKA pozycja {pos}: za mało pól; start={start}, found={found}, "
                f"fragment={stream[found:found+12]!r}"
            )

        # Card text is title followed by one or more artists. Ad labels are
        # removed above; everything until the next rank belongs to the card.
        title = values[0]
        artists = [v for v in values[1:] if v.casefold() not in NOISE]
        entries.append({"position": pos, "artist": ", ".join(artists), "title": title})
        cursor = k

    if len(entries) < 10:
        raise ValueError(
            f"Parser ESKA odczytał tylko {len(entries)} pozycji; "
            f"start_fragment={stream[:40]!r}"
        )

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
    start = None
    try:
        start = _find_chart_start(tokens)
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
        "chart_start_index": start,
        "parsed_entries": parsed,
        "preview": preview,
        "parse_error": error,
        "body_sha256": hashlib.sha256(r.content).hexdigest()[:16],
        "visible_start": " | ".join(tokens[:120]),
        "chart_fragment": tokens[start:start + 60] if isinstance(start, int) else None,
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
            f"chart_fragment={diag.get('chart_fragment')!r}"
        ) from exc
    data["source_url"] = r.url
    return data
