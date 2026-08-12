from __future__ import annotations

import re
from datetime import date

import requests
from bs4 import BeautifulSoup

CURRENT_URL = "https://player.radiozet.pl/Lista-przebojow"
ARCHIVE_URL = "https://player.radiozet.pl/Lista-przebojow/(notowanie)/{archive_id}"
DATE_RE = re.compile(r"Notowanie\s+z\s+dnia\s+(\d{4}-\d{2}-\d{2})", re.I)
NOISE = {"lubię to", "lubie to", "lista przebojów", "lista przebojow", "propozycje"}
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.7",
}


def parse_zet_text(text: str, fallback_date: date | None = None, source_url: str | None = None) -> dict:
    """Parse the public Radio ZET chart text: rank -> artist -> title."""
    lines = [re.sub(r"\s+", " ", x).strip() for x in text.splitlines() if x.strip()]
    joined = "\n".join(lines)
    m = DATE_RE.search(joined)
    d = date.fromisoformat(m.group(1)) if m else (fallback_date or date.today())

    start = 0
    if m:
        for i, line in enumerate(lines):
            if m.group(1) in line and "Notowanie" in line:
                start = i + 1
                break
    stream = lines[start:]
    entries: list[dict] = []
    cursor = 0
    for pos in range(1, 21):
        found = None
        for i in range(cursor, len(stream)):
            if stream[i] == str(pos):
                found = i
                break
            if stream[i].casefold() == "propozycje":
                break
        if found is None:
            break
        values: list[str] = []
        j = found + 1
        while j < len(stream):
            v = stream[j].strip()
            low = v.casefold()
            if low == "propozycje":
                break
            if pos < 20 and v == str(pos + 1) and values:
                break
            if low not in NOISE and not low.startswith("image:"):
                values.append(v)
            j += 1
        if len(values) < 2:
            raise ValueError(f"ZET #{pos}: za mało pól: {values!r}")
        entries.append({"position": pos, "artist": values[0], "title": values[1]})
        cursor = j

    if len(entries) < 10:
        raise ValueError(f"ZET: parser odczytał tylko {len(entries)} pozycji")
    return {
        "source": "ZET",
        "chart_date": d.isoformat(),
        "issue_key": d.isoformat(),
        "chart_size": 20,
        "entries": entries,
        "source_url": source_url or "manual:text-copy",
    }


def _fetch_url(url: str, timeout: int = 10) -> tuple[str, str, int]:
    r = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")
    text = soup.get_text("\n", strip=True)
    return text, r.url, r.status_code


def fetch_zet(archive_id: int | None = None, timeout: int = 10) -> dict:
    """Fetch the current public chart or one public archived chart ID."""
    url = CURRENT_URL if archive_id is None else ARCHIVE_URL.format(archive_id=int(archive_id))
    text, final_url, _status = _fetch_url(url, timeout=timeout)
    if archive_id is not None:
        # Invalid archive IDs may redirect to another route. Do not accidentally
        # store the current chart as if it were a historical issue.
        if str(int(archive_id)) not in final_url:
            raise ValueError(f"ZET archive {archive_id}: przekierowanie poza wskazane notowanie")
    data = parse_zet_text(text, source_url=final_url)
    if len(data["entries"]) != 20:
        raise ValueError(f"ZET: oczekiwano 20 pozycji, odczytano {len(data['entries'])}")
    return data


def probe_zet(timeout: int = 10) -> dict:
    try:
        data = fetch_zet(timeout=timeout)
        return {
            "source": "ZET",
            "ok": True,
            "chart_date": data["chart_date"],
            "entries": len(data["entries"]),
            "preview": data["entries"][:5],
            "url": data.get("source_url"),
        }
    except Exception as exc:
        return {"source": "ZET", "ok": False, "error": f"{type(exc).__name__}: {exc}"}
