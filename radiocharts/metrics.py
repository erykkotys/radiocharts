from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, datetime, timedelta

import pandas as pd

from radiocharts.config import load_config
from radiocharts.db import connect, init_db


def rank_score(position: float | None, chart_size: int) -> float:
    if position is None or chart_size <= 0:
        return 0.0
    p = max(1.0, min(float(position), float(chart_size)))
    if chart_size == 1:
        return 100.0
    pct = 1.0 - (p - 1.0) / (chart_size - 1.0)
    return round(100.0 * (pct ** 0.75), 2)


def _week_key(d: date) -> str:
    monday = d - timedelta(days=d.weekday())
    return monday.isoformat()


def _resolve_as_of(as_of: str | date | datetime | None = None) -> date:
    if isinstance(as_of, datetime):
        return as_of.date()
    if isinstance(as_of, date):
        return as_of
    if as_of:
        return date.fromisoformat(str(as_of)[:10])
    init_db()
    with connect() as con:
        row = con.execute("SELECT MAX(chart_date) AS d FROM chart_issues").fetchone()
    if row and row["d"]:
        return date.fromisoformat(str(row["d"])[:10])
    return date.today()


def _load_rows(
    as_of: str | date | datetime | None = None,
    lookback_days: int | None = None,
    song_ids: list[int] | tuple[int, ...] | None = None,
) -> list[dict]:
    init_db()
    end = _resolve_as_of(as_of)
    cutoff = None
    if lookback_days:
        cutoff = end - timedelta(days=max(1, int(lookback_days)) - 1)
    sql = """
        SELECT s.id AS song_id,s.artist,s.title,s.release_date,
               i.source,i.chart_date,i.chart_size,e.position,
               e.reported_weeks,e.reported_peak
        FROM chart_entries e
        JOIN chart_issues i ON i.id=e.issue_id
        JOIN songs s ON s.id=e.song_id
        WHERE i.chart_date <= ?
    """
    params: list[object] = [end.isoformat()]
    if cutoff is not None:
        sql += " AND i.chart_date >= ?"
        params.append(cutoff.isoformat())
    ids = [int(x) for x in (song_ids or [])]
    if ids:
        placeholders = ",".join("?" for _ in ids)
        sql += f" AND s.id IN ({placeholders})"
        params.extend(ids)
    sql += " ORDER BY i.chart_date,e.position"
    with connect() as con:
        rows = con.execute(sql, tuple(params)).fetchall()
        return [dict(r) for r in rows]


def _latest_source_dates(end: date, lookback_days: int | None = None) -> dict[str, str]:
    """Latest stored issue per source in the score window.

    This is separate from the song rows so single-song scoring still knows that
    a track disappeared from a source instead of treating its own last sighting
    as the current issue.
    """
    cutoff = None
    if lookback_days:
        cutoff = end - timedelta(days=max(1, int(lookback_days)) - 1)
    sql = "SELECT source,MAX(chart_date) AS d FROM chart_issues WHERE chart_date<=?"
    params: list[object] = [end.isoformat()]
    if cutoff is not None:
        sql += " AND chart_date>=?"
        params.append(cutoff.isoformat())
    sql += " GROUP BY source"
    init_db()
    with connect() as con:
        return {str(r['source']): str(r['d']) for r in con.execute(sql, tuple(params)).fetchall() if r['d']}


def _source_stats(rows: list[dict], latest_date: str, use_reported_history: bool = True) -> dict:
    weekly: dict[str, dict] = {}
    latest_seen = date.min
    latest_position = None
    local_peak = 10**9
    reported_peak = 10**9
    reported_weeks = 0
    top10_weeks: set[str] = set()

    for r in rows:
        d = date.fromisoformat(str(r["chart_date"])[:10])
        pos = int(r["position"])
        size = int(r["chart_size"])
        wk = _week_key(d)
        bucket = weekly.setdefault(wk, {"sum_pos": 0.0, "n": 0, "size": 0, "date": d})
        bucket["sum_pos"] += pos
        bucket["n"] += 1
        bucket["size"] = max(bucket["size"], size)
        if d > bucket["date"]:
            bucket["date"] = d
        if pos <= 10:
            top10_weeks.add(wk)
        if d > latest_seen:
            latest_seen = d
        if str(r["chart_date"]) == str(latest_date):
            latest_position = pos
        local_peak = min(local_peak, pos)
        if use_reported_history and r.get("reported_peak") is not None:
            try:
                reported_peak = min(reported_peak, int(r["reported_peak"]))
            except Exception:
                pass
        if use_reported_history and r.get("reported_weeks") is not None:
            try:
                reported_weeks = max(reported_weeks, int(r["reported_weeks"]))
            except Exception:
                pass

    ordered = sorted(weekly.values(), key=lambda x: x["date"])
    strengths: list[float] = []
    positions: list[float] = []
    for w in ordered:
        avg = w["sum_pos"] / max(1, w["n"])
        positions.append(avg)
        strengths.append(rank_score(avg, int(w["size"])))

    latest_global = date.fromisoformat(str(latest_date)[:10])
    weeks_since_seen = max(0.0, (latest_global - latest_seen).days / 7.0)
    # Current-strength is useful for trend diagnostics, but familiarity is human
    # memory, not "how hot is the record today". Keep only a very slow memory
    # decay (52-week time constant) so a heavily exposed hit stays familiar for
    # months after it leaves the chart.
    current_recency = math.exp(-weeks_since_seen / 3.0)
    current = (strengths[-1] if strengths else 0.0) * current_recency

    peak_pos = min(local_peak, reported_peak) if reported_peak < 10**9 else local_peak
    chart_size = max(int(r["chart_size"]) for r in rows)
    peak_strength = rank_score(peak_pos, chart_size)
    weeks = max(len(weekly), reported_weeks) if use_reported_history else len(weekly)
    weeks_top10 = len(top10_weeks)
    longevity = min(100.0, weeks / 10.0 * 100.0)
    persistence = min(100.0, weeks_top10 / 6.0 * 100.0)
    memory = peak_strength * math.exp(-weeks_since_seen / 52.0)
    familiarity = 0.35 * peak_strength + 0.30 * longevity + 0.20 * persistence + 0.15 * memory

    # Format fit should describe source/profile affinity, not simply whether the
    # song is still high *today*.  Older builds used ``current_strength`` here,
    # so a song that clearly belonged to RMF/ZET but had just left the charts
    # could collapse to a nonsensical few percent.  Historical fit intentionally
    # has no recency decay: peak + longevity + repeated Top-10 presence are a
    # better proxy for "this is the kind of hit these stations play".
    format_affinity = 0.55 * peak_strength + 0.25 * longevity + 0.20 * persistence

    last4 = strengths[-4:]
    if len(last4) == 1:
        momentum = 50 + 0.35 * last4[-1]
    elif last4:
        delta = last4[-1] - last4[0]
        momentum = 50 + delta * 1.5
        if len(last4) <= 2 and delta > 0:
            momentum += 5
    else:
        momentum = 0
    # Momentum is deliberately current. If the song is no longer present in a
    # source, the old slope rapidly loses relevance even though Familiarity stays.
    momentum *= math.exp(-weeks_since_seen / 2.5)
    momentum = max(0.0, min(100.0, momentum))
    avg4 = sum(positions[-4:]) / max(1, len(positions[-4:])) if positions else 0.0

    return {
        "weeks": int(weeks),
        "weeks_top10": int(weeks_top10),
        "peak": int(peak_pos),
        "latest_position": latest_position,
        "latest_seen": latest_seen.isoformat(),
        "avg4": round(avg4, 1),
        "familiarity": round(familiarity, 1),
        "momentum": round(momentum, 1),
        "current_strength": round(current, 1),
        "format_affinity": round(format_affinity, 1),
    }


def _weekly_source_stats(g: pd.DataFrame, latest_date: str, source: str = "") -> dict:
    """Backward-compatible test/helper wrapper around the pure-Python aggregator."""
    rows = g.to_dict("records")
    return _source_stats(rows, latest_date)


def compute_scores(
    as_of: str | date | datetime | None = None,
    lookback_days: int | None = None,
    song_ids: list[int] | tuple[int, ...] | None = None,
) -> pd.DataFrame:
    """Compute chart-derived scores.

    ``as_of`` makes the calculation historical (used by Notowania).  When
    ``lookback_days`` is set, only observations in that recent window are used
    and lifetime ``reported_weeks/reported_peak`` metadata is intentionally
    ignored, so 1/2/4-week and 2/4/6-month views genuinely describe that period.
    """
    end_date = _resolve_as_of(as_of)
    rows = _load_rows(end_date, lookback_days, song_ids=song_ids)
    if not rows:
        return pd.DataFrame()

    cfg = load_config()
    weights = {k.upper(): float(v) for k, v in cfg.get("weights", {}).items()}
    fit_weights = {k.upper(): float(v) for k, v in cfg.get("format_fit_weights", {}).items()}
    external_sources = ["UK", "BILLBOARD"]
    use_reported_history = not bool(lookback_days)

    latest: dict[str, str] = _latest_source_dates(end_date, lookback_days)
    grouped: dict[int, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    song_meta: dict[int, dict] = {}
    for r in rows:
        sid = int(r["song_id"])
        src = str(r["source"])
        grouped[sid][src].append(r)
        song_meta.setdefault(sid, r)
        if src not in latest:
            latest[src] = str(r["chart_date"])

    available = {s for s in latest if s in weights}
    coverage = sum(weights[s] for s in available)
    weight_den = max(1.0, sum(weights[s] for s in available))
    fit_available = {s for s in latest if s in fit_weights}
    fit_den = max(1.0, sum(fit_weights[s] for s in fit_available))

    out: list[dict] = []
    thresholds = cfg.get("thresholds", {})

    for sid, per_source_rows in grouped.items():
        per = {
            src: _source_stats(src_rows, latest[src], use_reported_history=use_reported_history)
            for src, src_rows in per_source_rows.items()
        }

        fam_num = sum(weights[src] * (per.get(src, {}).get("familiarity", 0.0)) for src in available)
        mom_num = sum(weights[src] * (per.get(src, {}).get("momentum", 0.0)) for src in available)
        familiarity = fam_num / weight_den
        momentum = mom_num / weight_den
        fit = sum(fit_weights[src] * per.get(src, {}).get("format_affinity", 0.0) for src in fit_available) / fit_den

        first = song_meta[sid]
        rel = first.get("release_date") or ""
        first_chart_date = min(
            str(r["chart_date"])[:10]
            for rows_for_source in per_source_rows.values()
            for r in rows_for_source
        )
        age_weeks = None
        if rel:
            try:
                age_weeks = max(0, (end_date - date.fromisoformat(str(rel)[:10])).days // 7)
            except Exception:
                pass
        all_weeks = max((x["weeks"] for x in per.values()), default=0)
        recommendation = "Watch"
        if familiarity >= thresholds.get("current_familiar", 70):
            recommendation = "Current Familiar candidate"
        if momentum >= thresholds.get("rising", 65) and familiarity < thresholds.get("current_familiar", 70):
            recommendation = "Rising / przesłuchaj"
        if familiarity >= thresholds.get("current_familiar", 70) and momentum <= thresholds.get("fading", 40) and all_weeks >= 12:
            recommendation = "Fading / sprawdź recurrent"

        row = {
            "song_id": sid,
            "artist": first["artist"],
            "title": first["title"],
            "release_date": rel,
            "first_chart_date": first_chart_date,
            "age_weeks": age_weeks,
            "familiarity": round(familiarity, 1),
            "momentum": round(momentum, 1),
            "format_fit": round(fit, 1),
            "coverage": round(coverage, 1),
            "recommendation": recommendation,
            "score_as_of": end_date.isoformat(),
            "lookback_days": int(lookback_days or 0),
        }
        for src in list(weights) + external_sources:
            stt = per.get(src)
            row[f"{src}_pos"] = stt["latest_position"] if stt else None
            row[f"{src}_weeks"] = stt["weeks"] if stt else 0
            row[f"{src}_peak"] = stt["peak"] if stt else None
        out.append(row)

    return pd.DataFrame(out).sort_values(["familiarity", "momentum"], ascending=False).reset_index(drop=True)


def song_history(song_id: int) -> pd.DataFrame:
    init_db()
    with connect() as con:
        df = pd.read_sql_query(
            """
            SELECT i.source,i.chart_date,i.chart_size,e.position
            FROM chart_entries e JOIN chart_issues i ON i.id=e.issue_id
            WHERE e.song_id=? ORDER BY i.chart_date
            """,
            con,
            params=(song_id,),
        )
    if df.empty:
        return df
    df["chart_date"] = pd.to_datetime(df["chart_date"])
    return df
