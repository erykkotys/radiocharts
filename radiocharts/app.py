from __future__ import annotations

import html
import json
import math
import re
from datetime import date, datetime, timedelta
from urllib.parse import quote
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.express as px
import streamlit as st
import streamlit.components.v1 as components
from st_aggrid import AgGrid, GridOptionsBuilder, JsCode

from radiocharts.build_info import BUILD_DATE, display_version
from radiocharts.freshness import source_cadence_info
from radiocharts.airplay import completed_windows_in_range
from radiocharts.db import (
    airplay_coverage, airplay_presence_summary, airplay_revision, airplay_song_presence, airplay_station_coverage,
    airplay_summary, airplay_track_detail_by_song, canonical_song_id, chart_archive_summary, chart_revision, get_song, init_db,
    issue_entries, issue_entries_enriched, latest_chart_positions, latest_issues, latest_source_checks,
    source_check_day_summary, list_airplay_stations, list_issues, load_notes, normalize, song_catalog, song_catalog_revision,
    set_airplay_station_active, update_note,
)
from radiocharts.job_manager import active_job, latest_job, read_job_log, start_job, stop_job
from radiocharts.metrics import compute_scores, song_history

st.set_page_config(page_title="RadioCharts Research", page_icon="📻", layout="wide")

# Compact UI: the app is primarily a dense research/table tool, not a dashboard
# made of large presentation cards.
st.markdown(
    """
    <style>
      html { font-size: 16px; }
      [data-testid="stAppViewContainer"] { background: #1b2028; }
      .block-container, [data-testid="stMainBlockContainer"] {
        padding-top: 3.35rem !important;
        padding-bottom: 1.2rem !important;
        max-width: 100% !important;
      }
      [data-testid="stHeader"] { background:#1b2028 !important; height:2.55rem !important; }
      [data-testid="stSidebar"] { display:none !important; }
      h1 { font-size: 1.55rem !important; margin: .15rem 0 .15rem !important; }
      h2 { font-size: 1.35rem !important; margin: .45rem 0 .25rem !important; }
      h3 { font-size: 1.05rem !important; margin: .45rem 0 .2rem !important; }
      p, li, label { line-height: 1.3; }
      [data-testid="stCaptionContainer"] { margin-bottom: .15rem; }
      [data-testid="stMetric"] { padding: .2rem .35rem !important; }
      [data-testid="stMetricLabel"] { font-size: .76rem !important; }
      [data-testid="stMetricValue"] { font-size: 1.35rem !important; line-height: 1.08 !important; }
      [data-testid="stDataFrame"] { font-size: .88rem; }
      .stButton button, .stDownloadButton button, .stLinkButton a {
        min-height: 2.15rem !important; height:auto !important;
        padding: .28rem .52rem !important;
        font-size: .80rem !important; line-height:1.15 !important;
        white-space:normal !important; overflow:visible !important;
      }
      .stButton button p, .stDownloadButton button p, .stLinkButton a p { margin:0 !important; line-height:1.15 !important; }
      div[data-baseweb="select"] > div { min-height: 2.1rem !important; }
      input { min-height: 2rem !important; }
      [data-testid="stWidgetLabel"] p { font-size: .76rem !important; margin-bottom: .08rem !important; line-height:1.18 !important; }
      [data-testid="stForm"] { padding:.55rem .7rem !important; }
      [data-testid="stVerticalBlock"] { gap: .58rem !important; }
      [data-testid="stHorizontalBlock"] { gap: .6rem !important; }
      iframe[title="st.iframe"] { min-height: 0 !important; }
      .rc-app-title { display:flex; align-items:center; gap:.42rem; font-size:1.48rem; font-weight:760; line-height:1.1; margin:0 0 .12rem; min-height:1.75rem; }
      .rc-app-subtitle { color:#9aa3af; font-size:.78rem; margin-bottom:.35rem; }
      .rc-build-badge {
        /* Small release marker immediately to the left of Streamlit's ⋮ menu. */
        position:fixed; top:.56rem; right:3.25rem; z-index:100000;
        color:#aeb6c2; background:rgba(27,32,40,.86);
        border-radius:4px; padding:.10rem .28rem;
        font-size:.68rem; font-weight:550; line-height:1.05; white-space:nowrap;
        pointer-events:none;
      }
      .rc-tabs { display:flex; gap:0; border-bottom:1px solid #4a5260; margin:0 0 .6rem 0; overflow-x:auto; }
      .rc-tabs a { color:#cfd5df; text-decoration:none; padding:.43rem .78rem; border:1px solid transparent; border-bottom:none; border-radius:6px 6px 0 0; white-space:nowrap; font-size:.9rem; }
      .rc-tabs a:hover { background:#2a313d; color:#fff; }
      .rc-tabs a.active { background:#2b323e; color:#fff; border-color:#4a5260; border-bottom:1px solid #2b323e; margin-bottom:-1px; font-weight:650; }
      .rc-metrics { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:.45rem; margin:.15rem 0 .35rem; }
      .rc-metric { border:1px solid #3e4653; border-radius:7px; padding:.38rem .52rem; background:#1d232c; min-width:0; }
      .rc-metric-label { color:#aeb6c2; font-size:.72rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
      .rc-metric-value { color:#f7f8fa; font-size:1.28rem; font-weight:700; line-height:1.1; margin-top:.05rem; }
      .rc-song-title { font-size:1.18rem; font-weight:720; line-height:1.2; margin:.05rem 0 .08rem; }
      .rc-song-meta { color:#9fa8b5; font-size:.78rem; }
      @media (max-width: 640px) {
        .rc-build-badge { display:none; }
        .rc-metrics { grid-template-columns:repeat(2,minmax(0,1fr)); }
      }
    </style>
    """,
    unsafe_allow_html=True,
)

# The Streamlit header forms its own stacking context. A fixed element rendered
# from the main app can therefore sit *behind* the header even with a huge
# z-index. Render the release marker as a pseudo-element of the header itself,
# so it is guaranteed to be in the same top layer as the ⋮ menu.
_rc_version_css = display_version().replace("\\", "\\\\").replace('"', '\\"')
st.markdown(
    f"""
    <style>
      [data-testid="stHeader"] {{ position: relative !important; }}
      [data-testid="stHeader"]::after {{
        content: "{_rc_version_css}";
        position: fixed;
        top: .72rem;
        right: 3.35rem;
        z-index: 2147483647;
        color: #aeb6c2;
        background: rgba(27,32,40,.94);
        border: 1px solid rgba(174,182,194,.15);
        border-radius: 4px;
        padding: .10rem .30rem;
        font-size: .68rem;
        font-weight: 550;
        line-height: 1.05;
        white-space: nowrap;
        pointer-events: none;
      }}
    </style>
    """,
    unsafe_allow_html=True,
)

init_db()


def copyable_json(data: dict, key: str) -> None:
    """Render diagnostics with a visible copy button and a readable pre block."""
    text = json.dumps(data, ensure_ascii=False, indent=2)
    escaped = html.escape(text)
    # execCommand is intentionally used as a fallback because clipboard API can
    # require HTTPS on LAN deployments. The textarea is hidden in the iframe.
    components.html(
        f"""
        <div style="font-family: sans-serif;">
          <button id="copy-{key}" style="padding:7px 12px;cursor:pointer;border-radius:7px;border:1px solid #777;background:#2b313c;color:#f3f4f6;">
            📋 Kopiuj diagnostykę
          </button>
          <span id="msg-{key}" style="margin-left:8px;color:#aab2c0;font-size:13px;"></span>
          <textarea id="txt-{key}" style="position:absolute;left:-9999px;top:-9999px;">{escaped}</textarea>
          <pre style="white-space:pre-wrap;word-break:break-word;background:#11151b;color:#e9edf2;padding:12px;border-radius:8px;font-size:13px;max-height:330px;overflow:auto;">{escaped}</pre>
        </div>
        <script>
          const btn = document.getElementById('copy-{key}');
          const msg = document.getElementById('msg-{key}');
          btn.onclick = async () => {{
            const ta = document.getElementById('txt-{key}');
            let ok = false;
            try {{
              if (navigator.clipboard && window.isSecureContext) {{
                await navigator.clipboard.writeText(ta.value); ok = true;
              }}
            }} catch(e) {{}}
            if (!ok) {{
              ta.style.position = 'fixed'; ta.style.left = '0'; ta.style.top = '0';
              ta.select();
              try {{ ok = document.execCommand('copy'); }} catch(e) {{}}
              ta.style.position = 'absolute'; ta.style.left = '-9999px'; ta.style.top = '-9999px';
            }}
            msg.textContent = ok ? 'Skopiowano' : 'Nie udało się automatycznie — zaznacz tekst poniżej';
            setTimeout(() => msg.textContent = '', 2500);
          }};
        </script>
        """,
        height=440,
        scrolling=False,
    )


def score_columns() -> dict:
    return {
        "familiarity": st.column_config.ProgressColumn(
            "Familiarity", help="Szacowana znajomość utworu.", format="%.0f%%", min_value=0.0, max_value=100.0
        ),
        "momentum": st.column_config.ProgressColumn(
            "Momentum", help="Bieżący trend na listach; szybko wygasa po zejściu z listy.", format="%.0f%%", min_value=0.0, max_value=100.0
        ),
    }


def position_display(value) -> str:
    try:
        if value is None or pd.isna(value):
            return "-"
        return str(int(value))
    except Exception:
        return "-"


def position_sort_value(value) -> int:
    """Numeric value for the grid: missing=999 so native ascending sort puts it last."""
    try:
        if value is None or pd.isna(value):
            return 999
        return int(value)
    except Exception:
        return 999


def position_styler(value) -> str:
    try:
        v = int(value)
        return "-" if v >= 999 else f"{v:02d}"
    except Exception:
        return "-"


def render_compact_metrics(items: list[tuple[str, object]], columns: int | None = None) -> None:
    """Dense metric strip used instead of tall st.metric cards."""
    if not items:
        return
    cols = int(columns or len(items) or 1)
    cards = []
    for label, value in items:
        cards.append(
            '<div class="rc-metric">'
            f'<div class="rc-metric-label">{html.escape(str(label))}</div>'
            f'<div class="rc-metric-value">{html.escape(str(value))}</div>'
            '</div>'
        )
    st.markdown(
        f'<div class="rc-metrics" style="grid-template-columns:repeat({max(1, cols)},minmax(0,1fr))">'
        + ''.join(cards) + '</div>',
        unsafe_allow_html=True,
    )


AIRPLAY_QUICK_RANGES = [
    "Ostatni tydzień",
    "Ostatnie 2 tyg.",
    "Ostatni miesiąc",
    "Ostatnie 3 miesiące",
    "Ostatnie pół roku",
    "Ostatni rok",
    "Własny zakres",
]


def _subtract_months(anchor: date, months: int) -> date:
    """Calendar-month subtraction without an extra dependency."""
    months = max(0, int(months))
    total = anchor.year * 12 + (anchor.month - 1) - months
    year, month0 = divmod(total, 12)
    month = month0 + 1
    # clamp the day to the destination month's last valid day
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    last_day = (next_month - timedelta(days=1)).day
    return date(year, month, min(anchor.day, last_day))


def airplay_quick_range(preset: str, end_date: date, earliest: date | None = None) -> tuple[date, date]:
    """Resolve a compact preset to an inclusive date range."""
    label = str(preset or "")
    if label == "Ostatni tydzień":
        start = end_date - timedelta(days=6)
    elif label == "Ostatnie 2 tyg.":
        start = end_date - timedelta(days=13)
    elif label == "Ostatni miesiąc":
        start = _subtract_months(end_date, 1) + timedelta(days=1)
    elif label == "Ostatnie 3 miesiące":
        start = _subtract_months(end_date, 3) + timedelta(days=1)
    elif label == "Ostatnie pół roku":
        start = _subtract_months(end_date, 6) + timedelta(days=1)
    elif label == "Ostatni rok":
        start = _subtract_months(end_date, 12) + timedelta(days=1)
    else:
        start = end_date - timedelta(days=6)
    if earliest is not None and start < earliest:
        start = earliest
    if start > end_date:
        start = end_date
    return start, end_date


def render_airplay_range_picker(
    *,
    key_prefix: str,
    default_end: date,
    earliest: date | None = None,
    default_preset: str = "Ostatni tydzień",
) -> tuple[date, date]:
    """Compact preset dropdown; exact date picker appears only for custom range."""
    try:
        default_idx = AIRPLAY_QUICK_RANGES.index(default_preset)
    except ValueError:
        default_idx = 0
    c1, c2 = st.columns([1.05, 2.2])
    preset = c1.selectbox(
        "Zakres dat",
        AIRPLAY_QUICK_RANGES,
        index=default_idx,
        key=f"{key_prefix}_preset",
    )
    if preset == "Własny zakres":
        default_start, _ = airplay_quick_range("Ostatni tydzień", default_end, earliest)
        selected = c2.date_input(
            "Daty",
            value=(default_start, default_end),
            key=f"{key_prefix}_custom",
            help="Zakres jest inkluzywny.",
        )
        if isinstance(selected, (list, tuple)) and len(selected) == 2:
            start, end = selected
        else:
            start = end = selected if isinstance(selected, date) else default_end
        if end < start:
            start, end = end, start
        if earliest is not None and start < earliest:
            start = earliest
        return start, end
    start, end = airplay_quick_range(preset, default_end, earliest)
    c2.markdown(
        f'<div style="padding-top:1.45rem;color:#aeb6c2;font-size:.78rem">'
        f'{html.escape(start.isoformat())} → {html.escape(end.isoformat())}</div>',
        unsafe_allow_html=True,
    )
    return start, end


def song_link(song_id: int, title: str | None = None) -> str:
    """Relative URL to the song detail view (compatible with LinkColumn)."""
    return f"?view=song&song={int(song_id)}"


@st.cache_resource(show_spinner=False, max_entries=32)
def cached_scores(revision: str, as_of: str = "", lookback_days: int = 0) -> pd.DataFrame:
    # revision invalidates cache when chart data changes; timeframe arguments
    # let Dashboard and historical Notowania reuse their own cached calculations.
    return compute_scores(as_of=as_of or None, lookback_days=lookback_days or None)


def clear_score_cache() -> None:
    cached_scores.clear()
    cached_song_score.clear()
    cached_song_history.clear()


@st.cache_resource(show_spinner=False, max_entries=128)
def cached_song_score(revision: str, song_id: int) -> pd.DataFrame:
    return compute_scores(song_ids=[int(song_id)])


@st.cache_resource(show_spinner=False, max_entries=256)
def cached_song_history(revision: str, song_id: int) -> pd.DataFrame:
    return song_history(int(song_id))


@st.cache_resource(show_spinner=False, max_entries=4)
def cached_song_catalog(revision: str) -> pd.DataFrame:
    return pd.DataFrame(song_catalog())


@st.cache_resource(show_spinner=False, max_entries=24)
def cached_airplay_summary(revision: str, station_key: tuple[int, ...], start_iso: str, end_iso: str) -> list[dict]:
    return airplay_summary(station_key, start_iso, end_iso)


@st.cache_resource(show_spinner=False, max_entries=64)
def cached_airplay_track_detail(revision: str, station_key: tuple[int, ...], start_iso: str, end_iso: str, song_id: int) -> dict:
    return airplay_track_detail_by_song(station_key, start_iso, end_iso, int(song_id))


@st.cache_resource(show_spinner=False, max_entries=8)
def cached_airplay_presence(revision: str, days: int = 7) -> dict:
    return airplay_presence_summary(days=days)


@st.cache_resource(show_spinner=False, max_entries=128)
def cached_airplay_song_presence(revision: str, song_id: int, days: int = 7) -> dict:
    return airplay_song_presence(int(song_id), days=days)


def radio_presence_frame(days: int = 7) -> tuple[pd.DataFrame, dict]:
    snapshot = cached_airplay_presence(airplay_revision(), days)
    rows = pd.DataFrame(snapshot.get("rows") or [])
    return rows, snapshot


def with_radio_presence(frame: pd.DataFrame, days: int = 7) -> pd.DataFrame:
    out = frame.copy()
    if out.empty or "song_id" not in out.columns:
        return out
    presence, meta = radio_presence_frame(days)
    reporting = int(meta.get("reporting_stations") or 0)
    cols = [
        "song_id", "radio_presence", "radio_reach", "radio_rotation", "stations_count", "airplay_spins_per_day",
        "airplay_spins_per_station_day", "last_play",
    ]
    if not presence.empty:
        ref = presence[[c for c in cols if c in presence.columns]].drop_duplicates("song_id")
        ref = ref.rename(columns={
            "stations_count": "airplay_stations_count",
            "last_play": "airplay_last_play",
        })
        out = out.merge(ref, on="song_id", how="left")
    for col in ["radio_presence", "radio_reach", "radio_rotation", "airplay_spins_per_day", "airplay_spins_per_station_day"]:
        if col not in out.columns:
            out[col] = 0.0 if reporting else float("nan")
        elif reporting:
            out[col] = out[col].fillna(0.0)
    if "airplay_stations_count" not in out.columns:
        out["airplay_stations_count"] = 0
    elif reporting:
        out["airplay_stations_count"] = out["airplay_stations_count"].fillna(0).astype(int)
    out["airplay_reporting_stations"] = reporting
    out["airplay_presence_days"] = int(meta.get("days") or days)
    return out


def source_health_frame() -> tuple[pd.DataFrame, list[str]]:
    """Fetch health plus expected publication cadence for every chart source."""
    sources = ["RMF", "ZET", "OLIA", "OLIS", "ESKA", "UK", "BILLBOARD"]
    issues = {str(x["source"]): x for x in latest_issues()}
    latest = {str(x["source"]): x for x in latest_source_checks()}
    daily = {str(x["source"]): x for x in source_check_day_summary()}
    tz = ZoneInfo("Europe/Warsaw")
    now_local = datetime.now(tz)
    today = now_local.date()
    rows = []
    problems: list[str] = []

    def fmt_local(value) -> str:
        if not value:
            return "—"
        try:
            return datetime.fromisoformat(str(value)).astimezone(tz).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return "—"

    for src in sources:
        issue = issues.get(src)
        last = latest.get(src)
        day = daily.get(src)
        success_today = bool(day and day.get("success_today"))
        attempted_today = bool(day and day.get("attempted_today"))
        cadence, expected_date = source_cadence_info(src, now_local)
        issue_date = None
        if issue and issue.get("chart_date"):
            try:
                issue_date = date.fromisoformat(str(issue.get("chart_date")))
            except Exception:
                issue_date = None
        issue_fresh = bool(issue_date and issue_date >= expected_date)

        if issue is None:
            status = "❌ brak danych"
            problems.append(src)
        elif success_today:
            status = "✅ pobrano dziś"
        elif attempted_today:
            status = "❌ dziś bez udanego pobrania"
            problems.append(src)
        else:
            status = "⚠️ nie sprawdzono dziś"
            problems.append(src)
        freshness = "✅ aktualne" if issue_fresh else ("⚠️ starsze niż oczekiwane" if issue else "—")

        if success_today:
            shown_at = day.get("latest_success_at")
            shown_message = str(day.get("latest_success_message") or "")
            attempts = int(day.get("attempts_today") or 0)
            successes = int(day.get("successes_today") or 0)
            if attempts > successes:
                shown_message = (shown_message + f" · dziś: {successes}/{attempts} prób udanych").strip(" ·")
        else:
            shown_at = last.get("checked_at") if last else None
            shown_message = str(last.get("message") or "") if last else ""

        rows.append({
            "Źródło": src,
            "Publikacja": cadence,
            "Najnowsze pobrane": str(issue.get("chart_date")) if issue else "—",
            "Powinno być ≥": expected_date.isoformat(),
            "Aktualność daty": freshness,
            "Stan pobrania": status,
            "Pozycji": int(issue.get("entries") or 0) if issue else 0,
            "Ostatni sukces / próba": fmt_local(shown_at),
            "Komunikat": shown_message[-180:] if shown_message else "",
        })
    return pd.DataFrame(rows), problems


def render_nav_tabs(current: str) -> None:
    tabs = [
        ("dashboard", "Dashboard"),
        ("song", "Utwór"),
        ("archive", "Notowania"),
        ("airplay", "Emisje"),
        ("data", "Dane"),
        ("methodology", "Manual"),
    ]
    links = []
    for key, label in tabs:
        cls = "active" if key == current else ""
        extra = ""
        if key == "song" and st.query_params.get("song"):
            extra = f"&song={st.query_params.get('song')}"
        links.append(
            f'<a class="{cls}" href="?view={key}{extra}" target="_self" '
            f'onclick="window.location.assign(this.href); return false;">{label}</a>'
        )
    st.markdown('<div class="rc-tabs">' + ''.join(links) + '</div>', unsafe_allow_html=True)



st.markdown('<div class="rc-app-title">📻 <span>RadioCharts Research</span></div>', unsafe_allow_html=True)
st.markdown('<div class="rc-app-subtitle">Familiarity, momentum i radio presence · wsparcie odsłuchu i ręcznej decyzji</div>', unsafe_allow_html=True)

STATUSES = [
    "Nie słuchałem",
    "Watch",
    "R1 Candidate",
    "CF Candidate",
    "Baza Hold",
    "Słabe",
    "Baza R2",
    "Baza R1",
    "Baza CF2",
    "Baza CF1",
    "Poza formatem",
]

STATUS_ALIASES = {
    "Ignore": "Poza formatem",
    "Candidate": "CF Candidate",
    "Current": "Baza CF2",
    "Current Familiar": "Baza CF1",
    "Recurrent": "Baza R1",
    "Poza bazą": "Baza Hold",
}

def normalized_status(value: str | None) -> str:
    raw = str(value or "Nie słuchałem")
    return STATUS_ALIASES.get(raw, raw if raw in STATUSES else "Nie słuchałem")


def release_month(exact_release: object = None, first_chart: object = None) -> str:
    """YYYY/MM. A leading ~ means first chart appearance, not an exact release date."""
    raw = str(exact_release or "").strip()
    if raw and raw.lower() not in {"nan", "none", "nat"}:
        m = re.match(r"^(\d{4})-(\d{2})", raw)
        if m:
            return f"{m.group(1)}/{m.group(2)}"
    raw = str(first_chart or "").strip()
    if raw and raw.lower() not in {"nan", "none", "nat"}:
        m = re.match(r"^(\d{4})-(\d{2})", raw)
        if m:
            return f"~{m.group(1)}/{m.group(2)}"
    return "—"


def with_notes(frame: pd.DataFrame) -> pd.DataFrame:
    """Overlay live user state without invalidating expensive score caches."""
    out = frame.copy()
    if out.empty:
        return out
    note_rows = load_notes()
    if note_rows:
        notes_df = pd.DataFrame(note_rows).set_index("song_id")
        ids = out["song_id"].astype(int)
        out["heard"] = [bool(notes_df.at[i, "heard"]) if i in notes_df.index else False for i in ids]
        out["status"] = [normalized_status(notes_df.at[i, "status"]) if i in notes_df.index else "Nie słuchałem" for i in ids]
        out["note"] = [str(notes_df.at[i, "note"] or "") if i in notes_df.index else "" for i in ids]
    else:
        out["heard"] = False
        out["status"] = "Nie słuchałem"
        out["note"] = ""
    return out


def spotify_search_url(artist: str, title: str) -> str:
    query = quote(f"{artist} {title}", safe="")
    return f"https://open.spotify.com/search/{query}"


def filter_song_rows(frame: pd.DataFrame, query: str) -> pd.DataFrame:
    """Accent-insensitive artist/title filtering; every typed token must match."""
    q = normalize(str(query or ""))
    if frame.empty or not q:
        return frame
    tokens = [x for x in q.split() if x]
    artist = frame["artist"].astype(str) if "artist" in frame.columns else pd.Series("", index=frame.index)
    title = frame["title"].astype(str) if "title" in frame.columns else pd.Series("", index=frame.index)
    hay = (artist + " " + title).map(normalize)
    mask = pd.Series(True, index=frame.index)
    for token in tokens:
        mask &= hay.str.contains(re.escape(token), regex=True, na=False)
    return frame[mask]


def _accent_alias_tokens(text: str) -> str:
    """Short ASCII aliases so native selectbox search finds Polish spelling."""
    aliases: list[str] = []
    for raw in re.findall(r"[^\s—–,()/]+", str(text or "")):
        folded = normalize(raw)
        # Only expose an alias when folding actually changed a word.
        ascii_raw = re.sub(r"[^a-z0-9]+", "", raw.casefold())
        if folded and folded != ascii_raw and folded not in aliases:
            aliases.append(folded)
    return ", ".join(aliases[:6])


def render_song_picker(frame: pd.DataFrame, selected_id: int) -> int:
    """One native searchable dropdown — same interaction as Emisje."""
    if frame.empty:
        return int(selected_id)
    ids = [int(x) for x in frame["song_id"].tolist()]
    labels: dict[int, str] = {}
    for r in frame.itertuples(index=False):
        base = f"{r.artist} — {r.title}"
        alias = _accent_alias_tokens(base)
        labels[int(r.song_id)] = base + (f"  [{alias}]" if alias else "")
    try:
        index = ids.index(int(selected_id))
    except (ValueError, TypeError):
        index = 0
    return int(st.selectbox(
        "Znajdź utwór", ids, index=index,
        format_func=lambda sid: labels.get(int(sid), str(sid)),
        key="song_picker_single_v4",
        help="Kliknij i zacznij pisać. Podpowiedzi pojawiają się od razu; np. „meskie” znajduje „Męskie”.",
    ))

def navigate_to_song(song_id: int) -> None:
    """Server-side navigation used by AG Grid and native selectors."""
    st.session_state["_rc_song_scroll_top"] = True
    st.query_params["view"] = "song"
    st.query_params["song"] = str(int(song_id))
    st.rerun()


def scroll_song_to_top_once() -> None:
    """Undo browser/component scroll restoration after opening a song row."""
    if not st.session_state.pop("_rc_song_scroll_top", False):
        return
    components.html(
        """
        <script>
          function rcTop() {
            try { window.parent.scrollTo(0, 0); } catch(e) {}
            try { window.parent.document.documentElement.scrollTop = 0; } catch(e) {}
            try { window.parent.document.body.scrollTop = 0; } catch(e) {}
          }
          rcTop();
          setTimeout(rcTop, 40);
          setTimeout(rcTop, 160);
        </script>
        """,
        height=1,
        scrolling=False,
    )



DETAILS_LABEL_FORMATTER = JsCode("""
function(params) {
  const sid = String((params.data || {}).song_id || '');
  return sid ? 'Otwórz' : '-';
}
""")

SPOTIFY_COPY_FORMATTER = JsCode("""
function(params) {
  return String(params.value || '') ? '⧉' : '-';
}
""")

SPOTIFY_LABEL_FORMATTER = JsCode("""
function(params) {
  const url = String(params.value || '');
  return url ? 'Spotify ↗' : '-';
}
""")

PREVIEW_LABEL_FORMATTER = JsCode("""
function(params) {
  return '▶ 30s';
}
""")

SOURCE_POSITION_FORMATTER = JsCode("""
function(params) {
  const field = String((params.colDef && params.colDef.field) || '');
  const v = Number(params.value);
  if (!isFinite(v) || v >= 999) return '-';

  const weekField = field + '_weeks';
  let weekColumn = null;
  try {
    if (params.api && params.api.getColumn) weekColumn = params.api.getColumn(weekField);
    else if (params.columnApi && params.columnApi.getColumn) weekColumn = params.columnApi.getColumn(weekField);
  } catch(e) {}
  const compact = !!(weekColumn && weekColumn.isVisible && !weekColumn.isVisible());
  if (!compact) return String(Math.round(v));

  const weeks = Number((params.data || {})[weekField] || 0);
  const weekLabel = weeks > 0 ? (Math.round(weeks) + 'w') : '–';
  return '#' + Math.round(v) + ' · ' + weekLabel;
}
""")

AVERAGE_POSITION_FORMATTER = JsCode("""
function(params) {
  const v = Number(params.value);
  if (!isFinite(v) || v >= 999) return '-';
  return v.toFixed(1);
}
""")

GRID_CLICK_HANDLER = JsCode("""
function(params) {
  const field = params && params.colDef ? params.colDef.field : null;
  const row = params && params.data ? params.data : {};
  const host = window.top || window;
  const ev = (params && params.event) ? params.event : {};

  if (field === 'details') {
    const sid = String(row.song_id || '');
    if (!sid) return;
    const url = window.location.origin + '/?view=song&song=' + encodeURIComponent(sid) + '#rc-song-top';
    if (ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.button === 1) {
      try { window.open(url, '_blank', 'noopener,noreferrer'); } catch(e) {}
      return;
    }
    // Same-tab navigation is returned to Streamlit through a hidden editable
    // field. This avoids trying to navigate the component iframe itself.
    try { params.node.setDataValue('_open_request', sid); } catch(e) {}
    return;
  }

  if (field === 'spotify') {
    const raw = String(row.spotify || params.value || '');
    if (!raw) return;
    try { host.open(raw, '_blank', 'noopener,noreferrer'); } catch(e) {}
    return;
  }

  if (field === 'spotify_copy') {
    const raw = String(row.spotify_copy || row.spotify || '');
    if (!raw) return;
    try {
      const doc = host.document || document;
      const ta = doc.createElement('textarea');
      ta.value = raw;
      ta.setAttribute('readonly', '');
      ta.style.position = 'fixed';
      ta.style.left = '-9999px';
      doc.body.appendChild(ta);
      ta.select();
      let copied = false;
      try { copied = doc.execCommand('copy'); } catch(e) {}
      doc.body.removeChild(ta);
      if (!copied && host.navigator && host.navigator.clipboard) {
        host.navigator.clipboard.writeText(raw).catch(() => {});
      }
    } catch(e) {}
    return;
  }

  if (field !== 'preview') return;
  try {
    if (typeof host.__rcPlayPreview === 'function') {
      host.__rcPlayPreview({
        songId: String(row.song_id || (row.artist || '') + '|' + (row.title || '')),
        artist: String(row.artist || ''),
        title: String(row.title || ''),
        spotify: String(row.spotify || '')
      });
    }
  } catch(e) {}
}
""")

GRID_SHOULD_RETURN = JsCode("""
function(params) {
  const trigger = String((params && params.streamlitRerunEventTriggerName) || '');
  return trigger === 'cellValueChanged';
}
""")


def install_client_helpers() -> None:
    """Install hard-navigation/back-button support and one page-level preview player.

    The AG Grid lives inside a component iframe.  The player is deliberately
    created in the top document, so it is fixed to the bottom of the browser
    viewport rather than the bottom of the table iframe.
    """
    components.html(
        r"""
        <script>
        (() => {
          let host = window.top || window;
          let doc = document;
          try { doc = host.document; } catch(e) { host = window; doc = document; }

          if (!host.__rcBackReloadInstalled) {
            host.__rcBackReloadInstalled = true;
            host.addEventListener('popstate', function() {
              // Streamlit does not always rerun when only query params change via
              // browser history. Force a real reload on Back/Forward.
              setTimeout(() => { try { host.location.reload(); } catch(e) {} }, 0);
            });
          }

          if (typeof host.__rcPlayPreview === 'function') return;

          const norm = (x) => String(x || '')
            .toLowerCase()
            .replace(/ł/g,'l')
            .normalize('NFD')
            .replace(/[\u0300-\u036f]/g,'')
            .replace(/[^a-z0-9]+/g,' ')
            .trim();

          const ensurePlayer = () => {
            let wrap = doc.getElementById('__rcFloatingPlayer');
            if (wrap) return wrap;
            wrap = doc.createElement('div');
            wrap.id = '__rcFloatingPlayer';
            wrap.style.cssText = [
              'display:none','position:fixed','left:50%','bottom:24px','transform:translateX(-50%)',
              'z-index:2147483000','width:min(760px,calc(100vw - 36px))','box-sizing:border-box',
              'background:rgba(22,27,35,.985)','border:1px solid rgba(160,175,195,.42)',
              'border-radius:11px','box-shadow:0 -8px 28px rgba(0,0,0,.44)',
              'padding:6px 10px 6px','font-family:system-ui,-apple-system,Segoe UI,sans-serif','color:#f4f6f8'
            ].join(';');
            wrap.innerHTML = `
              <div style="display:flex;align-items:center;gap:10px;margin-bottom:3px">
                <div id="__rcPlayerTitle" style="min-width:0;flex:1;font-size:13px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">Podgląd</div>
                <a id="__rcPlayerSpotify" href="#" target="_blank" rel="noopener noreferrer" style="font-size:12px;color:#d7f9df;text-decoration:none;white-space:nowrap">Spotify ↗</a>
                <button id="__rcPlayerClose" type="button" aria-label="Zamknij" style="border:0;background:transparent;color:#fff;font-size:22px;cursor:pointer;line-height:1;padding:0 3px">×</button>
              </div>
              <audio id="__rcPlayerAudio" controls preload="metadata" style="display:block;width:100%;height:32px"></audio>
              <div id="__rcPlayerStatus" style="display:none"></div>`;
            doc.body.appendChild(wrap);
            const audio = wrap.querySelector('#__rcPlayerAudio');
            wrap.querySelector('#__rcPlayerClose').addEventListener('click', function(ev) {
              ev.stopPropagation();
              try { audio.pause(); audio.currentTime = 0; } catch(e) {}
              wrap.style.display = 'none';
              host.__rcPreviewSongId = null;
            });
            return wrap;
          };

          host.__rcPlayPreview = function(info) {
            info = info || {};
            const songId = String(info.songId || (info.artist || '') + '|' + (info.title || ''));
            const artist = String(info.artist || '');
            const title = String(info.title || '');
            const spotify = String(info.spotify || '');
            if (!artist && !title) return;

            const player = ensurePlayer();
            const audio = player.querySelector('#__rcPlayerAudio');
            player.style.display = 'block';

            if (host.__rcPreviewSongId === songId && audio.src) {
              if (audio.paused) {
                const pr = audio.play();
                if (pr && pr.catch) pr.catch(() => {});
              } else {
                audio.pause();
              }
              return;
            }

            try { audio.pause(); } catch(e) {}
            audio.removeAttribute('src');
            audio.load();
            host.__rcPreviewSongId = songId;
            player.querySelector('#__rcPlayerTitle').textContent = (artist && title) ? (artist + ' — ' + title) : (title || artist || 'Podgląd');
            const spot = player.querySelector('#__rcPlayerSpotify');
            if (spotify) { spot.href = spotify; spot.style.display = ''; }
            else { spot.style.display = 'none'; }
            player.querySelector('#__rcPlayerStatus').textContent = 'Szukam podglądu…';

            const cb = '__rcPreviewCB_' + Date.now() + '_' + Math.floor(Math.random()*1000000);
            const script = doc.createElement('script');
            const cleanup = () => {
              try { delete host[cb]; } catch(e) {}
              try { script.remove(); } catch(e) {}
            };
            host[cb] = function(payload) {
              try {
                if (host.__rcPreviewSongId !== songId) return;
                const results = (payload && payload.results ? payload.results : []).filter(x => x.previewUrl);
                const nt = norm(title), na = norm(artist);
                let best = null, bestScore = -1;
                for (const r of results) {
                  const rt = norm(r.trackName), ra = norm(r.artistName);
                  let score = 0;
                  if (rt === nt) score += 10;
                  if (nt && (rt.includes(nt) || nt.includes(rt))) score += 4;
                  const artistTokens = na.split(' ').filter(x => x.length > 2);
                  score += artistTokens.filter(t => ra.includes(t)).length;
                  if (score > bestScore) { best = r; bestScore = score; }
                }
                if (!best) {
                  player.querySelector('#__rcPlayerStatus').textContent = 'Brak 30-sekundowego podglądu dla tego utworu.';
                  return;
                }
                audio.src = best.previewUrl;
                audio.load();
                player.querySelector('#__rcPlayerStatus').textContent = '30-sekundowy podgląd Apple/iTunes · możesz przewijać suwakiem';
                const promise = audio.play();
                if (promise && promise.catch) promise.catch(() => {});
              } finally {
                cleanup();
              }
            };
            script.onerror = function() {
              if (host.__rcPreviewSongId === songId) player.querySelector('#__rcPlayerStatus').textContent = 'Nie udało się pobrać podglądu.';
              cleanup();
            };
            const term = encodeURIComponent(artist + ' ' + title);
            script.src = 'https://itunes.apple.com/search?term=' + term + '&country=PL&media=music&entity=song&limit=5&callback=' + cb;
            doc.body.appendChild(script);
          };
        })();
        </script>
        """,
        height=1,
        scrolling=False,
    )


def render_preview_button(song_id: int | str, artist: str, title: str, spotify: str) -> None:
    payload = json.dumps({
        "songId": str(song_id), "artist": str(artist), "title": str(title), "spotify": str(spotify),
    }, ensure_ascii=False).replace("<", "\\u003c")
    components.html(
        f"""
        <style>
          body {{ margin:0; background:transparent; font-family:system-ui,-apple-system,Segoe UI,sans-serif; }}
          button {{ width:100%; height:38px; border:1px solid #596272; border-radius:7px; background:#2a313d; color:#f1f4f7; font-weight:650; cursor:pointer; }}
          button:hover {{ background:#343d4b; }}
        </style>
        <button id="play">▶ Odsłuch 30s</button>
        <script>
          const info = {payload};
          document.getElementById('play').addEventListener('click', function() {{
            try {{ if (window.top && typeof window.top.__rcPlayPreview === 'function') window.top.__rcPlayPreview(info); }} catch(e) {{}}
          }});
        </script>
        """,
        height=42,
        scrolling=False,
    )

@st.fragment
def render_song_note_editor(song_id: int, heard_value: bool, status_value: str, note_value: str) -> None:
    """Small fragment so editing one song does not rerun/repaint the whole detail page."""
    with st.container(border=True):
        with st.form(f"note_form_{song_id}"):
            n1, n2, n3, n4 = st.columns([1.0, 1.5, 4.8, .8])
            heard = n1.checkbox("Przesłuchany", value=bool(heard_value))
            current_status = normalized_status(status_value)
            idx = STATUSES.index(current_status) if current_status in STATUSES else 0
            status = n2.selectbox("Status", STATUSES, index=idx)
            note = n3.text_input("Notatka", value=note_value or "")
            with n4:
                st.caption("Zapis")
                save_note = st.form_submit_button("Zapisz", use_container_width=True)
            if save_note:
                update_note(song_id, heard, status, note)
                st.toast("Zapisano")


PERCENT_FORMATTER = JsCode("""
function(params) {
  if (params.value === null || params.value === undefined || isNaN(params.value)) return '-';
  return Math.round(Number(params.value)) + '%';
}
""")

POSITION_FORMATTER = JsCode("""
function(params) {
  const v = Number(params.value);
  if (!isFinite(v) || v >= 999) return '-';
  return String(Math.round(v));
}
""")


@st.fragment
def render_song_grid(
    frame: pd.DataFrame,
    *,
    key: str,
    height: int = 640,
    editable_state: bool = True,
    source_layout: str = "full",
    station_total: int | None = None,
) -> pd.DataFrame:
    """AG Grid table: row highlight, editing, responsive source columns and preview player."""
    show = frame.copy()
    if show.empty:
        st.info("Brak utworów do pokazania.")
        return show
    if "preview" not in show.columns:
        show["preview"] = "▶"
    if "details" in show.columns:
        show["_open_request"] = ""

    gb = GridOptionsBuilder.from_dataframe(show)
    gb.configure_default_column(resizable=True, sortable=True, filter=True, editable=False)
    gb.configure_selection(selection_mode="single", use_checkbox=False, suppressRowClickSelection=False)
    gb.configure_grid_options(rowHeight=36, animateRows=False, onCellClicked=GRID_CLICK_HANDLER)

    if "song_id" in show.columns:
        gb.configure_column("song_id", hide=True)
    if "_open_request" in show.columns:
        gb.configure_column("_open_request", hide=True, editable=False)
    pin_identity = source_layout in {"auto", "compact", "airplay"}
    if "artist" in show.columns:
        gb.configure_column("artist", "Wykonawca", minWidth=170 if pin_identity else 190, width=205 if pin_identity else 220, pinned="left" if pin_identity else None)
    if "title" in show.columns:
        gb.configure_column("title", "Tytuł", minWidth=185 if pin_identity else 210, width=235 if pin_identity else 260, pinned="left" if pin_identity else None)
    if "release_month" in show.columns:
        gb.configure_column(
            "release_month", "Premiera", minWidth=86, width=92,
            headerTooltip="YYYY/MM; ~YYYY/MM = miesiąc pierwszego pojawienia się w naszych notowaniach, gdy brak dokładnej daty premiery.",
        )
    if "avg_position" in show.columns:
        gb.configure_column(
            "avg_position", "Śr. poz.", minWidth=82, width=88,
            headerTooltip="Średnia arytmetyczna bieżącej pozycji RMF, ZET, ESKA, OLiA i OLiS — tylko z list, na których utwór jest obecny.",
            valueFormatter=AVERAGE_POSITION_FORMATTER,
        )
    if "details" in show.columns:
        gb.configure_column(
            "details", "Otwórz", minWidth=78, width=84, sortable=False, filter=False,
            valueFormatter=DETAILS_LABEL_FORMATTER,
            headerTooltip="Klik: ta karta · Ctrl/Cmd/Shift/środkowy przycisk: nowa karta",
            cellStyle={"cursor": "pointer", "color": "#cfe4ff", "fontWeight": "650", "textDecoration": "underline"},
        )
    if "spotify" in show.columns:
        gb.configure_column(
            "spotify", "Spotify", minWidth=90, width=95, sortable=False, filter=False,
            valueFormatter=SPOTIFY_LABEL_FORMATTER,
            cellStyle={"cursor": "pointer", "color": "#d7f9df", "fontWeight": "650"},
        )
    if "spotify_copy" in show.columns:
        gb.configure_column(
            "spotify_copy", "Kopiuj", minWidth=62, width=68, sortable=False, filter=False,
            valueFormatter=SPOTIFY_COPY_FORMATTER,
            headerTooltip="Kopiuj link Spotify do schowka",
            cellStyle={"cursor": "pointer", "textAlign": "center", "fontWeight": "700"},
        )
    if "preview" in show.columns:
        gb.configure_column("preview", "Odsłuch", minWidth=90, width=98, sortable=False, filter=False, valueFormatter=PREVIEW_LABEL_FORMATTER, cellStyle={"cursor": "pointer"})
    if "heard" in show.columns:
        gb.configure_column(
            "heard", "✓", width=65, minWidth=58,
            editable=bool(editable_state), cellDataType="boolean",
            cellRenderer="agCheckboxCellRenderer", cellEditor="agCheckboxCellEditor",
        )
    if "status" in show.columns:
        gb.configure_column(
            "status", "Status", minWidth=150, width=165,
            editable=bool(editable_state),
            cellEditor="agSelectCellEditor", cellEditorParams={"values": STATUSES},
        )
    if "note" in show.columns:
        gb.configure_column("note", "Notatka", minWidth=220, width=300, editable=bool(editable_state))
    for col, label in [("familiarity", "Familiarity"), ("momentum", "Momentum")]:
        if col in show.columns:
            gb.configure_column(col, label, width=115, minWidth=105, valueFormatter=PERCENT_FORMATTER)
    if "radio_presence" in show.columns:
        gb.configure_column(
            "radio_presence", "Radio Presence 7d", width=145, minWidth=132,
            valueFormatter=PERCENT_FORMATTER,
        )
    if "radio_reach" in show.columns:
        gb.configure_column("radio_reach", "Zasięg 7d", width=108, minWidth=98, valueFormatter=PERCENT_FORMATTER)
    if "radio_rotation" in show.columns:
        gb.configure_column("radio_rotation", "Rotacja", width=100, minWidth=92, valueFormatter=PERCENT_FORMATTER)
    if "radio_presence_period" in show.columns:
        gb.configure_column("radio_presence_period", "Radio Presence", width=132, minWidth=120, valueFormatter=PERCENT_FORMATTER)

    source_names = [c for c in ["RMF", "ZET", "OLIA", "OLIS", "ESKA", "UK", "BILLBOARD"] if c in show.columns]
    week_names = [f"{c}_weeks" for c in source_names if f"{c}_weeks" in show.columns]
    compact_initial = source_layout == "compact"
    for col in source_names:
        gb.configure_column(
            col, valueFormatter=SOURCE_POSITION_FORMATTER,
            width=96 if source_layout in {"auto", "compact"} else 88, minWidth=82,
        )
    for col in week_names:
        src = col[:-6]
        gb.configure_column(col, f"{src} tyg.", width=76, minWidth=68, hide=compact_initial)

    # In Auto mode the grid itself decides: normal laptop widths collapse each
    # source to one cell (#position + muted weeks), ultrawide keeps two columns.
    if source_layout == "auto" and week_names:
        week_js = json.dumps(week_names)
        source_js = json.dumps(source_names)
        responsive_js = JsCode(f"""
        function(params) {{
          const weekCols = {week_js};
          const sourceCols = {source_js};
          const width = Number((params && params.clientWidth) || document.documentElement.clientWidth || window.innerWidth || 0);
          const compact = width > 0 && width < 2050;
          try {{
            if (params.api && params.api.setColumnsVisible) params.api.setColumnsVisible(weekCols, !compact);
            else if (params.columnApi && params.columnApi.setColumnsVisible) params.columnApi.setColumnsVisible(weekCols, !compact);
            if (params.api && params.api.refreshCells) params.api.refreshCells({{columns: sourceCols, force:true}});
          }} catch(e) {{}}
        }}
        """)
        gb.configure_grid_options(onGridSizeChanged=responsive_js, onFirstDataRendered=responsive_js)

    for col in [c for c in show.columns if c in {"position","previous_position","reported_peak"}]:
        gb.configure_column(col, valueFormatter=POSITION_FORMATTER, width=88, minWidth=78)
    if "position" in show.columns:
        gb.configure_column("position", "Pozycja", pinned="left", width=82, minWidth=76, valueFormatter=POSITION_FORMATTER)
    if "previous_position" in show.columns:
        gb.configure_column("previous_position", "Poprzednio", width=95, minWidth=90, valueFormatter=POSITION_FORMATTER)
    if "reported_weeks" in show.columns:
        gb.configure_column("reported_weeks", "Tygodnie", width=90, minWidth=84)
    if "reported_peak" in show.columns:
        gb.configure_column("reported_peak", "Peak", width=75, minWidth=70, valueFormatter=POSITION_FORMATTER)
    if "spins" in show.columns:
        gb.configure_column("spins", "Emisje", width=92, minWidth=84, pinned="left" if source_layout == "airplay" else None)
    if "stations_count" in show.columns:
        station_label = f"Stacje ({int(station_total)})" if station_total is not None else "Stacje"
        gb.configure_column("stations_count", station_label, width=92, minWidth=84)
    if "avg_per_day" in show.columns:
        gb.configure_column("avg_per_day", "Emisje/dzień łącznie", width=150, minWidth=138)
    if "avg_station_day" in show.columns:
        gb.configure_column("avg_station_day", "Śr./grającą stację/dzień", width=185, minWidth=170)
    if "station_reach" in show.columns:
        gb.configure_column("station_reach", "Zasięg stacji", width=120, minWidth=110, valueFormatter=PERCENT_FORMATTER)
    if "avg_per_station" in show.columns:
        gb.configure_column("avg_per_station", "Śr./stację", width=105, minWidth=96)
    if "max_station_spins" in show.columns:
        gb.configure_column("max_station_spins", "Max/stacja", width=105, minWidth=96)
    if "top_station" in show.columns:
        gb.configure_column("top_station", "Najmocniejsza stacja", minWidth=165, width=190)
    if "last_play" in show.columns:
        gb.configure_column("last_play", "Ostatnio", minWidth=150, width=165)

    options = gb.build()
    options.pop("autoSizeStrategy", None)
    original = show[[c for c in ["song_id", "heard", "status", "note"] if c in show.columns]].copy()

    response = AgGrid(
        show,
        gridOptions=options,
        height=height,
        theme="streamlit",
        allow_unsafe_jscode=True,
        enable_enterprise_modules=False,
        data_return_mode="AS_INPUT",
        update_on=["cellValueChanged"],
        should_grid_return=GRID_SHOULD_RETURN,
        custom_css={
            ".ag-row-selected": {"background-color": "rgba(74, 126, 187, 0.34) !important"},
            ".ag-cell-focus": {"border": "none !important", "outline": "none !important"},
        },
        key=key,
    )
    try:
        edited = response.data
    except Exception:
        try:
            edited = response["data"]
        except Exception:
            edited = show
    edited = pd.DataFrame(edited)

    if "_open_request" in edited.columns:
        requested = [str(x).strip() for x in edited["_open_request"].tolist() if str(x).strip()]
        if requested:
            try:
                navigate_to_song(int(requested[-1]))
            except (TypeError, ValueError):
                pass

    if editable_state and {"song_id", "heard", "status"}.issubset(edited.columns) and not original.empty:
        before = original.set_index("song_id")
        changed = 0
        cols_for_edit = [c for c in ["song_id", "heard", "status", "note"] if c in edited.columns]
        for r in edited[cols_for_edit].itertuples(index=False):
            try:
                sid = int(r.song_id)
            except Exception:
                continue
            if sid not in before.index:
                continue
            prev = before.loc[sid]
            old_note = str(prev["note"] or "") if "note" in before.columns else ""
            new_note = str(getattr(r, "note", old_note) or "")
            if bool(r.heard) != bool(prev.heard) or str(r.status) != str(prev.status) or new_note != old_note:
                update_note(sid, bool(r.heard), str(r.status), new_note)
                changed += 1
        if changed:
            st.toast(f"Zapisano status dla {changed} utworów.")
    return edited


def render_info_grid(frame: pd.DataFrame, *, key: str, height: int = 210) -> None:
    """Read-only AG Grid used on the song-detail page for visual consistency."""
    if frame.empty:
        st.caption("Brak danych.")
        return
    gb = GridOptionsBuilder.from_dataframe(frame)
    gb.configure_default_column(resizable=True, sortable=True, filter=False, editable=False)
    gb.configure_grid_options(rowHeight=36, animateRows=False)
    for col in frame.columns:
        if col in {"Pozycja", "Peak", "Tygodnie"}:
            gb.configure_column(col, width=105, minWidth=88)
        elif col == "Źródło":
            gb.configure_column(col, width=120, minWidth=105)
        elif col == "Rola":
            gb.configure_column(col, minWidth=180, width=220)
    AgGrid(
        frame,
        gridOptions=gb.build(),
        height=height,
        theme="streamlit",
        enable_enterprise_modules=False,
        key=key,
    )


@st.fragment(run_every=0.8)
def render_job_status_fragment(group: str = "all", key_suffix: str = "main") -> None:
    """Poll background jobs without rerunning the whole application."""
    job = latest_job()
    if not job:
        st.caption("Brak uruchomionych procesów.")
        return
    kind = str(job.get("kind", ""))
    if group == "collect" and not kind.startswith("collect"):
        return
    if group == "backfill" and not kind.startswith("backfill"):
        return
    if group == "airplay" and not kind.startswith("airplay"):
        return
    state = str(job.get("state", ""))
    running_now = state in {"running", "starting", "stopping"}
    icon = {"done":"✅", "partial":"⚠️", "failed":"⚠️", "cancelled":"⏹️", "running":"⏳", "starting":"⏳", "stopping":"⏹️"}.get(state, "ℹ️")
    st.markdown(f"**{icon} Proces:** {job.get('kind')} {job.get('source') or ''} — `{state}`")
    total = int(job.get("total") or 0)
    done = int(job.get("done") or 0)
    fraction = min(1.0, max(0.0, done / total)) if total else 0.0
    if running_now:
        st.progress(fraction, text=(f"{done}/{total} · " if total else "") + str(job.get("message") or "Pracuję…"))
    else:
        st.caption(job.get("message") or "")
    if job.get("messages"):
        st.code("\n".join(job["messages"][-10:]), language=None)
    if job.get("log_file"):
        with st.expander("📄 Log procesu"):
            st.caption(f"Pełny log: /app/data/jobs/{job.get('log_file')}")
            tail = read_job_log(str(job.get("job_id")), max_bytes=80_000)
            if tail:
                st.code(tail, language=None)
            if job.get("source_summary"):
                st.caption("Podsumowanie backfillu per źródło")
                summary_rows = [
                    {"Źródło": src, **stats}
                    for src, stats in job.get("source_summary", {}).items()
                ]
                if summary_rows:
                    st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)
    if running_now and st.button("⏹ Zatrzymaj proces", use_container_width=True, key=f"stop_{key_suffix}_{job.get('job_id')}"):
        stop_job(str(job["job_id"]))
        st.rerun()

    state_key = f"_rc_job_state_{key_suffix}"
    previous = st.session_state.get(state_key)
    st.session_state[state_key] = state
    if previous in {"running", "starting", "stopping"} and not running_now:
        st.rerun()


def render_airplay_data_management(running: bool) -> None:
    st.markdown("### Emisje — pobieranie i backfill")
    st.caption("Cała techniczna obsługa odSluchane jest tutaj. Zakładka Emisje służy już tylko do analizy zapisanych danych.")

    stations = list_airplay_stations(active_only=True)
    all_known = list_airplay_stations(active_only=False)
    active_ids = [int(s["station_id"]) for s in stations]
    labels = {int(s["station_id"]): str(s["name"]) for s in stations}

    b1, b2, _ = st.columns([1.15, 1.15, 3.7])
    if b1.button("↻ Odkryj / odśwież stacje", disabled=running, use_container_width=True, key="data_airplay_discover"):
        start_job("airplay-discover")
        st.rerun()
    if b2.button("⬇ Uzupełnij ostatnie 24h", disabled=running or not active_ids, use_container_width=True, key="data_airplay_latest"):
        start_job("airplay-latest")
        st.rerun()

    if not active_ids:
        st.info("Brak aktywnych stacji. Najpierw odśwież katalog odSluchane.")
        render_job_status_fragment("airplay", "data_airplay_empty")
        return

    cov = airplay_coverage(active_ids)
    last_date_raw = cov.get("last_date")
    try:
        last_date = date.fromisoformat(str(last_date_raw)) if last_date_raw else date.today() - timedelta(days=1)
    except Exception:
        last_date = date.today() - timedelta(days=1)
    default_bf = min(last_date, date.today() - timedelta(days=1))

    s1, s2 = st.columns([1.4, 3.6])
    station_scope = s1.selectbox("Stacje do backfillu", ["Wszystkie aktywne", "Wybrane"], key="data_airplay_bf_scope")
    if station_scope == "Wszystkie aktywne":
        selected_ids = active_ids
        s2.caption(f"{len(selected_ids)} aktywnych stacji")
    else:
        selected_ids = [int(x) for x in s2.multiselect(
            "Wybierz stacje",
            active_ids,
            default=active_ids[: min(6, len(active_ids))],
            format_func=lambda sid: labels.get(int(sid), str(sid)),
            key="data_airplay_bf_stations",
        )]

    d1, d2 = st.columns([2.1, 1])
    bf_range = d1.date_input("Zakres backfillu emisji", value=(default_bf, default_bf), key="data_airplay_bf_range")
    if isinstance(bf_range, (list, tuple)) and len(bf_range) == 2:
        bf_start, bf_end = bf_range
    else:
        bf_start = bf_end = bf_range if isinstance(bf_range, date) else default_bf
    if bf_end < bf_start:
        bf_start, bf_end = bf_end, bf_start
    estimated_windows = len(selected_ids) * len(completed_windows_in_range(bf_start, bf_end))
    d2.metric("Okna 2h", f"{estimated_windows:,}".replace(",", " "))
    can_backfill = bool(selected_ids) and estimated_windows <= 100_000 and not running
    if estimated_windows > 100_000:
        st.warning("Zakres przekracza limit 100 000 okien. Zmniejsz zakres lub liczbę stacji.")
    run_col, _ = st.columns([1.8, 4.2])
    if run_col.button("Backfill emisji", disabled=not can_backfill, type="primary", use_container_width=True, key="data_airplay_bf_run"):
        start_job("airplay-backfill", params={
            "station_ids": selected_ids,
            "start_date": bf_start.isoformat(),
            "end_date": bf_end.isoformat(),
        })
        st.rerun()
    st.caption("Pełna zakończona doba jednej stacji = 12 bloków po 2h. Backfill pobiera tylko zakończone okna i nie powinien dublować zapisanych emisji.")
    render_job_status_fragment("airplay", "data_airplay")

    with st.expander("Stacje bez użytecznych danych / wyłączone", expanded=False):
        probe_date = min(last_date, date.today() - timedelta(days=1))
        probe_expected = len(completed_windows_in_range(probe_date, probe_date))
        probe_rows = airplay_station_coverage(active_ids, probe_date, probe_date)
        dead_rows = [
            r for r in probe_rows
            if probe_expected >= 12 and int(r.get("ok_windows") or 0) >= probe_expected and int(r.get("plays") or 0) == 0
        ]
        if dead_rows:
            dead_df = pd.DataFrame(dead_rows)[["station_id", "name", "ok_windows", "zero_windows", "plays"]].rename(columns={
                "station_id": "ID", "name": "Stacja", "ok_windows": "Bloki OK", "zero_windows": "Puste bloki", "plays": "Emisje",
            })
            st.warning(f"{len(dead_rows)} stacji ma pełną dobę ({probe_expected} bloków) i 0 emisji za {probe_date}.")
            st.dataframe(dead_df, hide_index=True, use_container_width=True)
            if st.button(f"Wyłącz te stacje ({len(dead_rows)})", disabled=running, key="data_airplay_disable_dead"):
                set_airplay_station_active([int(r["station_id"]) for r in dead_rows], False)
                st.rerun()
        else:
            st.caption(f"Brak aktywnych stacji z pełną dobą i zerem emisji za {probe_date}.")

        inactive = [s for s in all_known if not bool(s.get("active"))]
        if inactive:
            inactive_map = {int(x["station_id"]): str(x["name"]) for x in inactive}
            to_enable = st.multiselect("Wyłączone stacje", list(inactive_map), format_func=lambda sid: inactive_map[int(sid)], key="data_airplay_reenable")
            if st.button("Włącz zaznaczone ponownie", disabled=running or not to_enable, key="data_airplay_reenable_btn"):
                set_airplay_station_active([int(x) for x in to_enable], True)
                st.rerun()


view_key = str(st.query_params.get("view", "dashboard"))
if view_key not in {"dashboard", "song", "archive", "airplay", "data", "methodology"}:
    view_key = "dashboard"
render_nav_tabs(view_key)
install_client_helpers()

# Keep heavy scoring out of views that do not need it.  In particular the
# Utwór view now scores only the selected song; this matters once the airplay
# catalogue contains tens of thousands of titles.
if view_key in {"dashboard", "archive", "song"}:
    REVISION = chart_revision()
else:
    REVISION = ""

if view_key in {"dashboard", "archive"}:
    df = with_notes(cached_scores(REVISION))
    if view_key == "dashboard":
        df = with_radio_presence(df, days=7)
else:
    df = pd.DataFrame()


if view_key == "dashboard":
    if df.empty:
        st.info("Baza jest pusta. Przejdź do zakładki Dane i pobierz źródła.")
    else:
        health_df, health_problems = source_health_frame()
        if health_problems:
            st.warning(
                "Nie wszystkie źródła są zweryfikowane dzisiaj: " + ", ".join(health_problems) +
                ". Pozycje poniżej pozostają z najnowszego poprawnie zapisanego notowania."
            )
            st.markdown('<a href="?view=data" target="_self">→ Przejdź do Dane i uzupełnij źródła</a>', unsafe_allow_html=True)
        else:
            st.success("Wszystkie źródła zostały sprawdzone dzisiaj.")
        with st.expander("Stan źródeł / świeżość danych", expanded=bool(health_problems)):
            st.dataframe(health_df, hide_index=True, use_container_width=True, height=285)
            st.caption("Publikacja = typowa kadencja źródła. „Powinno być ≥” jest liczone w tej samej semantyce daty, którą zwraca dane źródło (np. koniec okresu UK/OLiS, sobotnia data wydania Billboard; ESKA = dzień odczytu). Status pobrania i data notowania są rozdzielone.")

        period_map = {
            "1 tydz.": 7,
            "2 tyg.": 14,
            "4 tyg.": 28,
            "2 mies.": 61,
            "4 mies.": 122,
            "6 mies.": 183,
            "Całość": 0,
        }
        ctl_period, ctl_scope, ctl_layout, ctl_fam, ctl_mom, ctl_unheard = st.columns([1.05, 1.35, .9, 1.1, 1.1, 1.0])
        period_label = ctl_period.selectbox(
            "Okres wskaźników",
            list(period_map),
            index=len(period_map) - 1,
            help="Familiarity i Momentum są liczone ponownie tylko z obserwacji z wybranego okresu. Widok Całość najlepiej oddaje trwałą znajomość utworu; krótsze okresy służą do analizy świeżego zachowania list.",
        )
        lookback = int(period_map[period_label])
        period_df = df if lookback == 0 else with_radio_presence(with_notes(cached_scores(REVISION, lookback_days=lookback)), days=7)
        if period_df.empty:
            st.info("Brak danych w wybranym okresie.")
        else:
            scope = ctl_scope.selectbox(
                "Zakres",
                ["W najnowszych notowaniach", "PL w najnowszych", "Zagraniczne w najnowszych", "Cała historia"],
                index=0,
                help="„W najnowszych” = utwór jest obecny w najnowszym zapisanym notowaniu co najmniej jednego odpowiedniego źródła. To nie znaczy po prostu „kiedyś ostatnio pobrany”.",
            )
            table_layout_label = ctl_layout.selectbox(
                "Tabela",
                ["Auto", "Pełny", "Kompaktowy"],
                index=0,
                help="Auto: poniżej ok. 2050 px tygodnie są składane do kolumny źródła; na szerokim ekranie wracają jako osobne kolumny.",
            )
            min_fam = ctl_fam.slider("Min. Familiarity", 0, 100, 0, format="%d%%")
            min_mom = ctl_mom.slider("Min. Momentum", 0, 100, 0, format="%d%%")
            with ctl_unheard:
                st.caption("Filtr")
                only_unheard = st.checkbox("Nieprzesłuchane", key="dashboard_only_unheard")
            source_layout = {"Auto": "auto", "Pełny": "full", "Kompaktowy": "compact"}[table_layout_label]

            base = period_df.copy()
            core_pos = [c for c in ["OLIA_pos", "RMF_pos", "ZET_pos", "OLIS_pos", "ESKA_pos"] if c in base.columns]
            foreign_pos = [c for c in ["UK_pos", "BILLBOARD_pos"] if c in base.columns]
            all_pos = core_pos + foreign_pos
            if scope == "PL w najnowszych" and core_pos:
                base = base[base[core_pos].notna().any(axis=1)]
            elif scope == "Zagraniczne w najnowszych" and foreign_pos:
                base = base[base[foreign_pos].notna().any(axis=1)]
            elif scope == "W najnowszych notowaniach" and all_pos:
                base = base[base[all_pos].notna().any(axis=1)]
            view = base[(base.familiarity >= min_fam) & (base.momentum >= min_mom)].copy()
            search_col, unheard_col = st.columns([5.2, 1.0])
            song_query = search_col.text_input(
                "Szukaj w Dashboardzie",
                placeholder="wykonawca lub tytuł, np. meskie / Waligóra / Azizam",
                key="dashboard_song_search",
                help="Przeszukuje wszystkie utwory po zastosowaniu zakresu i progów, jeszcze przed wyświetleniem tabeli. Polskie znaki nie mają znaczenia.",
            )
            if song_query.strip():
                view = filter_song_rows(view, song_query)
            if only_unheard:
                view = view[~view.heard]
            view = view.reset_index(drop=True)

            render_compact_metrics([
                ("Utwory (filtr / okres)", f"{len(view)} / {len(period_df)}"),
                ("Current Familiar ≥70%", f"{int((view.familiarity >= 70).sum())} / {int((period_df.familiarity >= 70).sum())}"),
                ("Rising ≥65%", f"{int((view.momentum >= 65).sum())} / {int((period_df.momentum >= 65).sum())}"),
                ("Pokrycie źródeł", f"{period_df.coverage.max():.0f}%"),
            ])
            st.caption(f"Okres wskaźników: {period_label}. Cała baza zawiera obecnie {len(df)} utworów. Rising nie ma już osobnej tabeli — wystarczy sortować Momentum albo ustawić jego minimum.")

            core_avg_cols = [c for c in ["RMF_pos", "ZET_pos", "ESKA_pos", "OLIA_pos", "OLIS_pos"] if c in view.columns]
            if core_avg_cols:
                view["avg_position"] = view[core_avg_cols].apply(pd.to_numeric, errors="coerce").mean(axis=1).round(1)
            else:
                view["avg_position"] = float("nan")
            view["release_month"] = [
                release_month(rel, first)
                for rel, first in zip(
                    view["release_date"] if "release_date" in view.columns else [""] * len(view),
                    view["first_chart_date"] if "first_chart_date" in view.columns else [""] * len(view),
                )
            ]
            view["details"] = [song_link(sid) for sid in view.song_id]
            view["spotify"] = [spotify_search_url(a, t) for a, t in zip(view.artist, view.title)]
            view["spotify_copy"] = view["spotify"]
            view["preview"] = "▶"
            view["heard"] = view["heard"].fillna(False).astype(bool)
            view["status"] = view["status"].fillna("Nie słuchałem").astype(str)

            cols = [
                "song_id", "artist", "title", "release_month", "details", "preview", "spotify", "spotify_copy", "heard", "status",
                "familiarity", "momentum", "radio_presence", "radio_reach", "radio_rotation",
                "avg_position", "RMF_pos", "RMF_weeks", "ZET_pos", "ZET_weeks", "OLIA_pos", "OLIA_weeks",
                "OLIS_pos", "OLIS_weeks", "ESKA_pos", "ESKA_weeks",
                "UK_pos", "UK_weeks", "BILLBOARD_pos", "BILLBOARD_weeks", "note",
            ]
            show = view[[c for c in cols if c in view.columns]].copy()
            pos_cols = [c for c in show.columns if c.endswith("_pos")]
            for col in pos_cols:
                show[col] = show[col].map(position_sort_value).astype(int)
            show = show.rename(columns={c: c.replace("_pos", "") for c in pos_cols})
            render_song_grid(show, key=f"dashboard_grid_{lookback}_{scope}_{source_layout}", height=660, editable_state=True, source_layout=source_layout)
            st.caption("Auto składa na laptopie pozycję i tygodnie do jednej komórki, np. #7 · 5w. Radio Presence 7d = 70% zasięg stacji + 30% intensywność rotacji; szczegóły są w Manualu. ▶ 30s otwiera player przyklejony do dołu ekranu.")

elif view_key == "song":
    st.markdown('<span id="rc-song-top"></span>', unsafe_allow_html=True)
    scroll_song_to_top_once()

    # The picker deliberately excludes anonymous/raw airplay-only credits.  That
    # keeps it responsive even when Emisje discovered tens of thousands of RDS
    # variants. A song opened directly from Emisje is appended for this request.
    catalog = cached_song_catalog(song_catalog_revision())
    requested = st.query_params.get("song")
    requested_id: int | None = None
    try:
        requested_id = int(requested) if requested is not None else None
    except (TypeError, ValueError):
        requested_id = None
    if requested_id is not None:
        requested_id = canonical_song_id(requested_id)

    if catalog.empty and requested_id is None:
        st.info("Najpierw dodaj dane z notowań albo otwórz utwór z Emisji.")
    else:
        picker = catalog.copy()
        if requested_id is not None and (picker.empty or requested_id not in set(picker["song_id"].astype(int))):
            direct = get_song(requested_id)
            if direct:
                picker = pd.concat([
                    pd.DataFrame([{"song_id": int(direct["song_id"]), "artist": direct["artist"], "title": direct["title"]}]),
                    picker,
                ], ignore_index=True)
        picker = picker.drop_duplicates("song_id").sort_values(
            ["artist", "title"], key=lambda s: s.astype(str).str.casefold()
        ).reset_index(drop=True)
        ids = [int(x) for x in picker["song_id"].tolist()]
        selected_id = requested_id if requested_id in ids else (ids[0] if ids else requested_id)
        if selected_id is None:
            st.info("Brak utworów do pokazania.")
        else:
            picked_id = render_song_picker(picker, int(selected_id))
            if int(picked_id) != int(selected_id):
                navigate_to_song(int(picked_id))

            song_id = canonical_song_id(int(selected_id))
            song_meta = get_song(song_id)
            if song_meta is None:
                st.error("Nie znaleziono utworu w bazie.")
            else:
                score_df = cached_song_score(REVISION, song_id)
                has_chart_data = not score_df.empty
                if has_chart_data:
                    row = score_df.iloc[0].copy()
                else:
                    row = pd.Series({"song_id": song_id, "artist": song_meta["artist"], "title": song_meta["title"]})
                    for src in ["OLIA", "RMF", "ZET", "OLIS", "ESKA", "UK", "BILLBOARD"]:
                        row[f"{src}_pos"] = None
                        row[f"{src}_weeks"] = 0
                        row[f"{src}_peak"] = None
                row["artist"] = str(song_meta["artist"])
                row["title"] = str(song_meta["title"])
                row["heard"] = bool(song_meta.get("heard", False))
                row["status"] = str(song_meta.get("status") or "Nie słuchałem")
                row["note"] = str(song_meta.get("note") or "")

                radio = cached_airplay_song_presence(airplay_revision(), song_id, 7)
                reporting = int(radio.get("reporting_stations") or 0)
                spotify_url = spotify_search_url(str(row.artist), str(row.title))

                with st.container(border=True):
                    head1, head2, head3 = st.columns([6, 1.05, .9])
                    with head1:
                        st.markdown(
                            f'<div class="rc-song-title">{html.escape(str(row.artist))} — {html.escape(str(row.title))}</div>'
                            f'<div class="rc-song-meta">{html.escape(str(row.status))} · {"przesłuchany" if bool(row.heard) else "nieprzesłuchany"}</div>',
                            unsafe_allow_html=True,
                        )
                    with head2:
                        render_preview_button(song_id, row.artist, row.title, spotify_url)
                    with head3:
                        st.link_button("Spotify ↗", spotify_url, use_container_width=True)

                    fam_label = f"{float(row.familiarity):.0f}%" if has_chart_data else "—"
                    mom_label = f"{float(row.momentum):.0f}%" if has_chart_data else "—"
                    radio_label = f"{float(radio.get('radio_presence') or 0):.0f}%" if reporting else "—"
                    reach_label = f"{float(radio.get('radio_reach') or 0):.0f}%" if reporting else "—"
                    rotation_label = f"{float(radio.get('radio_rotation') or 0):.0f}%" if reporting else "—"
                    render_compact_metrics([
                        ("Familiarity", fam_label),
                        ("Momentum", mom_label),
                        ("Radio Presence 7d", radio_label),
                        ("Zasięg stacji", reach_label),
                        ("Rotacja", rotation_label),
                    ], columns=5)
                    if reporting:
                        st.caption(
                            f"Radio 7d: {int(radio.get('stations_count') or 0)}/{reporting} raportujących stacji · "
                            f"{float(radio.get('airplay_spins_per_day') or 0):.1f} emisji/dzień łącznie · "
                            f"{float(radio.get('airplay_spins_per_station_day') or 0):.2f} na grającą stację/dzień."
                        )
                    if row.note:
                        st.caption(f"Notatka: {row.note}")

                def _source_frame(sources: list[str]) -> pd.DataFrame:
                    rows = []
                    for src in sources:
                        rows.append({
                            "Źródło": src,
                            "Pozycja": position_display(row.get(f"{src}_pos")),
                            "Tygodnie": int(row.get(f"{src}_weeks", 0) or 0),
                            "Peak": position_display(row.get(f"{src}_peak")),
                        })
                    return pd.DataFrame(rows)

                st.markdown("### Pozycje i historia źródłowa")
                source_table = pd.concat([
                    _source_frame(["OLIA", "RMF", "ZET", "OLIS", "ESKA"]).assign(Rola="Polska / Familiarity"),
                    _source_frame(["UK", "BILLBOARD"]).assign(Rola="Sygnał międzynarodowy"),
                ], ignore_index=True)
                source_table = source_table[["Źródło", "Rola", "Pozycja", "Tygodnie", "Peak"]]
                render_info_grid(source_table, key=f"song_sources_{song_id}", height=258)
                st.caption("UK/Billboard są sygnałami pomocniczymi i nie zmieniają wag Familiarity.")

                st.markdown("### Historia pozycji")
                h = cached_song_history(REVISION, song_id)
                if h.empty:
                    st.caption("Brak zapisanej historii pozycji dla tego utworu. Jeśli trafił tu z Emisji, może jeszcze nie występować w żadnym naszym notowaniu.")
                else:
                    available_sources = list(dict.fromkeys(h["source"].tolist()))
                    default_sources = [x for x in ["RMF", "ZET", "OLIA", "OLIS", "ESKA"] if x in available_sources]
                    if not default_sources:
                        default_sources = available_sources[:4]
                    hist_src_col, hist_scale_col = st.columns([3, 1])
                    selected_sources = hist_src_col.multiselect("Źródła na wykresie", available_sources, default=default_sources, key=f"history_sources_{song_id}")
                    scale_mode = hist_scale_col.selectbox(
                        "Skala", ["Nieliniowa — Top 20", "Liniowa"], index=0, key=f"history_scale_{song_id}"
                    )
                    hp = h[h["source"].isin(selected_sources)] if selected_sources else h.iloc[0:0]
                    if hp.empty:
                        st.caption("Wybierz przynajmniej jedno źródło do wykresu.")
                    else:
                        plot_df = hp.copy()
                        maxpos = max(20, int(plot_df.position.max()))
                        if scale_mode.startswith("Nieliniowa"):
                            plot_df["position_plot"] = plot_df["position"].astype(float).map(math.sqrt)
                            fig = px.line(plot_df, x="chart_date", y="position_plot", color="source", markers=True)
                            ticks = [x for x in [1, 2, 3, 5, 10, 20, 40, 60, 80, 100, 150, 200] if x <= maxpos]
                            if maxpos not in ticks:
                                ticks.append(maxpos)
                            fig.update_yaxes(
                                autorange="reversed", range=[math.sqrt(maxpos + 3), 1], tickmode="array",
                                tickvals=[math.sqrt(x) for x in ticks], ticktext=[str(x) for x in ticks],
                                title="Pozycja (skala nieliniowa)",
                            )
                            fig.update_traces(customdata=plot_df[["position"]], hovertemplate="%{x|%Y-%m-%d}<br>Pozycja #%{customdata[0]}<extra></extra>")
                        else:
                            fig = px.line(plot_df, x="chart_date", y="position", color="source", markers=True)
                            fig.update_yaxes(autorange="reversed", range=[maxpos + 3, 1], dtick=5, title="Pozycja")
                        fig.update_layout(height=430, legend=dict(orientation="h", yanchor="top", y=-0.12, x=0), margin=dict(t=12,b=65,l=35,r=20))
                        st.plotly_chart(fig, use_container_width=True)

                st.markdown("### Emisje radiowe")
                song_airplay_stations = list_airplay_stations(active_only=True)
                song_station_ids = [int(s["station_id"]) for s in song_airplay_stations]
                if not song_station_ids:
                    st.caption("Brak aktywnych stacji w Emisjach.")
                else:
                    song_cov = airplay_coverage(song_station_ids)
                    song_last_date = song_cov.get("last_date")
                    song_first_date = song_cov.get("first_date")
                    song_air_end = date.fromisoformat(str(song_last_date)) if song_last_date else date.today()
                    song_air_earliest = date.fromisoformat(str(song_first_date)) if song_first_date else song_air_end
                    song_air_start, song_air_end = render_airplay_range_picker(
                        key_prefix=f"song_airplay_range_{song_id}",
                        default_end=song_air_end,
                        earliest=song_air_earliest,
                        default_preset="Ostatni tydzień",
                    )
                    song_air_detail = cached_airplay_track_detail(
                        airplay_revision(),
                        tuple(sorted(song_station_ids)),
                        song_air_start.isoformat(),
                        song_air_end.isoformat(),
                        song_id,
                    )
                    song_air_days = max(1, (song_air_end - song_air_start).days + 1)
                    song_spins = int(song_air_detail.get("total_spins") or 0)
                    song_station_count = int(song_air_detail.get("stations_count") or 0)
                    song_avg_day = song_spins / song_air_days
                    song_avg_station_day = song_spins / song_air_days / max(1, song_station_count)
                    song_last_play = str(song_air_detail.get("last_play") or "—").replace("T", " ")
                    render_compact_metrics([
                        ("Emisje", song_spins),
                        (f"Stacje ({len(song_station_ids)})", song_station_count),
                        ("Emisje/dzień", f"{song_avg_day:.1f}"),
                        ("Śr./grającą stację/dzień", f"{song_avg_station_day:.2f}"),
                        ("Ostatnio", song_last_play),
                    ], columns=5)
                    st.caption(
                        f"{song_air_start} → {song_air_end} · wszystkie aktywne stacje. "
                        "Szczegóły per stacja są zwinięte poniżej, żeby karta Utworu pozostała kompaktowa."
                    )

                    with st.expander("Szczegóły emisji per stacja i dzień", expanded=False):
                        detail_left, detail_right = st.columns([1.15, 1])
                        station_df = pd.DataFrame(song_air_detail.get("stations") or [])
                        with detail_left:
                            if station_df.empty:
                                st.caption("Brak zapisanych emisji tego utworu w wybranym okresie.")
                            else:
                                station_df["avg_period_day"] = (station_df["spins"] / song_air_days).round(2)
                                station_df["avg_active_day"] = (station_df["spins"] / station_df["active_days"].clip(lower=1)).round(2)
                                station_table = station_df[[
                                    "station", "spins", "active_days", "avg_period_day", "avg_active_day"
                                ]].rename(columns={
                                    "station": "Stacja",
                                    "spins": "Emisje",
                                    "active_days": "Dni z emisją",
                                    "avg_period_day": "Śr./dzień okresu",
                                    "avg_active_day": "Śr./aktywny dzień",
                                })
                                st.dataframe(
                                    station_table,
                                    hide_index=True,
                                    use_container_width=True,
                                    height=min(330, 38 + 35 * len(station_table)),
                                )
                        with detail_right:
                            daily_df = pd.DataFrame(song_air_detail.get("daily") or [])
                            if daily_df.empty:
                                st.caption("Brak danych dziennych do wykresu.")
                            else:
                                daily_total = daily_df.groupby("play_date", as_index=False)["spins"].sum()
                                daily_total["play_date"] = pd.to_datetime(daily_total["play_date"])
                                air_fig = px.bar(
                                    daily_total,
                                    x="play_date",
                                    y="spins",
                                    labels={"play_date": "Dzień", "spins": "Emisje"},
                                )
                                air_fig.update_layout(height=285, margin=dict(t=10, b=35, l=25, r=10))
                                st.plotly_chart(air_fig, use_container_width=True)

                render_song_note_editor(song_id, bool(row.heard), str(row.status), str(row.note or ""))
                # Player jest podniesiony nad dół okna; dodatkowy luz zapobiega
                # przycinaniu ostatniego wiersza formularza na niższych ekranach.
                st.markdown('<div style="height:5rem"></div>', unsafe_allow_html=True)


elif view_key == "archive":
    st.subheader("📚 Notowania")
    st.caption("Przeglądaj zarówno najnowsze, jak i historyczne notowania. Domyślnie otwiera się najnowsze zapisane notowanie wybranego źródła.")
    all_issues = list_issues(limit=20000)
    if not all_issues:
        st.info("Brak zapisanych notowań.")
    else:
        sources = sorted({x["source"] for x in all_issues})
        src = st.selectbox("Źródło", sources, key="archive_source")
        source_issues = [x for x in all_issues if x["source"] == src]
        issue_ids = [int(x["id"]) for x in source_issues]
        by_id = {int(x["id"]): x for x in source_issues}
        issue_id = st.selectbox(
            "Notowanie",
            issue_ids,
            format_func=lambda x: f"{by_id[x]['chart_date']} · {by_id[x]['issue_key']} · {by_id[x]['entries']} pozycji",
            key="archive_issue",
        )
        meta = by_id[int(issue_id)]
        newest_id = issue_ids[0] if issue_ids else None
        latest_note = " · NAJNOWSZE" if int(issue_id) == newest_id else ""
        st.caption(f"{meta['source']} · {meta['chart_date']} · {meta['entries']} pozycji{latest_note} · tabela pokazuje ok. 20 wierszy i przewija resztę")

        entries = pd.DataFrame(issue_entries_enriched(int(issue_id)))
        if not entries.empty:
            historical_scores = with_notes(cached_scores(REVISION, as_of=str(meta["chart_date"])))
            if not historical_scores.empty:
                score_cols = ["song_id", "familiarity", "momentum", "heard", "status", "note"]
                entries = entries.drop(columns=[c for c in ["heard", "status", "note"] if c in entries.columns]).merge(
                    historical_scores[score_cols], on="song_id", how="left",
                )
            entries["heard"] = entries.get("heard", False).fillna(False).astype(bool)
            entries["status"] = entries.get("status", "Nie słuchałem").fillna("Nie słuchałem").astype(str)
            entries["spotify"] = [spotify_search_url(a, t) for a, t in zip(entries.artist, entries.title)]
            entries["spotify_copy"] = entries["spotify"]
            entries["details"] = [song_link(sid) for sid in entries.song_id]
            entries["preview"] = "▶"
            for c in ["position", "previous_position", "reported_peak"]:
                if c in entries:
                    entries[c] = entries[c].map(position_sort_value).astype(int)

            archive_cols = [
                "song_id", "position", "artist", "title", "details", "preview", "spotify", "spotify_copy",
                "previous_position", "reported_weeks", "reported_peak",
                "familiarity", "momentum", "status", "heard", "note",
            ]
            archive_show = entries[[c for c in archive_cols if c in entries.columns]].copy()
            render_song_grid(
                archive_show,
                key=f"issue_grid_{int(issue_id)}",
                height=770,
                editable_state=True,
            )
            st.caption("Poprzednio/Tygodnie/Peak są uzupełniane z danych źródła, a gdy ich brakuje — z naszej zapisanej historii. Familiarity i Momentum są liczone historycznie: tylko z danych dostępnych do daty tego notowania. Status, ✓ i notatka są Twoim obecnym stanem i można je edytować.")

elif view_key == "airplay":
    st.subheader("📡 Emisje")
    st.info(
        "**Emisje są osobną miarą, ale utwory są wspólne.** Liczba odtworzeń z odSluchane.eu nie wpływa na "
        "Familiarity, Momentum ani pozycje w notowaniach. Jeśli ten sam utwór występuje w obu miejscach, ma jeden "
        "rekord, ten sam odsłuch/status/notatkę, a w Emisjach możemy obok pokazać jego bieżące pozycje z RMF/ZET/OLiA/OLiS/ESKA."
    )
    stations = list_airplay_stations(active_only=True)
    all_known_stations = list_airplay_stations(active_only=False)
    running = active_job() is not None

    latest_pos_rows = pd.DataFrame(latest_chart_positions())
    if not latest_pos_rows.empty:
        chart_latest = latest_pos_rows.pivot_table(
            index="song_id", columns="source", values="position", aggfunc="first"
        ).reset_index()
        chart_latest.columns.name = None
        chart_latest = chart_latest.rename(columns={src: f"{src}_pos" for src in ["RMF", "ZET", "OLIA", "OLIS", "ESKA", "UK", "BILLBOARD"] if src in chart_latest.columns})
    else:
        chart_latest = pd.DataFrame(columns=["song_id"])

    if not stations:
        st.warning("Nie ma jeszcze listy stacji. Najpierw uruchom odkrywanie katalogu odSluchane.eu.")
        if st.button("↻ Odkryj / odśwież wszystkie stacje", disabled=running, type="primary"):
            start_job("airplay-discover")
            st.rerun()
        render_job_status_fragment("airplay", "airplay_empty")
    else:
        all_station_ids = [int(s["station_id"]) for s in stations]
        station_labels = {int(s["station_id"]): str(s["name"]) for s in stations}
        core_ids = [
            sid for sid, name in station_labels.items()
            if name.casefold() in {"rmf fm", "zet", "eska", "radio zet", "radio eska"}
        ]
        all_coverage = airplay_coverage(all_station_ids)
        first_date = all_coverage.get("first_date")
        last_date = all_coverage.get("last_date")
        default_end = date.fromisoformat(str(last_date)) if last_date else date.today()
        earliest = date.fromisoformat(str(first_date)) if first_date else default_end - timedelta(days=6)
        default_start = max(earliest, default_end - timedelta(days=6))

        f1, f2 = st.columns([1, 2])
        scope = f1.radio(
            "Stacje",
            ["Wszystkie stacje", "Wybrane stacje"],
            horizontal=True,
            key="airplay_station_scope",
        )
        if scope == "Wszystkie stacje":
            selected_ids = all_station_ids
            f2.caption(f"Liczymy {len(selected_ids)} odkrytych stacji.")
        else:
            selected_ids = f2.multiselect(
                "Wybierz stacje",
                all_station_ids,
                default=core_ids or all_station_ids[: min(3, len(all_station_ids))],
                format_func=lambda sid: station_labels.get(int(sid), str(sid)),
                key="airplay_station_multiselect",
            )
            selected_ids = [int(x) for x in selected_ids]

        range_start, range_end = render_airplay_range_picker(
            key_prefix="airplay_range_v3",
            default_end=default_end,
            earliest=earliest,
            default_preset="Ostatni tydzień",
        )

        expected_windows = len(completed_windows_in_range(range_start, range_end)) * len(selected_ids) if selected_ids else 0
        range_coverage = airplay_coverage(selected_ids, range_start, range_end) if selected_ids else {}
        ok_windows = int(range_coverage.get("ok_windows") or 0)
        coverage_pct = (100.0 * ok_windows / expected_windows) if expected_windows else 0.0
        per_station_expected = len(completed_windows_in_range(range_start, range_end)) if selected_ids else 0
        station_cov_rows = airplay_station_coverage(selected_ids, range_start, range_end) if selected_ids else []
        reporting_station_count = sum(1 for r in station_cov_rows if int(r.get("plays") or 0) > 0)

        if not selected_ids:
            st.info("Wybierz przynajmniej jedną stację.")
            summary_rows = []
            air_rev = airplay_revision()
        else:
            air_rev = airplay_revision()
            summary_rows = cached_airplay_summary(
                air_rev, tuple(sorted(int(x) for x in selected_ids)),
                range_start.isoformat(), range_end.isoformat(),
            )

        air = pd.DataFrame(summary_rows)
        period_days = max(1, (range_end - range_start).days + 1)
        total_spins = int(air["spins"].sum()) if not air.empty else 0
        render_compact_metrics([
            ("Emisje w okresie", f"{total_spins:,}".replace(",", " ")),
            ("Różne utwory", len(air)),
            ("Stacje w filtrze", len(selected_ids)),
            ("Pokrycie bloków 2h", f"{ok_windows}/{expected_windows}" if expected_windows else "—"),
        ])
        st.caption(f"Zakres: {range_start} → {range_end}. Pełna zakończona doba = **12 bloków po 2h na każdą stację**.")
        if expected_windows and ok_windows < expected_windows:
            st.warning(
                f"Dane w tym zakresie są niepełne: zapisano {ok_windows} z {expected_windows} zakończonych bloków 2h "
                f"({coverage_pct:.0f}%). Ranking liczy tylko zapisane emisje. Około 20–30 utworów na stację/dzień "
                "zwykle oznacza, że mamy tylko jeden blok 2h, a nie całą dobę. Uzupełnienie 24h i backfill są w zakładce Dane."
            )
        if selected_ids:
            st.caption(
                f"Raportujące stacje w tym zakresie: **{reporting_station_count}/{len(selected_ids)}**. "
                "Raportująca = mamy z niej przynajmniej jedną zapisaną emisję w wybranym okresie."
            )
            with st.expander("🔎 Co dokładnie zostało pobrane — pokrycie per stacja", expanded=False):
                cov_df = pd.DataFrame(station_cov_rows)
                if not cov_df.empty:
                    cov_df["expected"] = per_station_expected
                    cov_df["missing"] = (cov_df["expected"] - cov_df["ok_windows"].fillna(0).astype(int)).clip(lower=0)
                    cov_df["coverage_pct"] = [
                        round(100.0 * int(ok or 0) / per_station_expected, 1) if per_station_expected else 0.0
                        for ok in cov_df["ok_windows"]
                    ]
                    cov_df["status"] = [
                        ("✅ komplet" if int(ok or 0) >= per_station_expected and int(plays or 0) > 0
                         else "⚪ komplet, 0 emisji" if int(ok or 0) >= per_station_expected and per_station_expected > 0
                         else "⚠️ braki")
                        for ok, plays in zip(cov_df["ok_windows"], cov_df["plays"])
                    ]
                    shown_cov = cov_df[["name", "status", "ok_windows", "expected", "missing", "zero_windows", "plays"]].rename(columns={
                        "name": "Stacja", "status": "Stan", "ok_windows": "Bloki OK", "expected": "Oczekiwane",
                        "missing": "Brakuje", "zero_windows": "Puste bloki", "plays": "Emisje",
                    })
                    st.dataframe(shown_cov, hide_index=True, use_container_width=True, height=min(600, 44 + 35 * len(shown_cov)))
                    st.caption("Pusty blok = strona odSluchane odpowiedziała poprawnie, ale parser nie znalazł żadnej emisji. To odróżnia brak pobrania od stacji, która nie zwraca playlisty/RDS.")

        if air.empty:
            st.info("Brak zapisanych emisji dla wybranych stacji i dat. Pobieranie bieżące i backfill są w zakładce Dane.")
        else:
            tab_rank, tab_track = st.tabs(["🔥 Najczęściej grane", "🔎 Sprawdź utwór"])

            with tab_rank:
                r0, r1, r2, r3 = st.columns([2.2, .85, 1, .75])
                airplay_query = r0.text_input(
                    "Szukaj w Emisjach",
                    placeholder="wykonawca lub tytuł",
                    key="airplay_rank_search",
                    help="Filtr jest wykonywany na wszystkich utworach w wybranym okresie, zanim zadziała limit Pokaż. Polskie znaki są ignorowane.",
                )
                min_station_count = r1.number_input(
                    "Min. stacji",
                    min_value=1,
                    max_value=max(1, len(selected_ids)),
                    value=1,
                    step=1,
                    key="airplay_rank_min_stations",
                )
                sort_mode = r2.selectbox(
                    "Sortuj",
                    ["Emisje", "Liczba stacji", "Max/stacja"],
                    index=0,
                    key="airplay_rank_sort",
                )
                top_n = r3.selectbox("Pokaż", [50, 100, 250, 500, "Wszystkie"], index=1, key="airplay_rank_top")

                ranked = air[air["stations_count"] >= int(min_station_count)].copy()
                if airplay_query.strip():
                    ranked = filter_song_rows(ranked, airplay_query)
                if sort_mode == "Liczba stacji":
                    ranked = ranked.sort_values(["stations_count", "spins"], ascending=[False, False])
                elif sort_mode == "Max/stacja":
                    ranked = ranked.sort_values(["max_station_spins", "spins"], ascending=[False, False])
                else:
                    ranked = ranked.sort_values(["spins", "stations_count"], ascending=[False, False])
                if top_n != "Wszystkie":
                    ranked = ranked.head(int(top_n))
                ranked = ranked.reset_index(drop=True)
                ranked = ranked[ranked["song_id"].notna()].copy()
                ranked["song_id"] = ranked["song_id"].astype(int)
                ranked["avg_per_day"] = (ranked["spins"] / period_days).round(1)
                ranked["avg_station_day"] = (ranked["spins"] / period_days / ranked["stations_count"].clip(lower=1)).round(2)
                ranked["station_reach"] = (
                    100.0 * ranked["stations_count"] / reporting_station_count
                ).clip(upper=100).round(1) if reporting_station_count else float("nan")
                ranked["radio_rotation"] = (100.0 * ranked["avg_station_day"] / 6.0).clip(upper=100).round(1)
                ranked["radio_presence_period"] = (
                    0.70 * ranked["station_reach"].fillna(0) + 0.30 * ranked["radio_rotation"]
                ).round(1) if reporting_station_count else float("nan")
                ranked["last_play"] = ranked["last_play"].astype(str).str.replace("T", " ", regex=False)
                ranked["release_month"] = [
                    release_month(rel, first)
                    for rel, first in zip(
                        ranked["release_date"] if "release_date" in ranked.columns else [""] * len(ranked),
                        ranked["first_chart_date"] if "first_chart_date" in ranked.columns else [""] * len(ranked),
                    )
                ]
                ranked = with_notes(ranked)

                # Join only latest chart-derived positions.  This avoids loading
                # the expensive full score frame merely to render Emisje.
                source_cols = ["RMF", "ZET", "OLIA", "OLIS", "ESKA"]
                if not chart_latest.empty:
                    chart_cols = ["song_id"] + [f"{src}_pos" for src in source_cols if f"{src}_pos" in chart_latest.columns]
                    ranked = ranked.merge(chart_latest[chart_cols].drop_duplicates("song_id"), on="song_id", how="left")
                for src in source_cols:
                    pos_col = f"{src}_pos"
                    ranked[src] = ranked[pos_col].map(position_sort_value).astype(int) if pos_col in ranked.columns else 999

                ranked["details"] = [song_link(sid) for sid in ranked["song_id"]]
                ranked["preview"] = "▶"
                ranked["spotify"] = [spotify_search_url(a, t) for a, t in zip(ranked["artist"], ranked["title"])]
                ranked["spotify_copy"] = ranked["spotify"]
                air_cols = [
                    "song_id", "spins", "artist", "title", "release_month", "details", "preview", "spotify", "spotify_copy", "heard", "status",
                    "stations_count", "radio_rotation", "radio_presence_period",
                    "avg_per_day", "avg_station_day", "max_station_spins", "top_station", "last_play",
                    "RMF", "ZET", "OLIA", "OLIS", "ESKA", "note",
                ]
                air_show = ranked[[c for c in air_cols if c in ranked.columns]].copy()
                station_key = "-".join(str(x) for x in selected_ids)
                render_song_grid(
                    air_show,
                    key=f"airplay_rank_{range_start}_{range_end}_{sort_mode}_{top_n}_{min_station_count}_{normalize(airplay_query)}_{station_key}",
                    height=690,
                    editable_state=True,
                    source_layout="airplay",
                    station_total=len(selected_ids),
                )
                st.caption(
                    "**Stacje (N)** = ile stacji z aktualnego filtra gra dany utwór; N w nagłówku to maksymalna liczba wybranych stacji. "
                    "**Emisje/dzień łącznie** = suma odtworzeń ze wszystkich wybranych stacji / liczba dni. "
                    "**Śr./grającą stację/dzień** dzieli dodatkowo przez liczbę stacji, które faktycznie zagrały utwór. "
                    "**Rotacja** = intensywność grania (6+/stację/dzień = 100). Radio Presence nadal uwzględnia szerokość grania, "
                    "ale osobna kolumna Zasięg została usunięta jako redundantna ze Stacjami."
                )

            with tab_track:
                order = air.sort_values(["artist", "title"], key=lambda s: s.astype(str).str.casefold()).reset_index(drop=True)
                track_query = st.text_input(
                    "Wykonawca / tytuł",
                    placeholder="wpisz fragment wykonawcy lub tytułu, np. meskie",
                    key="airplay_track_search_v2",
                    help="Wyszukiwanie jest dokładne po znormalizowanym tekście, a nie fuzzy. Ignoruje polskie znaki i przeszukuje cały wybrany okres.",
                )
                matches = filter_song_rows(order, track_query) if track_query.strip() else order
                matches = matches.reset_index(drop=True)
                if matches.empty:
                    st.info("Brak utworów pasujących do wyszukiwania w tym okresie.")
                    chosen = order.iloc[0]
                else:
                    preview_matches = matches.head(80).copy()
                    result_table = preview_matches[["artist", "title", "spins", "stations_count"]].rename(columns={
                        "artist": "Wykonawca", "title": "Tytuł", "spins": "Emisje", "stations_count": "Stacje",
                    })
                    selection = st.dataframe(
                        result_table,
                        hide_index=True,
                        use_container_width=True,
                        height=min(270, 38 + 35 * len(result_table)),
                        on_select="rerun",
                        selection_mode="single-row",
                        key=f"airplay_track_results_{normalize(track_query)}",
                    )
                    try:
                        selected_rows = list(selection.selection.rows or [])
                    except Exception:
                        try:
                            selected_rows = list((selection.get("selection") or {}).get("rows") or [])
                        except Exception:
                            selected_rows = []
                    picked_idx = int(selected_rows[0]) if selected_rows else 0
                    chosen = preview_matches.iloc[picked_idx]
                    if len(matches) > len(preview_matches):
                        st.caption(f"Pokazuję pierwsze {len(preview_matches)} z {len(matches)} dopasowań — doprecyzuj wyszukiwanie.")
                chosen_song_id = int(chosen["song_id"])
                detail = cached_airplay_track_detail(
                    air_rev, tuple(sorted(int(x) for x in selected_ids)),
                    range_start.isoformat(), range_end.isoformat(), chosen_song_id,
                )
                st.markdown(f"### {chosen['artist']} — {chosen['title']}")
                spotify_url = spotify_search_url(str(chosen["artist"]), str(chosen["title"]))
                total_track_spins = int(detail.get("total_spins") or 0)
                track_station_count = int(detail.get("stations_count") or 0)
                track_reach = (100.0 * track_station_count / reporting_station_count) if reporting_station_count else None
                track_station_day = total_track_spins / period_days / max(1, track_station_count)
                track_rotation = min(100.0, 100.0 * track_station_day / 6.0)
                track_presence = (0.70 * track_reach + 0.30 * track_rotation) if track_reach is not None else None
                render_compact_metrics([
                    ("Emisje", total_track_spins),
                    (f"Stacje ({len(selected_ids)})", track_station_count),
                    ("Rotacja", f"{track_rotation:.0f}%" if track_reach is not None else "—"),
                    ("Radio Presence", f"{track_presence:.0f}%" if track_presence is not None else "—"),
                    ("Emisje/dzień łącznie", f"{total_track_spins / period_days:.1f}"),
                    ("Śr./grającą stację/dzień", f"{track_station_day:.2f}"),
                ], columns=6)
                st.caption(f"Ostatnia zapisana emisja: {str(detail.get('last_play') or '—').replace('T', ' ')}")

                chart_match = chart_latest[chart_latest.song_id.astype(int) == chosen_song_id] if not chart_latest.empty else pd.DataFrame()
                if not chart_match.empty:
                    chart_row = chart_match.iloc[0]
                    pos_bits = []
                    for src in ["RMF", "ZET", "OLIA", "OLIS", "ESKA"]:
                        pos = position_display(chart_row.get(f"{src}_pos"))
                        if pos != "-":
                            pos_bits.append(f"{src} #{pos}")
                    st.markdown("**Bieżące pozycje z notowań:** " + (" · ".join(pos_bits) if pos_bits else "brak w najnowszych notowaniach"))
                else:
                    st.caption("Brak tego utworu w najnowszych zapisanych notowaniach. Może nadal mieć starszą historię na karcie Utwór.")

                act1, act2, act3 = st.columns(3)
                with act1:
                    render_preview_button(chosen_song_id, str(chosen["artist"]), str(chosen["title"]), spotify_url)
                with act2:
                    st.link_button("Spotify ↗", spotify_url, use_container_width=True)
                with act3:
                    if st.button("Otwórz kartę utworu", key=f"airplay_open_song_{chosen_song_id}", use_container_width=True):
                        navigate_to_song(chosen_song_id)

                station_df = pd.DataFrame(detail.get("stations") or [])
                if not station_df.empty:
                    station_df["avg_active_day"] = (station_df["spins"] / station_df["active_days"].clip(lower=1)).round(1)
                    station_df["first_play"] = station_df["first_play"].astype(str).str.replace("T", " ", regex=False)
                    station_df["last_play"] = station_df["last_play"].astype(str).str.replace("T", " ", regex=False)
                    station_table = station_df[["station", "spins", "active_days", "avg_active_day", "first_play", "last_play"]].rename(columns={
                        "station": "Stacja",
                        "spins": "Emisje",
                        "active_days": "Dni z emisją",
                        "avg_active_day": "Śr./aktywny dzień",
                        "first_play": "Pierwsza emisja",
                        "last_play": "Ostatnia emisja",
                    })
                    st.markdown("#### Gdzie i jak często")
                    st.dataframe(station_table, hide_index=True, use_container_width=True)

                daily_df = pd.DataFrame(detail.get("daily") or [])
                if not daily_df.empty:
                    daily_total = daily_df.groupby("play_date", as_index=False)["spins"].sum()
                    daily_total["play_date"] = pd.to_datetime(daily_total["play_date"])
                    fig = px.bar(daily_total, x="play_date", y="spins", labels={"play_date": "Dzień", "spins": "Emisje"}, title="Emisje dzień po dniu")
                    fig.update_layout(height=360, margin=dict(t=50, b=40))
                    st.plotly_chart(fig, use_container_width=True)

                history_df = pd.DataFrame(detail.get("plays") or [])
                with st.expander("Dokładna historia emisji", expanded=False):
                    if history_df.empty:
                        st.caption("Brak zapisanych emisji.")
                    else:
                        history_df["played_at"] = history_df["played_at"].astype(str).str.replace("T", " ", regex=False)
                        history_table = history_df[["played_at", "station"]].rename(columns={"played_at": "Czas", "station": "Stacja"})
                        st.dataframe(history_table, hide_index=True, use_container_width=True, height=420)
                        if int(detail.get("total_spins") or 0) > len(history_table):
                            st.caption(f"Pokazuję ostatnie {len(history_table)} emisji; podsumowania powyżej liczą cały wybrany okres.")

        st.caption("Pobieranie, uzupełnianie 24h, backfill i zarządzanie stacjami są teraz w zakładce **Dane**.")

elif view_key == "data":
    st.subheader("⬇️ Dane i procesy")
    st.caption("Pobieranie działa w tle i można je zatrzymać. OLiA/OLiS wróciły do starszego, sprawdzonego mechanizmu renderowania/eksportu; UI pozostaje responsywne.")
    running = active_job() is not None

    health_df, health_problems = source_health_frame()
    with st.expander("Stan źródeł / świeżość danych", expanded=bool(health_problems)):
        st.dataframe(health_df, hide_index=True, use_container_width=True, height=285)
        st.caption("„Publikacja” opisuje typową kadencję źródła. „Powinno być ≥” używa semantyki daty danego źródła (okres / issue date / dzień odczytu), żeby nie porównywać różnych typów dat jak zwykłych dat publikacji.")

    with st.expander("🗃️ Co jest już zapisane w bazie notowań", expanded=False):
        archive_rows = chart_archive_summary()
        if archive_rows:
            archive_df = pd.DataFrame(archive_rows).rename(columns={
                "source": "Źródło", "issues": "Notowania", "first_date": "Najstarsze",
                "last_date": "Najnowsze", "entries": "Pozycje", "songs": "Różne utwory",
            })
            st.dataframe(archive_df, hide_index=True, use_container_width=True)
            st.caption(
                "Ta tabela pokazuje to, co fizycznie znajduje się w chart_issues/chart_entries. Dokładne luki da się wskazać tylko tam, "
                "gdzie źródło ma jednoznaczną kadencję/klucze archiwum; dla nowych backfilli pełny log 0.3.11 zapisuje każdą udaną i nieudaną próbę."
            )
        else:
            st.caption("Archiwum notowań jest puste.")

    st.markdown("### Bieżące notowania")
    fetch_main, _ = st.columns([1.7, 5.3])
    if fetch_main.button("Pobierz wszystkie automatyczne źródła", disabled=running, type="primary", use_container_width=True):
        start_job("collect-all")
        st.rerun()

    auto_sources = ["RMF", "ZET", "OLIA", "OLIS", "ESKA", "UK", "BILLBOARD"]
    for row_start in range(0, len(auto_sources), 4):
        row_sources = auto_sources[row_start:row_start + 4]
        cols = st.columns([1, 1, 1, 1, 3.2])
        for idx, src in enumerate(row_sources):
            if cols[idx].button(f"Pobierz {src}", disabled=running, use_container_width=True, key=f"fetch_{src}"):
                start_job("collect-source", source=src)
                st.rerun()

    render_job_status_fragment("collect", "collect")


    st.divider()
    st.markdown("### Backfille notowań")
    st.caption("Wszystkie kontrolki są razem, a przebieg procesu jest bezpośrednio pod nimi i odświeża się automatycznie. Limity bezpieczeństwa odpowiadają maksymalnie ok. 5 lat historii (RMF 1300, ZET 1825, listy tygodniowe 260).")

    b1, b2, b3, b4, _ = st.columns([1, 1, 1, 1, 2.7])
    rmf_count = b1.number_input("RMF · notowania", min_value=5, max_value=1300, value=130, step=5)
    zet_count = b2.number_input("ZET · notowania", min_value=2, max_value=1825, value=30, step=1)
    uk_count = b3.number_input("UK · tygodnie", min_value=2, max_value=260, value=26, step=1)
    bb_count = b4.number_input("Billboard · tygodnie", min_value=2, max_value=260, value=26, step=1)
    if b1.button("Backfill RMF", disabled=running, use_container_width=True):
        start_job("backfill", source="RMF", count=int(rmf_count)); st.rerun()
    if b2.button("Backfill ZET", disabled=running, use_container_width=True):
        start_job("backfill", source="ZET", count=int(zet_count)); st.rerun()
    if b3.button("Backfill UK", disabled=running, use_container_width=True):
        start_job("backfill", source="UK", count=int(uk_count)); st.rerun()
    if b4.button("Backfill Billboard", disabled=running, use_container_width=True):
        start_job("backfill", source="BILLBOARD", count=int(bb_count)); st.rerun()

    o1, o2, _ = st.columns([1, 1, 4.7])
    olia_count = o1.number_input("OLiA · tygodnie", min_value=2, max_value=260, value=12, step=1)
    olis_count = o2.number_input("OLiS · tygodnie", min_value=2, max_value=260, value=12, step=1)
    if o1.button("Backfill OLiA", disabled=running, use_container_width=True):
        start_job("backfill", source="OLIA", count=int(olia_count)); st.rerun()
    if o2.button("Backfill OLiS", disabled=running, use_container_width=True):
        start_job("backfill", source="OLIS", count=int(olis_count)); st.rerun()

    a1, a2, a3, _ = st.columns([1.75, 1.25, 1.25, 2.3])
    if a1.button("Backfill RMF + ZET + UK + Billboard", disabled=running, use_container_width=True):
        start_job("backfill-all", params={
            "rmf_count": int(rmf_count), "zet_count": int(zet_count),
            "uk_count": int(uk_count), "billboard_count": int(bb_count),
        })
        st.rerun()
    if a2.button("Backfill OLiA + OLiS", disabled=running, use_container_width=True):
        start_job("backfill-all", params={"olia_count": int(olia_count), "olis_count": int(olis_count)})
        st.rerun()
    if a3.button("Backfill wszystkie 6", disabled=running, type="primary", use_container_width=True):
        start_job("backfill-all", params={
            "rmf_count": int(rmf_count), "zet_count": int(zet_count),
            "uk_count": int(uk_count), "billboard_count": int(bb_count),
            "olia_count": int(olia_count), "olis_count": int(olis_count),
        })
        st.rerun()

    render_job_status_fragment("backfill", "backfill")

    st.divider()
    render_airplay_data_management(running)

    st.divider()
    st.markdown("### Ostatnie zapisane notowania")
    with st.expander("Lista ostatnich wydań", expanded=False):
        for item in latest_issues():
            st.caption(f"**{item['source']}** · {item['chart_date']} · {item['entries']} pozycji")


else:
    st.markdown("## 📘 Manual RadioCharts")
    st.caption("Co pokazuje każda zakładka, jak czytać wskaźniki i jak odróżniać dane z list przebojów od realnych emisji radiowych.")

    with st.expander("1. Najkrótsza ścieżka pracy", expanded=True):
        st.markdown(
            """
1. **Dane** — sprawdź, czy źródła są świeże i czy backfill nie ma luk.
2. **Dashboard** — znajdź utwory warte odsłuchu; sortuj po Familiarity, Momentum i Radio Presence.
3. **Utwór** — zobacz pełną historię pozycji, emisje, odsłuchaj i ustaw własny status/notatkę.
4. **Emisje** — sprawdź, co faktycznie grają stacje, jak szeroko i jak często.
5. **Notowania** — podejrzyj konkretny historyczny tydzień/listę bez mieszania go z bieżącym stanem.

**Status, „Przesłuchany” i Notatka są wspólne** dla wszystkich zakładek. To ten sam rekord utworu, niezależnie od tego, czy trafiłeś do niego z notowania czy z emisji.

Aktualna kolejność statusów roboczych: **Nie słuchałem → Watch → R1 Candidate → CF Candidate → Baza Hold → Słabe → Baza R2 → Baza R1 → Baza CF2 → Baza CF1 → Poza formatem**. Stare `Candidate` jest migrowane do `CF Candidate`, `Ignore` do `Poza formatem`, a `Poza bazą` do `Baza Hold`.
            """
        )

    with st.expander("2. Dashboard — zakresy i filtry", expanded=True):
        st.markdown(
            """
**Okres wskaźników** określa, z jak długiej historii list przebojów liczymy Familiarity i Momentum. `Całość` najlepiej opisuje trwałą znajomość utworu; krótsze okresy są przydatne do analizowania świeżych zmian.

**W najnowszych notowaniach** oznacza: utwór znajduje się w **najnowszym zapisanym notowaniu przynajmniej jednego źródła** w danej grupie. To nie znaczy „pojawił się gdzieś w ostatnio pobranych danych”.

- **W najnowszych notowaniach** — dowolne z PL + UK/Billboard.
- **PL w najnowszych** — RMF, ZET, OLiA, OLiS lub ESKA.
- **Zagraniczne w najnowszych** — UK lub Billboard.
- **Cała historia** — również utwory, które już zeszły ze wszystkich najnowszych list.

Minimalne Familiarity/Momentum są tylko filtrami tabeli — nie zmieniają obliczeń. Pole **Szukaj w Dashboardzie** filtruje po wykonawcy i tytule, ignoruje polskie znaki i działa na całym aktualnym zakresie przed wyrenderowaniem tabeli.

**Śr. poz.** to zwykła średnia arytmetyczna z bieżących pozycji **RMF, ZET, ESKA, OLiA i OLiS**, ale tylko z tych list, na których utwór aktualnie występuje. To szybki skrót orientacyjny, nie osobny scoring.

**Premiera** jest pokazywana jako `YYYY/MM`. Gdy baza ma dokładną datę wydania, miesiąc jest bez prefiksu. `~YYYY/MM` oznacza, że dokładnej daty nie mamy i pokazujemy miesiąc **pierwszego pojawienia się w naszych notowaniach**.
            """
        )

    with st.expander("3. Familiarity — jak bardzo utwór powinien być znany", expanded=True):
        st.markdown(
            """
Familiarity jest **pamięcią sukcesu na listach**, a nie wskaźnikiem „czy utwór jest gorący dzisiaj”. Po zejściu z listy ma spadać bardzo powoli.

Najpierw pozycja jest zamieniana na siłę 0–100 z uwzględnieniem długości listy. Dla każdego źródła Familiarity składa się z:

- **35% Peak** — jak wysoko utwór zaszedł,
- **30% Longevity** — jak długo był obecny (pełne 100 przy ok. 10 tygodniach),
- **20% Top 10 persistence** — ile tygodni utrzymywał się w Top 10 (pełne 100 przy 6 tygodniach),
- **15% Memory** — pamięć najlepszego wyniku, wygaszana bardzo wolno z czasem; stała wygaszania to ok. **52 tygodnie**.

Wagi polskich źródeł w wyniku końcowym:

| Źródło | Waga |
|---|---:|
| OLiA | 30% |
| RMF | 25% |
| ZET | 20% |
| OLiS | 15% |
| ESKA | 10% |

Przykład: wielki przebój po miesiącu bez obecności na liście nadal powinien mieć wysokie Familiarity. To, że **teraz** przestaje być grany/promowany, ma być widoczne przede wszystkim w Momentum i Radio Presence, nie przez gwałtowne „zapominanie”.
            """
        )

    with st.expander("4. Momentum — co dzieje się teraz na listach", expanded=False):
        st.markdown(
            """
Momentum jest celowo **chart-only**. Patrzy na zmianę siły pozycji w maksymalnie czterech ostatnich tygodniowych punktach danego źródła.

- około **50%** — stabilnie,
- **>65%** — wyraźny wzrost,
- **<40%** — spadek.

Po zejściu z listy stary trend szybko traci znaczenie: wynik jest dodatkowo wygaszany ze stałą ok. **2,5 tygodnia**. Dzięki temu utwór może mieć np. Familiarity 80%, ale Momentum 10% — czyli „wszyscy go znają, lecz obecnie nie rośnie na listach”.

Emisje radiowe nie są dodawane do Momentum.
            """
        )

    with st.expander("5. Radio Presence — szerokość + intensywność grania", expanded=True):
        st.markdown(
            """
Radio Presence opisuje **realną bieżącą obecność na antenach** i jest niezależne od list przebojów.

**Zasięg stacji** = procent raportujących stacji, które zagrały utwór przynajmniej raz.

**Rotacja** = jak często utwór jest grany na stacjach, które go grają. Liczymy średnią `emisje / grająca stacja / dzień` i skalujemy ją tak, że:

- ok. **1 emisja/stację/dzień ≈ 17% rotacji** — typowy lekko rotowany gold,
- **3 emisje/stację/dzień ≈ 50%**,
- **6 lub więcej/stację/dzień = 100%** — bardzo mocna rotacja/current.

**Radio Presence = 70% Zasięgu + 30% Rotacji.**

Zasięg ma większą wagę, bo utwór obecny w 40 różnych stacjach jest innym sygnałem niż utwór grany bardzo często przez jedną stację. Rotacja powoduje jednak, że recurrent grany 7× dziennie nie wygląda tak samo jak gold grany 1× dziennie.

Na karcie Utwór/Dashboard domyślnie jest to sygnał z **ostatnich 7 dni**. W rankingu Emisji analogiczne parametry są liczone dla aktualnie wybranego zakresu dat.
            """
        )

    with st.expander("6. Emisje — znaczenie wszystkich parametrów", expanded=True):
        st.markdown(
            """
**Emisja** to jedno zapisane odtworzenie utworu przez jedną stację.

- **Emisje** — suma wszystkich odtworzeń ze wszystkich wybranych stacji w okresie.
- **Stacje (N)** — liczba stacji, które zagrały utwór co najmniej raz; `N` w nagłówku to liczba stacji w aktualnym filtrze.
- **Rotacja** — intensywność grania na stacjach, które grają utwór; 6+/stację/dzień = 100%.
- **Radio Presence** — `70% zasięgu + 30% rotacji`. Sam zasięg nadal jest liczony jako `stacje grające / stacje raportujące`, ale nie ma osobnej kolumny, bo praktycznie dublował informację z liczby stacji.
- **Emisje/dzień łącznie** — wszystkie emisje utworu / liczba dni kalendarzowych. **17 oznacza 17 odtworzeń dziennie łącznie w całej wybranej grupie stacji, nie 17 na każdej stacji.**
- **Śr./grającą stację/dzień** — emisje / dni / liczba stacji, które faktycznie zagrały utwór.
- **Max/stacja** — ile razy najaktywniejsza stacja zagrała utwór w całym wybranym okresie.
- **Najmocniejsza stacja** — stacja z największą liczbą emisji tego utworu.
- **Ostatnio** — ostatnia zapisana godzina emisji.

Zakres Emisji można ustawić jednym rozwijanym polem: **ostatni tydzień / 2 tygodnie / miesiąc / 3 miesiące / pół roku / rok**. Opcja **Własny zakres** pokazuje dokładny wybór dat. Szybkie zakresy kończą się na najnowszym dniu, dla którego mamy zapisane dane emisji, a nie na „dzisiaj” za wszelką cenę.

W zakładce **Najczęściej grane** pole wyszukiwania filtruje **cały wybrany okres**, zanim zadziała limit `Pokaż 50/100/...`. W **Sprawdź utwór** wyszukiwanie jest znormalizowane (np. `meskie` = `męskie`) i pokazuje tylko rzeczywiste dopasowania, bez fuzzy-searchu po przypadkowych podobnych słowach.

Na karcie **Utwór** jest osobna sekcja **Emisje radiowe** z takim samym wyborem zakresu. Pokazuje sumę emisji, liczbę stacji, średnią dzienną i średnią na grającą stację. Rozwijane **Szczegóły emisji per stacja i dzień** dodają tabelę stacji oraz niewielki wykres dzienny bez rozpychania całej karty.

W szczegółach jednego utworu:

- **Dni z emisją** — w ilu dniach konkretna stacja zagrała utwór przynajmniej raz,
- **Śr./aktywny dzień** — emisje tej stacji / tylko dni, w których ta stacja faktycznie go zagrała,
- **Pierwsza/Ostatnia emisja** — granice zapisanej historii w wybranym okresie.

**Stacja raportująca** = stacja, dla której mamy przynajmniej jedną zapisaną emisję w wybranym okresie. To ważne: stacja bez playlisty/RDS nie obniża sztucznie zasięgu, jeżeli została rozpoznana jako nieraportująca.
            """
        )

    with st.expander("7. Pokrycie emisji i bloki 2h", expanded=False):
        st.markdown(
            """
odSluchane udostępnia historię w **blokach po 2 godziny**. Pełna zakończona doba jednej stacji to **12 bloków**.

- **Pokrycie bloków 2h `X/Y`** — ile oczekiwanych bloków zakończyło się poprawnym pobraniem.
- **Bloki OK** — poprawnie sprawdzone okna.
- **Brakuje** — zakończone okna, których nie mamy.
- **Puste bloki** — serwis odpowiedział poprawnie, ale parser znalazł 0 emisji. To coś innego niż brak pobrania.

Ranking Emisji liczy tylko to, co faktycznie jest zapisane. Przy niepełnym pokryciu wyniki mogą być zaniżone.
            """
        )

    with st.expander("8. Utwór i identyfikacja między źródłami", expanded=False):
        st.markdown(
            """
RadioCharts próbuje utrzymywać **jeden wspólny rekord utworu** dla notowań i emisji. RDS potrafi jednak zapisać ten sam numer z innym zestawem wykonawców. System łączy bezpieczne warianty, gdy tytuł jest wystarczająco charakterystyczny i jednoznacznie wskazuje jeden utwór z historii notowań.

Nie robimy agresywnego łączenia krótkich tytułów typu „Home” czy „Stay”, bo łatwo byłoby skleić dwa różne nagrania. Jeżeli Emisje pokazują podejrzanie małą liczbę odtworzeń dla znanego hitu, pierwszą rzeczą do sprawdzenia są właśnie warianty kredytu RDS.

Wyszukiwarka Utwór pokazuje przede wszystkim utwory z notowań oraz te, którym nadałeś status/notatkę. Surowe, jednorazowe warianty RDS nie zaśmiecają selektora; nadal można je otworzyć bezpośrednio z Emisji.
            """
        )

    with st.expander("9. Format Fit — dlaczego został wycofany", expanded=False):
        st.markdown(
            """
**Format Fit nie jest już pokazywany.** Sama pozycja na RMF/ZET/ESKA/OLiA nie mówi wiarygodnie, czy nagranie pasuje do konkretnego Mainstream AC.

Przykład: utwór może być wielkim hitem w źródłach, a brzmieniowo być dance/CHR, rockiem lub inną estetyką niepasującą do Twojego formatu. Żeby uczciwie przywrócić Format Fit, potrzebowalibyśmy dodatkowych danych — np. ręcznych tagów formatu/soundcode, cech audio albo wytrenowania wyniku na Twoich realnych decyzjach programowych. Do tego czasu lepiej nie pokazywać precyzyjnie wyglądającego, ale mylącego procentu.
            """
        )

    with st.expander("10. Dane, backfill i logi", expanded=False):
        st.markdown(
            """
Zakładka **Dane** służy do całej obsługi pobierania: bieżących notowań, backfillu list oraz **backfillu Emisji / odSluchane**. Tabela „Stan źródeł” pokazuje kadencję publikacji, najnowsze pobrane notowanie oraz datę, której co najmniej oczekujemy dzisiaj. „Co jest już zapisane” pokazuje fizycznie zapisane wydania, zakres dat, liczbę pozycji i utworów.

Każdy nowy proces zapisuje pełny log w `/app/data/jobs/`. Nazwa zaczyna się od czasu uruchomienia:

`YYYY-MM-DD_HH-MM-SS_typ-procesu_jobid.log`

Dzięki temu pliki sortują się chronologicznie. JSON joba nadal ma osobny identyfikator i wskazuje właściwy `log_file`.

Worker sprawdza automatyczne źródła dwa razy dziennie — 07:30 i 20:30 czasu Europe/Warsaw. Nieudane pobranie nie usuwa ostatniego poprawnego notowania.
            """
        )

    with st.expander("11. Spotify, odsłuch i własna ocena", expanded=False):
        st.markdown(
            """
**▶ 30s** uruchamia podgląd Apple/iTunes w przyklejonym odtwarzaczu. **Spotify ↗** otwiera wyszukiwanie wykonawca + tytuł. Kolumna **Kopiuj (⧉)** kopiuje ten sam link Spotify do schowka; działa też na zwykłym HTTP w sieci LAN dzięki fallbackowi `execCommand`.

Twoje pola **Przesłuchany, Status i Notatka** są warstwą redakcyjną i nie zmieniają automatycznych wskaźników. Notatka jest celowo ostatnią kolumną tabel, żeby nie zabierała miejsca najważniejszym danym liczbowym.
            """
        )
