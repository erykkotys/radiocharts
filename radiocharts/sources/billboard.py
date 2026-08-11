from __future__ import annotations

import hashlib
import re
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from radiocharts.sources.browser import render_page

URL = "https://www.billboard.com/charts/hot-100/"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
DATE_RE = re.compile(r"Week\s+of\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})", re.I)
NOISE = {
    "new", "re-entry", "reentry", "hot shot debut", "greatest gainer",
    "streaming gainer", "airplay gainer", "sales gainer", "this week",
    "last week", "peak pos.", "peak pos", "wks on chart", "awards",
}


def _tokens_from_html(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    return [re.sub(r"\s+", " ", s).strip() for s in soup.stripped_strings if str(s).strip()]


def _tokens_from_text(text: str) -> list[str]:
    return [re.sub(r"\s+", " ", s).strip() for s in text.splitlines() if s.strip()]


def _chart_date(tokens: list[str]) -> str:
    joined = " ".join(tokens[:400])
    m = DATE_RE.search(joined)
    if not m:
        raise ValueError("Billboard: nie znaleziono daty 'Week of ...'")
    return datetime.strptime(m.group(1), "%B %d, %Y").date().isoformat()


def _is_int(s: str) -> bool:
    return bool(re.fullmatch(r"\d{1,3}", s))


def _find_start(tokens: list[str]) -> int:
    for i, t in enumerate(tokens):
        if t.casefold() == "wks on chart":
            return i + 1
    for i, t in enumerate(tokens):
        if "billboard hot 100" in t.casefold():
            return i + 1
    return 0


def _rank_marker(tokens: list[str], idx: int, expected: int) -> bool:
    if tokens[idx] != str(expected):
        return False
    j = idx + 1
    while j < len(tokens) and tokens[j].casefold() in NOISE:
        j += 1
    if j >= len(tokens):
        return False
    # Real rank is followed by a title. Numeric metadata from the previous row
    # is followed by more numeric metadata or the next rank.
    return not _is_int(tokens[j]) and tokens[j] not in {"-", "–", "—"}


def _parse_tokens(tokens: list[str]) -> dict:
    chart_date = _chart_date(tokens)
    start = _find_start(tokens)
    markers: list[tuple[int, int]] = []
    cursor = start
    for expected in range(1, 101):
        found = None
        for i in range(cursor, len(tokens)):
            if _rank_marker(tokens, i, expected):
                found = i
                break
        if found is None:
            break
        markers.append((expected, found))
        cursor = found + 1

    entries: list[dict] = []
    for n, (pos, idx) in enumerate(markers):
        end = markers[n + 1][1] if n + 1 < len(markers) else min(len(tokens), idx + 35)
        block = tokens[idx + 1 : end]
        cleaned = [x for x in block if x.casefold() not in NOISE]
        # Awards may be verbose; title/artist are the first two non-numeric values.
        textual = [x for x in cleaned if not _is_int(x) and x not in {"-", "–", "—"}]
        if len(textual) < 2:
            continue
        title, artist = textual[0], textual[1]
        nums = [int(x) for x in cleaned if _is_int(x)]
        entry = {"position": pos, "title": title, "artist": artist}
        if len(nums) >= 3:
            entry["previous_position"] = nums[-3]
            entry["reported_peak"] = nums[-2]
            entry["reported_weeks"] = nums[-1]
        elif len(nums) >= 2:  # new entry: no numeric LW
            entry["reported_peak"] = nums[-2]
            entry["reported_weeks"] = nums[-1]
        entries.append(entry)

    if len(entries) < 25:
        raise ValueError(f"Billboard: parser odczytał tylko {len(entries)} pozycji")
    return {
        "source": "BILLBOARD",
        "chart_date": chart_date,
        "issue_key": chart_date,
        "chart_size": 100,
        "entries": entries,
        "source_url": URL,
    }


def parse_billboard_html(html: str) -> dict:
    return _parse_tokens(_tokens_from_html(html))


def parse_billboard_text(text: str) -> dict:
    return _parse_tokens(_tokens_from_text(text))


def fetch_billboard(timeout: int = 35) -> dict:
    raw_error = None
    try:
        r = requests.get(URL, headers=HEADERS, timeout=timeout, allow_redirects=True)
        r.raise_for_status()
        data = parse_billboard_html(r.text)
        data["source_url"] = r.url
        return data
    except Exception as exc:
        raw_error = exc
    try:
        rendered = render_page(URL, auto_scroll=True, settle_ms=3500)
        data = parse_billboard_text(rendered.text)
        data["source_url"] = rendered.url
        return data
    except Exception as exc:
        raise ValueError(
            f"Billboard raw={type(raw_error).__name__}: {raw_error}; "
            f"rendered={type(exc).__name__}: {exc}"
        ) from exc


def probe_billboard(timeout: int = 35) -> dict:
    raw_status = raw_bytes = None
    raw_error = rendered_error = None
    raw_preview = rendered_preview = None
    raw_sha = None
    try:
        r = requests.get(URL, headers=HEADERS, timeout=timeout, allow_redirects=True)
        raw_status = r.status_code
        raw_bytes = len(r.content)
        raw_sha = hashlib.sha256(r.content).hexdigest()[:16]
        r.raise_for_status()
        d = parse_billboard_html(r.text)
        raw_preview = d["entries"][:5]
    except Exception as exc:
        raw_error = f"{type(exc).__name__}: {exc}"
    if raw_preview is None:
        try:
            rendered = render_page(URL, auto_scroll=True, settle_ms=3500)
            d = parse_billboard_text(rendered.text)
            rendered_preview = d["entries"][:5]
        except Exception as exc:
            rendered_error = f"{type(exc).__name__}: {exc}"
    return {
        "source": "BILLBOARD",
        "http_status": raw_status,
        "bytes": raw_bytes,
        "raw_preview": raw_preview,
        "raw_error": raw_error,
        "rendered_preview": rendered_preview,
        "rendered_error": rendered_error,
        "body_sha256": raw_sha,
    }
