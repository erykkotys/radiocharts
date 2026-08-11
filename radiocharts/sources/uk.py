from __future__ import annotations

import hashlib
import re
from datetime import date, datetime

import requests
from bs4 import BeautifulSoup

URL = "https://www.officialcharts.com/charts/singles-chart/"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
}
DATE_RE = re.compile(r"(\d{1,2}\s+[A-Za-z]+\s+\d{4})\s*-\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4})")
NUMBER_INLINE_RE = re.compile(r"^Number\s+(\d{1,3})$", re.I)

META_LABELS = {
    "weeks", "week", "peak", "lw", "number", "position", "rank",
    "last week", "peak pos", "peak pos.", "wks on chart", "weeks on chart",
}

def _is_meta_label(value: str) -> bool:
    return re.sub(r"\s+", " ", str(value)).strip().casefold().rstrip(":") in META_LABELS

def _valid_song_pair(title: str, artist: str) -> bool:
    return not (_is_meta_label(title) and _is_meta_label(artist))



def _tokens(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    return [re.sub(r"\s+", " ", s).strip() for s in soup.stripped_strings if str(s).strip()]


def _date_range(tokens: list[str]) -> tuple[str, str]:
    joined = " ".join(tokens[:400])
    m = DATE_RE.search(joined)
    if not m:
        raise ValueError("UK: nie znaleziono zakresu dat notowania")
    start = datetime.strptime(m.group(1), "%d %B %Y").date().isoformat()
    end = datetime.strptime(m.group(2), "%d %B %Y").date().isoformat()
    return start, end


def _markers(tokens: list[str]) -> list[tuple[int, int, int]]:
    """Return (position, marker_index, content_start).

    Official Charts currently renders either `Number 1` as one text node or
    `Number`, `1` as two consecutive text nodes depending on HTML parsing.
    """
    out: list[tuple[int, int, int]] = []
    for i, token in enumerate(tokens):
        m = NUMBER_INLINE_RE.fullmatch(token)
        if m:
            pos = int(m.group(1))
            if 1 <= pos <= 100:
                out.append((pos, i, i + 1))
            continue
        if token.casefold() == "number" and i + 1 < len(tokens) and re.fullmatch(r"\d{1,3}", tokens[i + 1]):
            pos = int(tokens[i + 1])
            if 1 <= pos <= 100:
                out.append((pos, i, i + 2))
    return out


def parse_uk(html: str) -> dict:
    tokens = _tokens(html)
    start_date, end_date = _date_range(tokens)
    markers = _markers(tokens)

    selected: list[tuple[int, int, int]] = []
    cursor = -1
    for expected in range(1, 101):
        candidates = [m for m in markers if m[0] == expected and m[1] > cursor]
        if not candidates:
            break
        marker = candidates[0]
        selected.append(marker)
        cursor = marker[1]

    entries: list[dict] = []
    for n, (pos, marker_idx, content_start) in enumerate(selected):
        end = selected[n + 1][1] if n + 1 < len(selected) else min(len(tokens), content_start + 40)
        block = tokens[content_start:end]
        if not block:
            continue

        # Metadata begins at LW:. Everything before it is title/artist plus
        # optional badges such as New/Re-entry.
        meta_idx = next((i for i, x in enumerate(block) if x.casefold().startswith("lw:")), len(block))
        head = [x for x in block[:meta_idx] if x not in {",", "New", "Re-entry", "Re-Entry"}]
        if len(head) < 2:
            continue
        title, artist = head[0], head[1]
        if not _valid_song_pair(title, artist):
            continue

        joined = " ".join(block)
        lw_m = re.search(r"\bLW:\s*(\d+|New|-)", joined, re.I)
        peak_m = re.search(r"\bPeak:\s*(\d+)", joined, re.I)
        weeks_m = re.search(r"\bWeeks:\s*(\d+)", joined, re.I)
        entry: dict = {"position": pos, "title": title, "artist": artist}
        if lw_m and lw_m.group(1).isdigit():
            entry["previous_position"] = int(lw_m.group(1))
        if peak_m:
            entry["reported_peak"] = int(peak_m.group(1))
        if weeks_m:
            entry["reported_weeks"] = int(weeks_m.group(1))
        entries.append(entry)

    if len(entries) < 75:
        raise ValueError(f"UK: parser odczytał tylko {len(entries)} pozycji")
    return {
        "source": "UK",
        "chart_date": end_date,
        "issue_key": f"{start_date}_{end_date}",
        "chart_size": 100,
        "entries": entries,
        "source_url": URL,
    }


def fetch_uk(start_date: str | date | None = None, timeout: int = 35) -> dict:
    if start_date is None:
        url = URL
    else:
        d = date.fromisoformat(start_date) if isinstance(start_date, str) else start_date
        url = f"{URL}{d.strftime('%Y%m%d')}/"
    r = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    data = parse_uk(r.text)
    data["source_url"] = r.url
    return data


def probe_uk(timeout: int = 35) -> dict:
    r = requests.get(URL, headers=HEADERS, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    parsed = None
    error = None
    preview = None
    try:
        data = parse_uk(r.text)
        parsed = len(data["entries"])
        preview = data["entries"][:5]
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    return {
        "source": "UK",
        "http_status": r.status_code,
        "url": r.url,
        "bytes": len(r.content),
        "parsed_entries": parsed,
        "preview": preview,
        "parse_error": error,
        "body_sha256": hashlib.sha256(r.content).hexdigest()[:16],
        "visible_start": " | ".join(_tokens(r.text)[:140]),
    }
