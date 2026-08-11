from __future__ import annotations

import math
from collections import defaultdict
from datetime import date
import pandas as pd

from radiocharts.config import load_config
from radiocharts.db import connect, init_db


def rank_score(position: float | None, chart_size: int) -> float:
    if position is None or pd.isna(position) or chart_size <= 0:
        return 0.0
    p = max(1.0, min(float(position), float(chart_size)))
    if chart_size == 1:
        return 100.0
    pct = 1.0 - (p - 1.0) / (chart_size - 1.0)
    # Lekko premiujemy czołówkę, ale zachowujemy informację z całej listy.
    return round(100.0 * (pct ** 0.75), 2)


def _load_entries() -> pd.DataFrame:
    init_db()
    with connect() as con:
        return pd.read_sql_query("""
            SELECT s.id AS song_id,s.artist,s.title,s.release_date,
                   i.source,i.chart_date,i.issue_key,i.chart_size,e.position,
                   e.reported_weeks,e.reported_peak,
                   n.heard,n.status,n.note
            FROM chart_entries e
            JOIN chart_issues i ON i.id=e.issue_id
            JOIN songs s ON s.id=e.song_id
            LEFT JOIN song_notes n ON n.song_id=s.id
            ORDER BY i.chart_date,e.position
        """, con)


def _latest_sources(df: pd.DataFrame) -> dict[str, str]:
    if df.empty: return {}
    return df.groupby("source")["chart_date"].max().to_dict()


def _weekly_source_stats(g: pd.DataFrame, latest_date: str, source: str = "") -> dict:
    g = g.copy()
    g["date"] = pd.to_datetime(g["chart_date"])
    g["week"] = g["date"].dt.to_period("W-SUN").astype(str)
    size = int(g.iloc[-1]["chart_size"])
    weekly = g.groupby("week", as_index=False).agg(position=("position","mean"), chart_size=("chart_size","max"), date=("date","max"))
    weekly["strength"] = weekly.apply(lambda r: rank_score(r.position, int(r.chart_size)), axis=1)
    weekly = weekly.sort_values("date")
    latest_seen = g["date"].max()
    latest_global = pd.Timestamp(latest_date)
    weeks_since_seen = max(0.0, (latest_global-latest_seen).days/7.0)
    recency = math.exp(-weeks_since_seen/3.0)
    current = float(weekly.iloc[-1]["strength"]) * recency

    # The dashboard current-position column must mean *the newest issue of the
    # source*, not "the last position where this song happened to appear".
    # Historical positions still stay in the DB and continue to drive weeks,
    # peak, trend and familiarity.
    latest_issue_rows = g[g["chart_date"].astype(str) == str(latest_date)]
    latest_position = int(latest_issue_rows.iloc[-1]["position"]) if not latest_issue_rows.empty else None
    local_peak = int(g["position"].min())
    reported_peaks = pd.to_numeric(g.get("reported_peak"), errors="coerce").dropna() if "reported_peak" in g else pd.Series(dtype=float)
    reported_weeks = pd.to_numeric(g.get("reported_weeks"), errors="coerce").dropna() if "reported_weeks" in g else pd.Series(dtype=float)
    peak_pos = min(local_peak, int(reported_peaks.min())) if not reported_peaks.empty else local_peak
    peak = rank_score(peak_pos, size)
    local_weeks = int(weekly.shape[0])
    weeks = max(local_weeks, int(reported_weeks.max())) if not reported_weeks.empty else local_weeks
    weeks_top10 = int(g.assign(week=g["date"].dt.to_period("W-SUN").astype(str)).query("position <= 10")["week"].nunique())
    longevity = min(100.0, weeks / 10.0 * 100.0)
    persistence = min(100.0, weeks_top10 / 6.0 * 100.0)
    familiarity = (0.40*current + 0.20*peak + 0.25*longevity + 0.15*persistence)

    last4 = weekly.tail(4)["strength"].tolist()
    if len(last4) == 1:
        momentum = 50 + 0.35 * last4[-1]
    else:
        delta = last4[-1] - last4[0]
        # 20 pkt zmiany rank-strength ~ wyraźny ruch; ograniczamy skrajności.
        momentum = 50 + delta * 1.5
        if len(last4) <= 2 and delta > 0:
            momentum += 5
    momentum = max(0.0, min(100.0, momentum))
    avg4 = float(weekly.tail(4)["position"].mean())
    return {
        "weeks": weeks, "weeks_top10": weeks_top10, "peak": peak_pos,
        "latest_position": latest_position,
        "latest_seen": latest_seen.date().isoformat(), "avg4": round(avg4,1),
        "familiarity": round(familiarity,1), "momentum": round(momentum,1),
        "current_strength": round(current,1),
    }


def compute_scores() -> pd.DataFrame:
    df = _load_entries()
    if df.empty:
        return pd.DataFrame()
    cfg = load_config()
    weights = {k.upper(): float(v) for k,v in cfg.get("weights", {}).items()}
    fit_weights = {k.upper(): float(v) for k,v in cfg.get("format_fit_weights", {}).items()}
    latest = _latest_sources(df)
    available = {s for s in latest if s in weights}
    coverage = sum(weights[s] for s in available)

    external_sources = ["UK", "BILLBOARD"]
    rows = []
    for song_id, sg in df.groupby("song_id"):
        per = {}
        for source, g in sg.groupby("source"):
            per[source] = _weekly_source_stats(g, latest[source], source)

        fam_num = mom_num = 0.0
        weight_den = max(1.0, sum(weights[s] for s in available))
        for source in available:
            w = weights[source]
            stats = per.get(source)
            fam_num += w * (stats["familiarity"] if stats else 0.0)
            # Brak utworu w istniejącym źródle oznacza brak trendu, więc momentum = 0.
            mom_num += w * (stats["momentum"] if stats else 0.0)
        familiarity = fam_num / weight_den
        momentum = mom_num / weight_den

        fit_available = {s for s in latest if s in fit_weights}
        fit_den = max(1.0, sum(fit_weights[s] for s in fit_available))
        fit = 0.0
        for source in fit_available:
            fit += fit_weights[source] * (per.get(source, {}).get("current_strength", 0.0))
        fit /= fit_den

        first = sg.iloc[0]
        rel = first["release_date"]
        age_weeks = None
        if rel:
            try: age_weeks = max(0, (date.today()-date.fromisoformat(rel[:10])).days//7)
            except Exception: pass
        all_weeks = max((x["weeks"] for x in per.values()), default=0)
        status = first["status"] if pd.notna(first["status"]) else "Nie słuchałem"
        heard = bool(first["heard"]) if pd.notna(first["heard"]) else False
        note = first["note"] if pd.notna(first["note"]) else ""
        thresholds = cfg.get("thresholds", {})
        recommendation = "Watch"
        if familiarity >= thresholds.get("current_familiar",70): recommendation = "Current Familiar candidate"
        if momentum >= thresholds.get("rising",65) and familiarity < thresholds.get("current_familiar",70): recommendation = "Rising / przesłuchaj"
        if familiarity >= thresholds.get("current_familiar",70) and momentum <= thresholds.get("fading",40) and all_weeks >= 12: recommendation = "Fading / sprawdź recurrent"

        row = {
            "song_id": int(song_id), "artist": first["artist"], "title": first["title"],
            "release_date": rel or "", "age_weeks": age_weeks,
            "familiarity": round(familiarity,1), "momentum": round(momentum,1), "format_fit": round(fit,1),
            "coverage": round(coverage,1), "recommendation": recommendation,
            "heard": heard, "status": status, "note": note,
        }
        for source in list(weights) + external_sources:
            st = per.get(source)
            row[f"{source}_pos"] = st["latest_position"] if st else None
            row[f"{source}_weeks"] = st["weeks"] if st else 0
            row[f"{source}_peak"] = st["peak"] if st else None
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["familiarity","momentum"], ascending=False).reset_index(drop=True)


def song_history(song_id: int) -> pd.DataFrame:
    init_db()
    with connect() as con:
        df = pd.read_sql_query("""
            SELECT i.source,i.chart_date,i.chart_size,e.position
            FROM chart_entries e JOIN chart_issues i ON i.id=e.issue_id
            WHERE e.song_id=? ORDER BY i.chart_date
        """, con, params=(song_id,))
    if df.empty: return df
    df["chart_date"] = pd.to_datetime(df["chart_date"])
    return df
