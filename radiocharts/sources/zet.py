from __future__ import annotations

import re
from datetime import date

DATE_RE = re.compile(r"Notowanie\s+z\s+dnia\s+(\d{4}-\d{2}-\d{2})", re.I)
NOISE = {"lubię to", "lubie to", "lista przebojów", "lista przebojow", "propozycje"}


def parse_zet_text(text: str, fallback_date: date | None = None) -> dict:
    """Parse text manually copied from the Radio ZET chart page.

    Automatic crawling remains disabled because the publisher explicitly
    reserves text/data-mining rights on the site. This parser only processes
    text supplied by the user in the dashboard.
    """
    lines = [re.sub(r"\s+", " ", x).strip() for x in text.splitlines() if x.strip()]
    joined = "\n".join(lines)
    m = DATE_RE.search(joined)
    d = date.fromisoformat(m.group(1)) if m else (fallback_date or date.today())

    # Anchor at the date when possible; then parse rank -> artist -> title.
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
        "source_url": "manual:text-copy",
    }
