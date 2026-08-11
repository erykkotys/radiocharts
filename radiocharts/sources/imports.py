from __future__ import annotations

import io
import json
import re
from datetime import date
import pandas as pd

COLUMN_ALIASES = {
    "position": ["position", "pozycja", "poz", "miejsce", "rank"],
    "artist": ["artist", "wykonawca", "wykonawcy"],
    "title": ["title", "tytul", "tytuł", "utwor", "utwór"],
    "release_date": ["release_date", "data_premiery", "premiera"],
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", "_", str(s).strip().lower())


def _rename(df: pd.DataFrame) -> pd.DataFrame:
    cols = {_norm(c): c for c in df.columns}
    mapping = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if _norm(alias) in cols:
                mapping[cols[_norm(alias)]] = canonical
                break
    return df.rename(columns=mapping)


def parse_tabular(data: bytes, filename: str) -> pd.DataFrame:
    name = filename.lower()
    if name.endswith(".json"):
        obj = json.loads(data.decode("utf-8-sig"))
        if isinstance(obj, dict):
            for key in ("data", "items", "chart", "entries", "results"):
                if isinstance(obj.get(key), list):
                    obj = obj[key]
                    break
        return _rename(pd.DataFrame(obj))
    if name.endswith((".xlsx", ".xls")):
        return _rename(pd.read_excel(io.BytesIO(data)))
    # sep=None autodetects comma/semicolon/tab
    return _rename(pd.read_csv(io.BytesIO(data), sep=None, engine="python", encoding="utf-8-sig"))


def dataframe_to_issue(df: pd.DataFrame, source: str, chart_date: str, issue_key: str | None = None, chart_size: int | None = None) -> dict:
    df = _rename(df.copy())
    missing = [x for x in ("position", "artist", "title") if x not in df.columns]
    if missing:
        raise ValueError(f"Brak wymaganych kolumn: {', '.join(missing)}")
    df = df.dropna(subset=["position", "artist", "title"]).copy()
    df["position"] = pd.to_numeric(df["position"], errors="coerce")
    df = df.dropna(subset=["position"]).sort_values("position")
    entries = []
    for _, row in df.iterrows():
        e = {"position": int(row["position"]), "artist": str(row["artist"]).strip(), "title": str(row["title"]).strip()}
        if "release_date" in df.columns and pd.notna(row.get("release_date")):
            e["release_date"] = str(row["release_date"])[:10]
        entries.append(e)
    chart_size = int(chart_size or max([e["position"] for e in entries], default=0))
    issue_key = issue_key or f"{source.upper()}-{date.fromisoformat(chart_date).isoformat()}"
    return {"source": source.upper(), "chart_date": date.fromisoformat(chart_date), "issue_key": issue_key, "chart_size": chart_size, "entries": entries}
