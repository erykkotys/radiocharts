from __future__ import annotations

import hashlib
import re
from datetime import date

import requests
from bs4 import BeautifulSoup

from radiocharts.sources.browser import render_page

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


def _clean_tokens(values) -> list[str]:
    return [re.sub(r"\s+", " ", str(x)).strip() for x in values if str(x).strip()]


def _tokens(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    return _clean_tokens(soup.stripped_strings)


def _text_tokens(text: str) -> list[str]:
    return _clean_tokens(text.splitlines())


def _find_chart_start(tokens: list[str]) -> int:
    starts = [i for i, t in enumerate(tokens) if t.casefold() == "gorąca 20".casefold()]
    for candidate in starts:
        look = tokens[candidate + 1 : candidate + 30]
        for j, value in enumerate(look[:-2]):
            if value == "1" and look[j + 1] in TREND:
                return candidate + 1 + j
    base = starts[-1] + 1 if starts else 0
    for i in range(base, len(tokens) - 1):
        if tokens[i] == "1" and tokens[i + 1] in TREND:
            return i
    return base


def _parse_tokens(tokens: list[str], chart_date: date | None = None) -> dict:
    start = _find_chart_start(tokens)
    stream = tokens[start:]
    entries: list[dict] = []
    cursor = 0

    for pos in range(1, 21):
        found = None
        for j in range(cursor, len(stream) - 1):
            if stream[j].upper() == "PROPOZYCJE":
                break
            if stream[j] == str(pos) and stream[j + 1] in TREND:
                found = j
                break
        if found is None:
            break

        k = found + 2
        values: list[str] = []
        while k < len(stream):
            value = stream[k].strip()
            low = value.casefold()
            if value.upper() == "PROPOZYCJE":
                break
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
                f"fragment={stream[found:found+14]!r}"
            )

        title = values[0]
        artists = [v for v in values[1:] if v.casefold() not in NOISE]
        entries.append({"position": pos, "artist": ", ".join(artists), "title": title})
        cursor = k

    if len(entries) < 10:
        raise ValueError(
            f"Parser ESKA odczytał tylko {len(entries)} pozycji; "
            f"start_fragment={stream[:50]!r}"
        )

    d = chart_date or date.today()
    return {
        "source": "ESKA",
        "chart_date": d,
        "issue_key": d.isoformat(),
        "chart_size": 20,
        "entries": entries,
    }


def parse_eska(html: str, chart_date: date | None = None) -> dict:
    return _parse_tokens(_tokens(html), chart_date=chart_date)


def parse_eska_text(text: str, chart_date: date | None = None) -> dict:
    return _parse_tokens(_text_tokens(text), chart_date=chart_date)


def _request(timeout: int = 30):
    return requests.get(URL, headers=HEADERS, timeout=timeout, allow_redirects=True)


def _render():
    return render_page(URL, auto_scroll=False)


def probe_eska(timeout: int = 30) -> dict:
    raw_error = rendered_error = None
    raw_preview = rendered_preview = None
    r = None
    rendered = None

    try:
        r = _request(timeout=timeout)
        r.raise_for_status()
        data = parse_eska(r.text)
        raw_preview = data["entries"][:5]
    except Exception as exc:
        raw_error = f"{type(exc).__name__}: {exc}"

    if raw_preview is None:
        try:
            rendered = _render()
            data = parse_eska_text(rendered.text)
            rendered_preview = data["entries"][:5]
        except Exception as exc:
            rendered_error = f"{type(exc).__name__}: {exc}"

    return {
        "source": "ESKA",
        "http_status": r.status_code if r is not None else None,
        "url": r.url if r is not None else URL,
        "content_type": r.headers.get("content-type", "") if r is not None else None,
        "bytes": len(r.content) if r is not None else None,
        "raw_parsed": raw_preview is not None,
        "raw_preview": raw_preview,
        "raw_error": raw_error,
        "rendered": rendered is not None,
        "rendered_status": rendered.status if rendered else None,
        "rendered_preview": rendered_preview,
        "rendered_error": rendered_error,
        "body_sha256": hashlib.sha256(r.content).hexdigest()[:16] if r is not None else None,
        "rendered_lines_start": _text_tokens(rendered.text)[:80] if rendered else None,
    }


def fetch_eska(timeout: int = 30) -> dict:
    raw_exc = None
    try:
        r = _request(timeout=timeout)
        r.raise_for_status()
        data = parse_eska(r.text)
        data["source_url"] = r.url
        return data
    except Exception as exc:
        raw_exc = exc

    try:
        rendered = _render()
        data = parse_eska_text(rendered.text)
        data["source_url"] = rendered.url
        return data
    except Exception as rendered_exc:
        raise ValueError(
            f"ESKA raw={type(raw_exc).__name__}: {raw_exc}; "
            f"rendered={type(rendered_exc).__name__}: {rendered_exc}"
        ) from rendered_exc
