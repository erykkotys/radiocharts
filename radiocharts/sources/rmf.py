from __future__ import annotations

import html as html_lib
import re
from datetime import date

import requests
from bs4 import BeautifulSoup

CURRENT_URL = "https://www.rmf.fm/poplista.html"
ARCHIVE_URL = "https://www.rmf.fm/poplista.html?a=poplista&nr={issue}"

# RMF serves slightly different markup depending on the client.  Use ordinary
# browser headers instead of a bot-looking custom User-Agent.
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

CONTROL = {
    "propozycje",
    "lubisz – popieraj!",
    "lubisz - popieraj!",
    "nie lubisz – odrzucaj!",
    "nie lubisz - odrzucaj!",
}

ISSUE_RE = re.compile(r"(?:Notowanie\s+)?(\d{3,5})\s*/\s*(\d{4}-\d{2}-\d{2})", re.I)


def _tokens(html: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    return [re.sub(r"\s+", " ", x).strip() for x in soup.stripped_strings if x.strip()]


def _find_issue(html: str, tokens: list[str]) -> tuple[int | None, int, date]:
    """Return (token index if known, issue number, chart date).

    RMF has historically changed the markup around the issue header.  We first
    inspect individual text nodes, then joined visible text, and finally raw
    HTML with tags/entities stripped enough for a regex fallback.
    """
    # Fast path: one visible text node, e.g. "6182 / 2026-08-10".
    for i, tok in enumerate(tokens):
        m = ISSUE_RE.fullmatch(tok)
        if m:
            return i, int(m.group(1)), date.fromisoformat(m.group(2))

    # Markup may split the number, slash and date into separate nodes.
    for i in range(len(tokens) - 2):
        if (
            re.fullmatch(r"\d{3,5}", tokens[i])
            and tokens[i + 1] == "/"
            and re.fullmatch(r"\d{4}-\d{2}-\d{2}", tokens[i + 2])
        ):
            return i, int(tokens[i]), date.fromisoformat(tokens[i + 2])

    # General visible-text fallback.
    joined = " ".join(tokens)
    m = ISSUE_RE.search(joined)
    if m:
        # Locate the first token containing the issue number if possible.  This
        # lets the existing token-stream entry parser start after the header.
        idx = next((i for i, t in enumerate(tokens) if str(m.group(1)) in t), None)
        return idx, int(m.group(1)), date.fromisoformat(m.group(2))

    # Last resort: normalize raw HTML.  This also handles entities and tags
    # inserted between issue number, slash and date.
    raw = html_lib.unescape(html)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = re.sub(r"\s+", " ", raw)
    m = ISSUE_RE.search(raw)
    if m:
        return None, int(m.group(1)), date.fromisoformat(m.group(2))

    raise ValueError("Nie znaleziono numeru/data notowania RMF")


def parse_rmf(html: str) -> dict:
    tokens = _tokens(html)
    issue_idx, issue_no, chart_date = _find_issue(html, tokens)

    # If the exact token index was not recoverable, find the first occurrence
    # of the issue number and start there.  Otherwise use the known index.
    if issue_idx is None:
        issue_idx = next((i for i, t in enumerate(tokens) if str(issue_no) in t), -1)

    stream = tokens[issue_idx + 1 :] if issue_idx >= 0 else tokens
    entries = []
    cursor = 0

    for pos in range(1, 21):
        found = None
        for j in range(cursor, len(stream)):
            low = stream[j].lower()
            if low in CONTROL or low == "propozycje":
                break
            if stream[j] == str(pos):
                found = j
                break
        if found is None:
            break

        # After a position RMF exposes artist and title as the next two useful
        # visible strings.  Ignore simple voting/UI labels.
        values = []
        k = found + 1
        while k < len(stream) and len(values) < 2:
            v = stream[k].strip()
            low = v.lower()
            if low == "propozycje":
                break
            if v and not re.fullmatch(r"\d+", v) and low not in {
                "tak",
                "nie",
                "głosuj",
                "glosuj",
                "wpisz numer notowania",
            }:
                values.append(v)
            k += 1

        if len(values) < 2:
            break

        entries.append({"position": pos, "artist": values[0], "title": values[1]})
        cursor = k

    if len(entries) < 10:
        raise ValueError(
            f"Parser RMF odczytał tylko {len(entries)} pozycji; strona mogła zmienić strukturę"
        )

    return {
        "source": "RMF",
        "chart_date": chart_date,
        "issue_key": str(issue_no),
        "chart_size": 20,
        "entries": entries,
    }


def fetch_rmf(issue: int | None = None, timeout: int = 25) -> dict:
    url = ARCHIVE_URL.format(issue=issue) if issue is not None else CURRENT_URL

    with requests.Session() as session:
        r = session.get(url, timeout=timeout, headers=HEADERS, allow_redirects=True)
    r.raise_for_status()

    try:
        data = parse_rmf(r.text)
    except ValueError as exc:
        # Provide enough diagnostics in TrueNAS logs without dumping a whole
        # webpage.  This makes future RMF markup/blocking changes easy to spot.
        soup = BeautifulSoup(r.text, "lxml")
        title = soup.title.get_text(" ", strip=True) if soup.title else "(brak title)"
        visible = " | ".join(_tokens(r.text)[:12])
        raise ValueError(
            f"{exc}. HTTP {r.status_code}, URL={r.url}, title={title!r}, "
            f"początek strony={visible!r}"
        ) from exc

    data["source_url"] = r.url
    if issue is not None and str(data["issue_key"]) != str(issue):
        raise ValueError(f"RMF zwrócił notowanie {data['issue_key']} zamiast żądanego {issue}")
    return data
