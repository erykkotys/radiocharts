from __future__ import annotations

import hashlib
import re
from datetime import datetime

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
NUMBER_RE = re.compile(r"^Number\s+(\d{1,3})$", re.I)


def _tokens(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    return [re.sub(r"\s+", " ", s).strip() for s in soup.stripped_strings if str(s).strip()]


def _date_range(tokens: list[str]) -> tuple[str, str]:
    joined = " ".join(tokens[:300])
    m = DATE_RE.search(joined)
    if not m:
        raise ValueError("UK: nie znaleziono zakresu dat notowania")
    start = datetime.strptime(m.group(1), "%d %B %Y").date().isoformat()
    end = datetime.strptime(m.group(2), "%d %B %Y").date().isoformat()
    return start, end


def parse_uk(html: str) -> dict:
    tokens = _tokens(html)
    start_date, end_date = _date_range(tokens)
    markers: list[tuple[int, int]] = []
    for idx, token in enumerate(tokens):
        m = NUMBER_RE.match(token)
        if m:
            pos = int(m.group(1))
            if 1 <= pos <= 100:
                markers.append((pos, idx))
    # Deduplicate and keep first monotonically ordered chart sequence.
    selected: list[tuple[int, int]] = []
    cursor = -1
    for expected in range(1, 101):
        candidates = [(p, i) for p, i in markers if p == expected and i > cursor]
        if not candidates:
            break
        p, i = candidates[0]
        selected.append((p, i))
        cursor = i

    entries: list[dict] = []
    for n, (pos, idx) in enumerate(selected):
        end = selected[n + 1][1] if n + 1 < len(selected) else min(len(tokens), idx + 30)
        block = tokens[idx + 1 : end]
        if len(block) < 2:
            continue
        title, artist = block[0], block[1]
        joined = " ".join(block)
        lw_m = re.search(r"\bLW:\s*(\d+|-)\b", joined, re.I)
        peak_m = re.search(r"\bPeak:\s*(\d+)\b", joined, re.I)
        weeks_m = re.search(r"\bWeeks:\s*(\d+)\b", joined, re.I)
        entry = {"position": pos, "title": title, "artist": artist}
        if lw_m and lw_m.group(1).isdigit():
            entry["previous_position"] = int(lw_m.group(1))
        if peak_m:
            entry["reported_peak"] = int(peak_m.group(1))
        if weeks_m:
            entry["reported_weeks"] = int(weeks_m.group(1))
        entries.append(entry)

    if len(entries) < 40:
        raise ValueError(f"UK: parser odczytał tylko {len(entries)} pozycji")
    return {
        "source": "UK",
        "chart_date": end_date,
        "issue_key": f"{start_date}_{end_date}",
        "chart_size": 100,
        "entries": entries,
        "source_url": URL,
    }


def fetch_uk(timeout: int = 35) -> dict:
    r = requests.get(URL, headers=HEADERS, timeout=timeout, allow_redirects=True)
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
        "visible_start": " | ".join(_tokens(r.text)[:100]),
    }
