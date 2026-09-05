from __future__ import annotations

import math
import os
from datetime import date, datetime, timedelta
from functools import lru_cache
from contextlib import asynccontextmanager
from typing import Any, Iterable, Literal

import pandas as pd
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

from radiocharts.build_info import display_version
from radiocharts.db import (
    airplay_presence_summary,
    airplay_revision,
    airplay_summary,
    airplay_track_detail_by_song,
    canonical_song_id,
    chart_revision,
    connect,
    get_song,
    init_db,
    latest_chart_positions,
    list_airplay_stations,
    list_songs,
    load_notes,
    normalize,
    update_note,
)
from radiocharts.metrics import compute_scores, song_history

API_VERSION = "1"
POPULARITY_CHART_WEIGHTS = {"OLIA": 35.0, "OLIS": 25.0, "RMF": 20.0, "ZET": 12.0, "ESKA": 8.0}
POPULARITY_CHART_SIZES = {"OLIA": 100, "OLIS": 100, "RMF": 20, "ZET": 20, "ESKA": 20}
RADIO_STATUS_BOTTOM_UP = ["CF1", "CF2", "R1", "R2", "G1", "G2", "SP1", "SP2", "NB", "F1"]
RADIO_STATUS_TOP_DOWN = list(reversed(RADIO_STATUS_BOTTOM_UP))
BASE_STATUSES = [f"Baza {code}" for code in RADIO_STATUS_TOP_DOWN]
CANDIDATE_STATUSES = [f"{code} Candidate" for code in RADIO_STATUS_TOP_DOWN]
STATUSES = [
    "Nie słuchałem", "Poza formatem", "Słabe", "Watch",
    *CANDIDATE_STATUSES, "Baza Hold", *BASE_STATUSES,
]
STATUS_ALIASES = {
    "Ignore": "Poza formatem", "Candidate": "CF1 Candidate", "CF Candidate": "CF1 Candidate",
    "Current": "Baza CF2", "Current Familiar": "Baza CF1", "Recurrent": "Baza R1", "Poza bazą": "Baza Hold",
}


def _norm_status(value: Any) -> str:
    raw = str(value or "Nie słuchałem")
    return STATUS_ALIASES.get(raw, raw if raw in STATUSES else "Nie słuchałem")


def _clean(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if isinstance(value, (bool, str, int)):
        return value
    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else round(value, 3)
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if hasattr(value, "item"):
        try:
            return _clean(value.item())
        except Exception:
            pass
    return value


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    return [{str(k): _clean(v) for k, v in row.items()} for row in frame.to_dict(orient="records")]


def _require_token(authorization: str | None = Header(default=None)) -> None:
    token = os.getenv("RADIOCHARTS_API_TOKEN", "").strip()
    if not token:
        return
    if authorization != f"Bearer {token}":
        raise HTTPException(status_code=401, detail="Invalid API token")


def _last_airplay_date() -> date | None:
    init_db()
    with connect() as con:
        row = con.execute("SELECT MAX(substr(played_at,1,10)) AS d FROM airplay_plays").fetchone()
    return date.fromisoformat(str(row["d"])) if row and row["d"] else None


def _parse_date_range(start: date | None, end: date | None, default_days: int = 7) -> tuple[date, date]:
    last = _last_airplay_date() or date.today()
    resolved_end = min(end or last, last)
    resolved_start = start or (resolved_end - timedelta(days=max(1, default_days) - 1))
    if resolved_start > resolved_end:
        resolved_start, resolved_end = resolved_end, resolved_start
    return resolved_start, resolved_end


def _station_ids(raw: str | None) -> list[int]:
    if raw:
        out: list[int] = []
        for part in raw.split(","):
            part = part.strip()
            if part:
                out.append(int(part))
        return sorted(set(out))
    return [int(x["station_id"]) for x in list_airplay_stations(active_only=True)]


@lru_cache(maxsize=8)
def _score_frame_cached(revision: str) -> pd.DataFrame:
    frame = compute_scores()
    return frame.copy(deep=False) if frame is not None else pd.DataFrame()


@lru_cache(maxsize=8)
def _presence_cached(revision: str, days: int) -> dict:
    return airplay_presence_summary(days=days)


def _chart_bonus(frame: pd.DataFrame) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype=float)
    total = max(1.0, sum(POPULARITY_CHART_WEIGHTS.values()))
    out = pd.Series(0.0, index=frame.index)
    for src, weight in POPULARITY_CHART_WEIGHTS.items():
        col = f"{src}_pos"
        if col not in frame.columns:
            continue
        pos = pd.to_numeric(frame[col], errors="coerce")
        size = float(POPULARITY_CHART_SIZES[src])
        strength = (100.0 * (size - pos) / max(1.0, size - 1.0)).clip(0.0, 100.0).fillna(0.0)
        out += float(weight) * strength
    return out / total


def _base_song_frame() -> pd.DataFrame:
    scores = _score_frame_cached(chart_revision()).copy()
    notes = pd.DataFrame(load_notes())
    catalogue = pd.DataFrame(list_songs())
    if scores.empty:
        base = catalogue.copy()
        if base.empty:
            base = pd.DataFrame(columns=["song_id", "artist", "title", "release_date"])
    else:
        base = scores.copy()
        if not catalogue.empty:
            cols = [c for c in ["song_id", "artist", "title", "release_date"] if c in catalogue.columns]
            # score frame already has metadata; catalogue is primarily needed for library-only titles later.
            missing_ids = set(catalogue["song_id"].astype(int)) - set(base["song_id"].astype(int))
            if missing_ids:
                extra = catalogue[catalogue["song_id"].astype(int).isin(missing_ids)][cols].copy()
                base = pd.concat([base, extra], ignore_index=True, sort=False)
    if notes.empty:
        base["heard"] = False
        base["status"] = "Nie słuchałem"
        base["downloaded"] = False
        base["note"] = ""
    else:
        overlay = notes[["song_id", "heard", "status", "downloaded", "note"]].copy()
        base = base.merge(overlay, on="song_id", how="left", suffixes=("", "_note"))
        for col, default in [("heard", False), ("status", "Nie słuchałem"), ("downloaded", False), ("note", "")]:
            base[col] = base[col].fillna(default)
    base["status"] = base["status"].map(_norm_status)
    base["heard"] = base["heard"].fillna(False).astype(bool)
    base["downloaded"] = base["downloaded"].fillna(False).astype(bool)

    presence7 = pd.DataFrame(_presence_cached(airplay_revision(), 7).get("rows") or [])
    if not presence7.empty:
        presence7 = presence7[[c for c in ["song_id", "spins", "radio_reach", "radio_rotation", "radio_presence", "stations_count"] if c in presence7.columns]].copy()
        presence7 = presence7.rename(columns={"spins": "airplay_spins_7d", "stations_count": "stations_7d"})
        base = base.merge(presence7, on="song_id", how="left")
    for col in ["airplay_spins_7d", "radio_reach", "radio_rotation", "radio_presence", "stations_7d"]:
        if col not in base.columns:
            base[col] = 0
        base[col] = pd.to_numeric(base[col], errors="coerce").fillna(0)

    presence28 = pd.DataFrame(_presence_cached(airplay_revision(), 28).get("rows") or [])
    volume = pd.DataFrame(columns=["song_id", "volume_index"])
    if not presence28.empty:
        p = presence28[["song_id", "spins"]].copy()
        p = p[p["song_id"].notna()]
        p["song_id"] = p["song_id"].astype(int)
        p["spins"] = pd.to_numeric(p["spins"], errors="coerce").fillna(0)
        p = p.groupby("song_id", as_index=False)["spins"].sum()
        p["volume_index"] = 0.0
        positive = p["spins"] > 0
        if positive.any():
            p.loc[positive, "volume_index"] = p.loc[positive, "spins"].rank(method="average", pct=True) * 100.0
        volume = p[["song_id", "volume_index"]]
    base = base.merge(volume, on="song_id", how="left")
    base["volume_index"] = pd.to_numeric(base.get("volume_index"), errors="coerce").fillna(0.0)
    base["popularity"] = (0.80 * base["volume_index"] + 0.20 * _chart_bonus(base)).round(1)

    pos_cols = [c for c in ["RMF_pos", "ZET_pos", "ESKA_pos", "OLIA_pos", "OLIS_pos"] if c in base.columns]
    if pos_cols:
        base["avg_position"] = base[pos_cols].apply(pd.to_numeric, errors="coerce").mean(axis=1).round(1)
    else:
        base["avg_position"] = float("nan")
    return base


def _apply_common_filters(frame: pd.DataFrame, search: str, statuses: list[str], downloaded: str) -> pd.DataFrame:
    out = frame
    q = normalize(str(search or "").strip())
    if q:
        artist_key = out["artist"].fillna("").astype(str).map(normalize)
        title_key = out["title"].fillna("").astype(str).map(normalize)
        mask = artist_key.str.contains(q, regex=False) | title_key.str.contains(q, regex=False)
        out = out[mask]
    if statuses:
        out = out[out["status"].isin([_norm_status(x) for x in statuses])]
    if downloaded == "yes":
        out = out[out["downloaded"]]
    elif downloaded == "no":
        out = out[~out["downloaded"]]
    return out.copy()


def _sort_frame(frame: pd.DataFrame, sort: str, descending: bool) -> pd.DataFrame:
    aliases = {
        "popularity": "popularity", "chart_score": "familiarity", "momentum": "momentum",
        "reach7": "radio_reach", "spins7": "airplay_spins_7d", "avg_position": "avg_position",
        "artist": "artist", "title": "title", "status": "status", "spins": "spins",
        "reach": "period_reach", "radio_presence": "period_radio_presence",
    }
    col = aliases.get(sort, "popularity")
    if col not in frame.columns:
        return frame
    na_pos = "last"
    return frame.sort_values(col, ascending=not descending, na_position=na_pos, kind="stable")


def _add_period_airplay(frame: pd.DataFrame, station_ids: list[int], start: date, end: date) -> tuple[pd.DataFrame, int]:
    rows = pd.DataFrame(airplay_summary(station_ids, start, end))
    days = max(1, (end - start).days + 1)
    presence = airplay_presence_summary(station_ids=station_ids, days=days, end_date=end)
    reporting = int(presence.get("reporting_stations") or 0)
    period = pd.DataFrame(presence.get("rows") or [])
    if not period.empty:
        keep = [c for c in ["song_id", "radio_reach", "radio_rotation", "radio_presence"] if c in period.columns]
        period = period[keep].rename(columns={"radio_reach": "period_reach", "radio_rotation": "period_rotation", "radio_presence": "period_radio_presence"})
    if rows.empty:
        rows = pd.DataFrame(columns=["song_id", "spins", "stations_count", "top_station", "last_play"])
    keep_rows = [c for c in ["song_id", "spins", "stations_count", "top_station", "last_play"] if c in rows.columns]
    merged = frame.merge(rows[keep_rows], on="song_id", how="left")
    if not period.empty:
        merged = merged.merge(period, on="song_id", how="left")
    for col in ["spins", "stations_count", "period_reach", "period_rotation", "period_radio_presence"]:
        if col not in merged.columns:
            merged[col] = 0
        merged[col] = pd.to_numeric(merged[col], errors="coerce").fillna(0)
    merged["spins"] = merged["spins"].astype(int)
    merged["stations_count"] = merged["stations_count"].astype(int)
    merged["airplay_per_day"] = (merged["spins"] / days).round(1)
    denom = merged["stations_count"].replace(0, 1) * days
    merged["airplay_per_station_day"] = (merged["spins"] / denom).where(merged["stations_count"] > 0, 0).round(2)
    return merged, reporting


def _song_projection(frame: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "song_id", "artist", "title", "release_date", "heard", "status", "downloaded", "note",
        "popularity", "familiarity", "momentum", "radio_reach", "airplay_spins_7d", "radio_presence",
        "avg_position", "RMF_pos", "RMF_weeks", "ZET_pos", "ZET_weeks", "ESKA_pos", "ESKA_weeks",
        "OLIA_pos", "OLIA_weeks", "OLIS_pos", "OLIS_weeks", "UK_pos", "BILLBOARD_pos",
        "spins", "stations_count", "period_reach", "period_rotation", "period_radio_presence",
        "airplay_per_day", "airplay_per_station_day", "top_station", "last_play",
    ]
    present = [c for c in cols if c in frame.columns]
    return frame[present].copy()


class NotePatch(BaseModel):
    heard: bool
    status: str
    downloaded: bool
    note: str = Field(default="", max_length=10000)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="RadioCharts API",
    version=display_version(),
    description="Private API for the RadioCharts Android client. Intended for LAN/Tailscale use.",
    dependencies=[Depends(_require_token)],
    lifespan=lifespan,
)


@app.get("/api/v1/health")
def health() -> dict[str, Any]:
    last = _last_airplay_date()
    return {"ok": True, "api_version": API_VERSION, "radiocharts_version": display_version(), "last_airplay_date": last.isoformat() if last else None}


@app.get("/api/v1/meta")
def meta() -> dict[str, Any]:
    return {
        "api_version": API_VERSION,
        "radiocharts_version": display_version(),
        "statuses": STATUSES,
        "base_statuses": ["Baza Hold", *BASE_STATUSES],
        "candidate_statuses": CANDIDATE_STATUSES,
        "last_airplay_date": _clean(_last_airplay_date()),
    }


@app.get("/api/v1/stations")
def stations(active_only: bool = True) -> list[dict[str, Any]]:
    return [{k: _clean(v) for k, v in row.items()} for row in list_airplay_stations(active_only=active_only)]


@app.get("/api/v1/songs")
def songs(
    mode: Literal["dashboard", "library", "airplay"] = "dashboard",
    search: str = "",
    statuses: list[str] = Query(default=[]),
    downloaded: Literal["any", "yes", "no"] = "any",
    sort: str = "popularity",
    descending: bool = True,
    start: date | None = None,
    end: date | None = None,
    station_ids: str | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    frame = _base_song_frame()
    if mode == "library":
        frame = frame[frame["status"].isin(["Baza Hold", *BASE_STATUSES])].copy()
    resolved_start = resolved_end = None
    reporting = None
    if mode in {"library", "airplay"} or start or end:
        resolved_start, resolved_end = _parse_date_range(start, end)
        ids = _station_ids(station_ids)
        frame, reporting = _add_period_airplay(frame, ids, resolved_start, resolved_end)
        if mode == "airplay":
            frame = frame[frame["spins"] > 0].copy()
    frame = _apply_common_filters(frame, search, statuses, downloaded)
    frame = _sort_frame(frame, sort, descending)
    total = len(frame)
    page = frame.iloc[offset:offset + limit].copy()
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "start_date": _clean(resolved_start),
        "end_date": _clean(resolved_end),
        "reporting_stations": reporting,
        "items": _records(_song_projection(page)),
    }


@app.get("/api/v1/songs/{song_id}")
def song(song_id: int) -> dict[str, Any]:
    sid = canonical_song_id(song_id)
    raw = get_song(sid)
    if not raw:
        raise HTTPException(status_code=404, detail="Song not found")
    frame = _base_song_frame()
    row = frame[frame["song_id"].astype(int) == sid]
    metrics = _records(_song_projection(row))[0] if not row.empty else {k: _clean(v) for k, v in raw.items()}
    return metrics


@app.patch("/api/v1/songs/{song_id}")
def patch_song(song_id: int, payload: NotePatch) -> dict[str, Any]:
    if payload.status not in STATUSES:
        raise HTTPException(status_code=400, detail="Unknown status")
    sid = canonical_song_id(song_id)
    if not get_song(sid):
        raise HTTPException(status_code=404, detail="Song not found")
    update_note(sid, payload.heard, payload.status, payload.note, downloaded=payload.downloaded)
    return {"ok": True, "song": song(sid)}


@app.get("/api/v1/songs/{song_id}/charts")
def song_charts(song_id: int) -> list[dict[str, Any]]:
    sid = canonical_song_id(song_id)
    frame = song_history(sid)
    return _records(frame)


@app.get("/api/v1/songs/{song_id}/airplay")
def song_airplay(
    song_id: int,
    start: date | None = None,
    end: date | None = None,
    station_ids: str | None = None,
) -> dict[str, Any]:
    resolved_start, resolved_end = _parse_date_range(start, end)
    ids = _station_ids(station_ids)
    detail = airplay_track_detail_by_song(ids, resolved_start, resolved_end, song_id, history_limit=500)
    days = max(1, (resolved_end - resolved_start).days + 1)
    presence = airplay_presence_summary(station_ids=ids, days=days, end_date=resolved_end)
    reporting = int(presence.get("reporting_stations") or 0)
    stations_count = int(detail.get("stations_count") or 0)
    spins = int(detail.get("total_spins") or 0)
    reach = 100.0 * stations_count / reporting if reporting else 0.0
    per_station_day = spins / max(1, stations_count) / days
    rotation = min(100.0, 100.0 * per_station_day / 6.0)
    detail.update({
        "start_date": resolved_start.isoformat(), "end_date": resolved_end.isoformat(), "days": days,
        "reporting_stations": reporting, "period_reach": round(reach, 1), "period_rotation": round(rotation, 1),
        "period_radio_presence": round(0.70 * reach + 0.30 * rotation, 1),
        "airplay_per_day": round(spins / days, 1), "airplay_per_station_day": round(per_station_day, 2),
    })
    return {k: _clean(v) if not isinstance(v, list) else [{kk: _clean(vv) for kk, vv in x.items()} for x in v] for k, v in detail.items()}


@app.get("/")
def root() -> dict[str, str]:
    return {"service": "RadioCharts API", "version": display_version(), "docs": "/docs"}
