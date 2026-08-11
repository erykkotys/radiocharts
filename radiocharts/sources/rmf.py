from __future__ import annotations

import re
from datetime import date
import requests
from bs4 import BeautifulSoup

CURRENT_URL = "https://www.rmf.fm/poplista.html"
ARCHIVE_URL = "https://www.rmf.fm/poplista.html?a=poplista&nr={issue}"

CONTROL = {"propozycje", "lubisz – popieraj!", "lubisz - popieraj!", "nie lubisz – odrzucaj!"}


def _tokens(html: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    return [re.sub(r"\s+", " ", x).strip() for x in soup.stripped_strings if x.strip()]


def parse_rmf(html: str) -> dict:
    tokens = _tokens(html)
    issue_idx = None
    issue_no = None
    chart_date = None
    issue_re = re.compile(r"^(?:Notowanie\s+)?(\d{3,5})\s*/\s*(\d{4}-\d{2}-\d{2})$")
    for i, tok in enumerate(tokens):
        m = issue_re.match(tok)
        if m:
            issue_idx = i
            issue_no = int(m.group(1))
            chart_date = date.fromisoformat(m.group(2))
            break
    if issue_idx is None:
        # sometimes number and date can be split by markup
        for i in range(len(tokens) - 2):
            if re.fullmatch(r"\d{3,5}", tokens[i]) and tokens[i+1] == "/" and re.fullmatch(r"\d{4}-\d{2}-\d{2}", tokens[i+2]):
                issue_idx, issue_no, chart_date = i, int(tokens[i]), date.fromisoformat(tokens[i+2])
                break
    if issue_idx is None:
        raise ValueError("Nie znaleziono numeru/data notowania RMF")

    stream = tokens[issue_idx + 1:]
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
        # Po pozycji spodziewamy się wykonawcy i tytułu. Pomijamy elementy UI.
        values = []
        k = found + 1
        while k < len(stream) and len(values) < 2:
            v = stream[k].strip()
            low = v.lower()
            if low == "propozycje":
                break
            if v and not re.fullmatch(r"\d+", v) and low not in {"tak", "nie", "głosuj"}:
                values.append(v)
            k += 1
        if len(values) < 2:
            break
        entries.append({"position": pos, "artist": values[0], "title": values[1]})
        cursor = k
    if len(entries) < 10:
        raise ValueError(f"Parser RMF odczytał tylko {len(entries)} pozycji; strona mogła zmienić strukturę")
    return {"source": "RMF", "chart_date": chart_date, "issue_key": str(issue_no), "chart_size": 20, "entries": entries}


def fetch_rmf(issue: int | None = None, timeout: int = 20) -> dict:
    url = ARCHIVE_URL.format(issue=issue) if issue is not None else CURRENT_URL
    r = requests.get(url, timeout=timeout, headers={"User-Agent": "RadioCharts/0.1 (+personal music research)"})
    r.raise_for_status()
    data = parse_rmf(r.text)
    data["source_url"] = r.url
    if issue is not None and str(data["issue_key"]) != str(issue):
        raise ValueError(f"RMF zwrócił notowanie {data['issue_key']} zamiast żądanego {issue}")
    return data
