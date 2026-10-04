from __future__ import annotations

import html
import json
import math
import re
from pathlib import Path
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
from radiocharts.airplay import AIRPLAY_BACKFILL_MAX_WINDOWS, completed_windows_in_range
from radiocharts.db import (
    airplay_coverage, airplay_dashboard_metrics, airplay_dashboard_spin_counts, airplay_data_revision,
    airplay_presence_summary, airplay_revision, airplay_song_presence, airplay_station_coverage,
    airplay_spin_counts, airplay_summary, airplay_track_detail_by_song, canonical_song_id, chart_archive_summary, chart_revision, get_song, init_db,
    issue_entries, issue_entries_enriched, latest_chart_positions, latest_issues, latest_source_checks,
    source_check_day_summary, list_airplay_stations, list_issues, load_notes, normalize, song_catalog, song_catalog_revision, catalog_revision,
    parse_radio_library_tsv, radio_library_catalog, radio_library_overview, set_airplay_station_active, sync_radio_library_tsv, update_note,
    merge_song_group,
)
from radiocharts.job_manager import active_job, latest_job, read_job_log, start_job, stop_job
from radiocharts.local_station import (
    EVENT_TYPES as LOCAL_EVENT_TYPES,
    GSELECTOR_SONG_COLUMNS as LOCAL_GSELECTOR_SONG_COLUMNS,
    available_dates as local_available_dates,
    compare_day as local_compare_day,
    compare_hour as local_compare_hour,
    day_summary as local_day_summary,
    ensure_seed_data as ensure_local_station_seed_data,
    ensure_song_links_current as ensure_local_station_song_links,
    events_for_day as local_events_for_day,
    import_gselector_export as import_local_gselector_export,
    import_history as local_import_history,
    local_station_revision,
    delete_import as delete_local_import,
    preview_import as preview_local_import,
    song_stats as local_song_stats,
    song_activity as local_song_activity,
    sync_zetta2go_live as local_sync_zetta2go_live,
    sync_zetta2go_schedule_horizon as local_sync_zetta2go_schedule_horizon,
    test_zetta2go_connection as local_test_zetta2go_connection,
)
from radiocharts.zetta2go import settings as zetta2go_settings, save_settings as save_zetta2go_settings
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
        padding-top: .85rem !important;
        padding-bottom: 8rem !important;
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
      .rc-control-label { font-size:.76rem; line-height:1.18; margin:0 0 .08rem 0; min-height:.90rem; display:flex; align-items:flex-end; color:inherit; }
      [data-testid="stPopover"] button { min-height:2.1rem !important; height:2.1rem !important; width:100% !important; padding-top:.15rem !important; padding-bottom:.15rem !important; }
      [data-testid="stTextInput"] input:disabled { color:#f3f4f6 !important; -webkit-text-fill-color:#f3f4f6 !important; opacity:1 !important; font-weight:650 !important; text-align:center !important; }
      [data-testid="stForm"] { padding:.55rem .7rem !important; }
      [data-testid="stVerticalBlock"] { gap: .58rem !important; }
      [data-testid="stHorizontalBlock"] { gap: .6rem !important; }
      iframe[title="st.iframe"] { min-height: 0 !important; }
      .rc-app-title { display:flex; align-items:center; gap:.46rem; font-size:1.92rem; font-weight:760; line-height:1.05; margin:0 0 .06rem; min-height:2.05rem; }
      .rc-app-subtitle { color:#9aa3af; font-size:.76rem; margin-bottom:.24rem; }
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
      .rc-etm-grid { display:grid; grid-template-columns:repeat(6,minmax(0,1fr)); gap:.28rem; margin:.18rem 0 .48rem; }
      .rc-etm-chip { display:grid; grid-template-columns:auto 1fr auto auto; gap:.32rem; align-items:center; border:1px solid #46505f; background:#11161d; border-radius:5px; padding:.24rem .38rem; min-width:0; font-size:.75rem; }
      .rc-etm-zero { opacity:.48; }
      .rc-etm-time { color:#b9c2cf; font-variant-numeric:tabular-nums; }
      .rc-etm-kind { color:#f4cf57; font-weight:650; overflow:hidden; text-overflow:ellipsis; }
      .rc-etm-gap { color:#f4f4f5; font-weight:700; font-variant-numeric:tabular-nums; }
      .rc-etm-risk { color:#f4b942; font-weight:800; cursor:help; }
      @media (max-width: 1100px) { .rc-etm-grid { grid-template-columns:repeat(4,minmax(0,1fr)); } }
      @media (max-width: 640px) {
        .rc-etm-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
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

VALID_VIEW_KEYS = {"dashboard", "song", "archive", "airplay", "library", "our_radio", "data", "settings", "methodology"}
BOOT_VIEW_KEY = str(st.query_params.get("view", "dashboard"))
if BOOT_VIEW_KEY not in VALID_VIEW_KEYS:
    BOOT_VIEW_KEY = "dashboard"


@st.cache_resource(show_spinner=False)
def _bootstrap_local_station_seed_once() -> dict:
    # The bundled GSelector seed is only needed by EMAUS/song views. Keeping it
    # out of the global startup path avoids a file lock + SQLite round-trip on
    # every first render of Dashboard/Emisje/Baza after a process restart.
    return ensure_local_station_seed_data()


@st.cache_resource(show_spinner=False, max_entries=16)
def _cached_local_station_song_links(catalog_rev: str) -> dict:
    # Unmatched EMAUS rows need a relink only when the shared song catalogue
    # changes. Import itself already links against the current catalogue.
    return ensure_local_station_song_links()


init_db()
# EMAUS seed/relink is intentionally deferred until an EMAUS subview (or a song
# EMAUS panel) is actually rendered. This keeps the first application paint out
# of the local-station maintenance path.


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
        "popularity": st.column_config.ProgressColumn(
            "Popularity", help="Bieżąca popularność: głównie emisje z ostatnich 28 dni + bonus za pozycje na listach.", format="%.0f%%", min_value=0.0, max_value=100.0
        ),
        "familiarity": st.column_config.ProgressColumn(
            "Chart Score", help="Historyczna siła utworu w obserwowanych notowaniach.", format="%.0f%%", min_value=0.0, max_value=100.0
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
    "Dzisiaj (1d)",
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
    if label == "Dzisiaj (1d)":
        start = end_date
    elif label == "Ostatni tydzień":
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
    """Preset dropdown + always-visible exact dates. Manual edits switch preset to Custom."""
    preset_key = f"{key_prefix}_preset"
    dates_key = f"{key_prefix}_dates"
    anchor_key = f"{key_prefix}_anchor"

    if default_preset not in AIRPLAY_QUICK_RANGES:
        default_preset = "Ostatni tydzień"
    if preset_key not in st.session_state:
        st.session_state[preset_key] = default_preset
    if dates_key not in st.session_state:
        st.session_state[dates_key] = airplay_quick_range(default_preset, default_end, earliest)

    # If new airplay arrived and the user is still on a quick preset, move the
    # range forward with the data. A manually edited Custom range stays put.
    previous_anchor = st.session_state.get(anchor_key)
    if previous_anchor != default_end.isoformat():
        if st.session_state.get(preset_key) != "Własny zakres":
            st.session_state[dates_key] = airplay_quick_range(str(st.session_state[preset_key]), default_end, earliest)
        st.session_state[anchor_key] = default_end.isoformat()

    def _preset_changed() -> None:
        preset = str(st.session_state.get(preset_key) or default_preset)
        if preset != "Własny zakres":
            st.session_state[dates_key] = airplay_quick_range(preset, default_end, earliest)

    def _dates_changed() -> None:
        value = st.session_state.get(dates_key)
        if isinstance(value, (list, tuple)) and len(value) == 2:
            start, end = value
        elif isinstance(value, date):
            start = end = value
        else:
            return
        if end < start:
            start, end = end, start
        preset = str(st.session_state.get(preset_key) or default_preset)
        if preset != "Własny zakres":
            expected = airplay_quick_range(preset, default_end, earliest)
            if (start, end) != expected:
                st.session_state[preset_key] = "Własny zakres"

    c1, c2 = st.columns([1.05, 2.2])
    c1.selectbox(
        "Zakres dat",
        AIRPLAY_QUICK_RANGES,
        key=preset_key,
        on_change=_preset_changed,
        help="Preset tylko ustawia daty po prawej. Możesz je potem ręcznie zmienić — zakres automatycznie przejdzie na Własny zakres.",
    )
    selected = c2.date_input(
        "Daty",
        key=dates_key,
        min_value=earliest,
        max_value=default_end,
        on_change=_dates_changed,
        help="Zakres jest inkluzywny i zawsze można go edytować ręcznie.",
    )
    if isinstance(selected, (list, tuple)) and len(selected) == 2:
        start, end = selected
    else:
        start = end = selected if isinstance(selected, date) else default_end
    if end < start:
        start, end = end, start
    if earliest is not None and start < earliest:
        start = earliest
    if end > default_end:
        end = default_end
    if start > end:
        start = end
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


POPULARITY_CHART_WEIGHTS = {"OLIA": 35.0, "OLIS": 25.0, "RMF": 20.0, "ZET": 12.0, "ESKA": 8.0}
POPULARITY_CHART_SIZES = {"OLIA": 100, "OLIS": 100, "RMF": 20, "ZET": 20, "ESKA": 20}


@st.cache_resource(show_spinner=False, max_entries=8)
def cached_dashboard_airplay(revision: str) -> dict:
    # Dashboard needs 7d radio breadth and 28d volume. Compute both in one SQL
    # pass instead of two full GROUP BY scans over airplay_plays.
    return airplay_dashboard_metrics(days=28, recent_days=7)


@st.cache_resource(show_spinner=False, max_entries=24)
def cached_dashboard_period_spins(revision: str, start_iso: str = "", end_iso: str = "") -> list[dict]:
    return airplay_dashboard_spin_counts(start_iso or None, end_iso or None)


@st.cache_resource(show_spinner=False, max_entries=8)
def cached_airplay_popularity(revision: str, days: int = 28) -> pd.DataFrame:
    """Relative airplay volume score for a fixed recent window.

    The score is a percentile of total plays among songs that actually received
    at least one play in the window.  It is intentionally independent of the
    current Emisje date filter, so Popularity is comparable between tables.
    """
    rows = pd.DataFrame(cached_airplay_presence(revision, days).get("rows") or [])
    if rows.empty or "song_id" not in rows.columns or "spins" not in rows.columns:
        return pd.DataFrame(columns=["song_id", "airplay_volume_index", "airplay_spins_pop_window"])
    rows = rows[rows["song_id"].notna()].copy()
    rows["song_id"] = rows["song_id"].astype(int)
    rows["spins"] = pd.to_numeric(rows["spins"], errors="coerce").fillna(0)
    rows = rows.groupby("song_id", as_index=False)["spins"].sum()
    positive = rows["spins"] > 0
    rows["airplay_volume_index"] = 0.0
    if positive.any():
        rows.loc[positive, "airplay_volume_index"] = (
            rows.loc[positive, "spins"].rank(method="average", pct=True) * 100.0
        )
    rows["airplay_spins_pop_window"] = rows["spins"].astype(int)
    return rows[["song_id", "airplay_volume_index", "airplay_spins_pop_window"]]


def _chart_popularity_bonus(frame: pd.DataFrame) -> pd.Series:
    """0–100 chart component, with intentionally larger OLiA/OLiS weights."""
    if frame.empty:
        return pd.Series(dtype=float)
    total_weight = sum(POPULARITY_CHART_WEIGHTS.values())
    bonus = pd.Series(0.0, index=frame.index)
    for src, weight in POPULARITY_CHART_WEIGHTS.items():
        col = f"{src}_pos"
        if col not in frame.columns:
            continue
        pos = pd.to_numeric(frame[col], errors="coerce")
        size = float(POPULARITY_CHART_SIZES[src])
        # Missing source = zero bonus. #1 = 100, bottom of the list ≈ 0.
        score = (100.0 * (size - pos) / max(1.0, size - 1.0)).clip(lower=0.0, upper=100.0).fillna(0.0)
        bonus = bonus + float(weight) * score
    return (bonus / max(1.0, total_weight)).round(1)


def with_popularity(frame: pd.DataFrame, air_rev: str) -> pd.DataFrame:
    """Attach Popularity = 80% recent airplay volume + 20% chart bonus."""
    out = frame.copy()
    if out.empty or "song_id" not in out.columns:
        return out
    air = cached_airplay_popularity(air_rev, 28)
    if not air.empty:
        out = out.merge(air, on="song_id", how="left")
    if "airplay_volume_index" not in out.columns:
        out["airplay_volume_index"] = 0.0
    out["airplay_volume_index"] = pd.to_numeric(out["airplay_volume_index"], errors="coerce").fillna(0.0)
    out["chart_popularity_bonus"] = _chart_popularity_bonus(out)
    out["popularity"] = (
        0.80 * out["airplay_volume_index"] + 0.20 * out["chart_popularity_bonus"]
    ).clip(lower=0.0, upper=100.0).round(1)
    return out


def with_dashboard_airplay(frame: pd.DataFrame, air_data_rev: str) -> pd.DataFrame:
    """Attach all Dashboard airplay metrics from one cached 28-day scan."""
    out = frame.copy()
    if out.empty or "song_id" not in out.columns:
        return out
    snapshot = cached_dashboard_airplay(air_data_rev)
    rows = pd.DataFrame(snapshot.get("rows") or [])
    reporting = int(snapshot.get("reporting_stations") or 0)
    if not rows.empty and "song_id" in rows.columns:
        rows["song_id"] = rows["song_id"].astype(int)
        rows["spins_28d"] = pd.to_numeric(rows.get("spins_28d"), errors="coerce").fillna(0)
        positive = rows["spins_28d"] > 0
        rows["airplay_volume_index"] = 0.0
        if positive.any():
            rows.loc[positive, "airplay_volume_index"] = (
                rows.loc[positive, "spins_28d"].rank(method="average", pct=True) * 100.0
            )
        rows["airplay_spins_pop_window"] = rows["spins_28d"].astype(int)
        keep = [
            "song_id", "airplay_volume_index", "airplay_spins_pop_window",
            "radio_presence", "radio_reach", "radio_rotation",
            "airplay_spins_7d", "airplay_stations_count",
            "airplay_spins_per_day", "airplay_spins_per_station_day", "airplay_last_play",
        ]
        out = out.merge(rows[[c for c in keep if c in rows.columns]], on="song_id", how="left")
    for col in ["radio_presence", "radio_reach", "radio_rotation", "airplay_spins_per_day", "airplay_spins_per_station_day", "airplay_volume_index"]:
        if col not in out.columns:
            out[col] = 0.0 if reporting else float("nan")
        elif reporting:
            out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)
    for col in ["airplay_spins_7d", "airplay_stations_count", "airplay_spins_pop_window"]:
        if col not in out.columns:
            out[col] = 0
        else:
            out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0).astype(int)
    out["airplay_reporting_stations"] = reporting
    out["airplay_presence_days"] = int(snapshot.get("recent_days") or 7)
    out["chart_popularity_bonus"] = _chart_popularity_bonus(out)
    out["popularity"] = (
        0.80 * pd.to_numeric(out["airplay_volume_index"], errors="coerce").fillna(0.0)
        + 0.20 * out["chart_popularity_bonus"]
    ).clip(lower=0.0, upper=100.0).round(1)
    return out


@st.cache_resource(show_spinner=False, max_entries=24)
def cached_dashboard_base_frame(chart_rev: str, air_rev: str, lookback_days: int = 0) -> pd.DataFrame:
    """Chart + recent-airplay Dashboard base, cached across UI reruns.

    Slider/search/status changes rerun the Streamlit script.  Before 1.2.8 each
    rerun rebuilt the airplay DataFrame, percentile rank and pandas merge even
    though neither chart nor airplay data had changed.  Keep that immutable base
    cached and overlay only live notes/status afterwards.
    """
    scored = cached_scores(chart_rev, lookback_days=int(lookback_days or 0))
    return with_dashboard_airplay(scored, air_rev)


@st.cache_resource(show_spinner=False, max_entries=48)
def cached_basic_song_metrics(chart_rev: str, air_rev: str, song_key: tuple[int, ...]) -> pd.DataFrame:
    """Standard table metrics for a bounded set of songs.

    Keeps Emisje fast: score only rows that are actually displayed, while
    Zasięg 7d / Emisje 7d and Popularity reuse cached recent-airplay aggregates.
    """
    ids = sorted({int(x) for x in song_key})
    base = pd.DataFrame({"song_id": ids})
    if not ids:
        return base
    scored = compute_scores(song_ids=ids)
    score_cols = [
        "song_id", "familiarity", "momentum",
        "RMF_pos", "RMF_weeks", "ZET_pos", "ZET_weeks",
        "ESKA_pos", "ESKA_weeks", "OLIA_pos", "OLIA_weeks", "OLIS_pos", "OLIS_weeks",
    ]
    if not scored.empty:
        base = base.merge(scored[[c for c in score_cols if c in scored.columns]].drop_duplicates("song_id"), on="song_id", how="left")
    presence = pd.DataFrame(cached_airplay_presence(air_rev, 7).get("rows") or [])
    if not presence.empty:
        keep = [c for c in ["song_id", "radio_reach", "spins"] if c in presence.columns]
        ref = presence[keep].drop_duplicates("song_id").rename(columns={"spins": "airplay_spins_7d"})
        base = base.merge(ref, on="song_id", how="left")
    if "airplay_spins_7d" not in base.columns:
        base["airplay_spins_7d"] = 0
    base["airplay_spins_7d"] = pd.to_numeric(base["airplay_spins_7d"], errors="coerce").fillna(0).astype(int)
    core = [c for c in ["RMF_pos", "ZET_pos", "ESKA_pos", "OLIA_pos", "OLIS_pos"] if c in base.columns]
    base["avg_position"] = base[core].apply(pd.to_numeric, errors="coerce").mean(axis=1).round(1) if core else float("nan")
    return with_popularity(base, air_rev)


@st.cache_resource(show_spinner=False, max_entries=256)
def cached_song_history(revision: str, song_id: int) -> pd.DataFrame:
    return song_history(int(song_id))


@st.cache_resource(show_spinner=False, max_entries=4)
def cached_song_catalog(revision: str) -> pd.DataFrame:
    return pd.DataFrame(song_catalog())


@st.cache_resource(show_spinner=False, max_entries=12)
def cached_airplay_stations(revision: str, active_only: bool = True) -> list[dict]:
    # Station metadata changes much less often than Streamlit reruns. Keeping it
    # behind the airplay revision removes several SQLite opens on every tab switch.
    return list_airplay_stations(active_only=bool(active_only))


@st.cache_resource(show_spinner=False, max_entries=48)
def cached_airplay_coverage(
    revision: str, station_key: tuple[int, ...], start_iso: str = "", end_iso: str = ""
) -> dict:
    return airplay_coverage(station_key, start_iso or None, end_iso or None)


@st.cache_resource(show_spinner=False, max_entries=48)
def cached_airplay_station_coverage(
    revision: str, station_key: tuple[int, ...], start_iso: str, end_iso: str
) -> list[dict]:
    return airplay_station_coverage(station_key, start_iso, end_iso)


@st.cache_resource(show_spinner=False, max_entries=12)
def cached_radio_library_catalog(revision: str) -> pd.DataFrame:
    # The library query also resolves first chart appearances. Cache the complete
    # frame and copy before view-specific mutations. The revision changes after
    # notes/status edits or new chart entries.
    return pd.DataFrame(radio_library_catalog())


@st.cache_resource(show_spinner=False, max_entries=24)
def cached_airplay_summary(revision: str, station_key: tuple[int, ...], start_iso: str, end_iso: str) -> list[dict]:
    return airplay_summary(station_key, start_iso, end_iso)


@st.cache_resource(show_spinner=False, max_entries=24)
def cached_airplay_spin_counts(revision: str, station_key: tuple[int, ...], start_iso: str, end_iso: str) -> list[dict]:
    return airplay_spin_counts(station_key, start_iso, end_iso)


@st.cache_resource(show_spinner=False, max_entries=64)
def cached_airplay_track_detail(revision: str, station_key: tuple[int, ...], start_iso: str, end_iso: str, song_id: int) -> dict:
    return airplay_track_detail_by_song(station_key, start_iso, end_iso, int(song_id))


@st.cache_resource(show_spinner=False, max_entries=8)
def cached_airplay_presence(revision: str, days: int = 7) -> dict:
    return airplay_presence_summary(days=days)


@st.cache_resource(show_spinner=False, max_entries=48)
def cached_airplay_presence_at(revision: str, days: int, end_iso: str) -> dict:
    return airplay_presence_summary(days=days, end_date=end_iso)


@st.cache_resource(show_spinner=False, max_entries=128)
def cached_airplay_song_presence(revision: str, song_id: int, days: int = 7) -> dict:
    return airplay_song_presence(int(song_id), days=days)


# EMAUS/GSelector caches. The cheap import revision invalidates them after every
# import/delete, while ordinary Streamlit reruns no longer reopen SQLite and
# decode the same payload_json hundreds/thousands of times.
@st.cache_resource(show_spinner=False, max_entries=16)
def cached_local_dates(revision: str, kind: str) -> list[str]:
    return local_available_dates(kind)


@st.cache_resource(show_spinner=False, max_entries=96)
def cached_local_day_events(revision: str, kind: str, service_date: str) -> list[dict]:
    return local_events_for_day(kind, service_date)


@st.cache_resource(show_spinner=False, max_entries=48)
def cached_local_compare_day(revision: str, service_date: str) -> dict:
    return local_compare_day(service_date, include_hour_details=True)


@st.cache_resource(show_spinner=False, max_entries=48)
def cached_local_song_stats(revision: str, kind: str, start: str, end: str) -> list[dict]:
    return local_song_stats(kind, start, end)


@st.cache_resource(show_spinner=False, max_entries=128)
def cached_local_song_activity(revision: str, song_id: int, start: str = "", end: str = "") -> dict:
    return local_song_activity(int(song_id), start or None, end or None)


@st.cache_resource(show_spinner=False, max_entries=16)
def cached_local_import_history(revision: str) -> list[dict]:
    return local_import_history()


def radio_presence_frame(days: int = 7, air_rev: str = "") -> tuple[pd.DataFrame, dict]:
    snapshot = cached_airplay_presence(air_rev or airplay_revision(), days)
    rows = pd.DataFrame(snapshot.get("rows") or [])
    return rows, snapshot


def with_radio_presence(frame: pd.DataFrame, days: int = 7, air_rev: str = "") -> pd.DataFrame:
    out = frame.copy()
    if out.empty or "song_id" not in out.columns:
        return out
    presence, meta = radio_presence_frame(days, air_rev)
    reporting = int(meta.get("reporting_stations") or 0)
    cols = [
        "song_id", "radio_presence", "radio_reach", "radio_rotation", "stations_count", "spins", "airplay_spins_per_day",
        "airplay_spins_per_station_day", "last_play",
    ]
    if not presence.empty:
        ref = presence[[c for c in cols if c in presence.columns]].drop_duplicates("song_id")
        ref = ref.rename(columns={
            "stations_count": "airplay_stations_count",
            "spins": "airplay_spins_7d",
            "last_play": "airplay_last_play",
        })
        out = out.merge(ref, on="song_id", how="left")
    for col in ["radio_presence", "radio_reach", "radio_rotation", "airplay_spins_per_day", "airplay_spins_per_station_day"]:
        if col not in out.columns:
            out[col] = 0.0 if reporting else float("nan")
        elif reporting:
            out[col] = out[col].fillna(0.0)
    if "airplay_spins_7d" not in out.columns:
        out["airplay_spins_7d"] = 0
    elif reporting:
        out["airplay_spins_7d"] = out["airplay_spins_7d"].fillna(0).astype(int)
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
        ("library", "Baza"),
        ("our_radio", "EMAUS"),
        ("data", "Dane"),
        ("settings", "Ustawienia"),
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

RADIO_STATUS_BOTTOM_UP = ["CF1", "CF2", "R1", "R2", "G1", "G2", "SP1", "SP2", "NB", "F3"]
RADIO_STATUS_TOP_DOWN = list(reversed(RADIO_STATUS_BOTTOM_UP))
BASE_STATUSES = [f"Baza {code}" for code in RADIO_STATUS_TOP_DOWN]
CANDIDATE_STATUSES = [f"{code} Candidate" for code in RADIO_STATUS_TOP_DOWN]

STATUSES = [
    "Nie słuchałem",
    "Poza formatem",
    "Słabe",
    "Watch",
    *CANDIDATE_STATUSES,
    "Baza Hold",
    *BASE_STATUSES,
]

STATUS_ALIASES = {
    "Ignore": "Poza formatem",
    "Candidate": "CF1 Candidate",
    "CF Candidate": "CF1 Candidate",
    "Current": "Baza CF2",
    "Current Familiar": "Baza CF1",
    "Recurrent": "Baza R1",
    "Poza bazą": "Baza Hold",
    "F1 Candidate": "F3 Candidate",
    "Baza F1": "Baza F3",
}

def normalized_status(value: str | None) -> str:
    raw = str(value or "Nie słuchałem")
    return STATUS_ALIASES.get(raw, raw if raw in STATUSES else "Nie słuchałem")


STATUS_FILTER_ALL = "Wszystkie statusy"
STATUS_FILTER_BASE = "Baza — wszystkie"
STATUS_FILTER_CANDIDATE = "Candidate — wszystkie"
DOWNLOAD_FILTER_OPTIONS = ["Any", "Yes", "No"]


def status_filter_options(*, base_only: bool = False) -> list[str]:
    if base_only:
        return ["Baza Hold", *BASE_STATUSES]
    return list(STATUSES)


def render_status_checkbox_filter(host, *, key: str, base_only: bool = False, field_label: str = "Status") -> list[str]:
    """Compact popover containing real checkboxes; no selection means all."""
    if field_label:
        host.markdown(
            f'<div class="rc-control-label">{html.escape(field_label)}</div>',
            unsafe_allow_html=True,
        )
    options = status_filter_options(base_only=base_only)
    group_base_key = f"{key}__group_base"
    group_cand_key = f"{key}__group_candidate"
    selected = [
        status for idx, status in enumerate(options)
        if bool(st.session_state.get(f"{key}__{idx}", False))
    ]
    if not base_only and bool(st.session_state.get(group_base_key, False)):
        selected.extend(["Baza Hold", *BASE_STATUSES])
    if not base_only and bool(st.session_state.get(group_cand_key, False)):
        selected.extend(CANDIDATE_STATUSES)
    selected = list(dict.fromkeys(selected))
    label = "Statusy: wszystkie" if not selected else f"Statusy: {len(selected)}"
    with host.popover(label, use_container_width=True):
        st.caption("Brak zaznaczeń = wszystkie")
        if not base_only:
            g1, g2 = st.columns(2)
            g1.checkbox("Baza — wszystkie", key=group_base_key)
            g2.checkbox("Candidate — wszystkie", key=group_cand_key)
            st.divider()
        cols = st.columns(2)
        for idx, status in enumerate(options):
            cols[idx % 2].checkbox(status, key=f"{key}__{idx}")
    # Re-read after widget creation so the current interaction is reflected now.
    selected = [
        status for idx, status in enumerate(options)
        if bool(st.session_state.get(f"{key}__{idx}", False))
    ]
    if not base_only and bool(st.session_state.get(group_base_key, False)):
        selected.extend(["Baza Hold", *BASE_STATUSES])
    if not base_only and bool(st.session_state.get(group_cand_key, False)):
        selected.extend(CANDIDATE_STATUSES)
    return list(dict.fromkeys(selected))


def apply_status_filter(frame: pd.DataFrame, selected: list[str] | tuple[str, ...] | None) -> pd.DataFrame:
    if frame.empty or "status" not in frame.columns or not selected:
        return frame
    status = frame["status"].fillna("Nie słuchałem").map(normalized_status)
    return frame[status.isin([str(x) for x in selected])].copy()


def apply_download_filter(frame: pd.DataFrame, choice: str) -> pd.DataFrame:
    if frame.empty or "downloaded" not in frame.columns or choice == "Any":
        return frame
    downloaded = frame["downloaded"].fillna(False).astype(bool)
    return frame[downloaded if choice == "Yes" else ~downloaded].copy()


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
    """Overlay live user state without invalidating expensive score caches.

    Use one vectorised join instead of four Python ``.at`` loops.  This matters
    on Dashboard because every filter/search interaction reruns the script.
    """
    out = frame.copy()
    if out.empty:
        return out
    state_cols = ["heard", "status", "downloaded", "note"]
    out = out.drop(columns=[c for c in state_cols if c in out.columns], errors="ignore")
    note_rows = load_notes()
    if note_rows:
        notes_df = pd.DataFrame(note_rows)
        keep = [c for c in ["song_id", *state_cols] if c in notes_df.columns]
        notes_df = notes_df[keep].drop_duplicates("song_id", keep="last")
        notes_df["song_id"] = pd.to_numeric(notes_df["song_id"], errors="coerce")
        notes_df = notes_df[notes_df["song_id"].notna()].copy()
        notes_df["song_id"] = notes_df["song_id"].astype(int)
        out["song_id"] = pd.to_numeric(out["song_id"], errors="raise").astype(int)
        out = out.merge(notes_df, on="song_id", how="left", sort=False)
    if "heard" not in out.columns:
        out["heard"] = False
    else:
        out["heard"] = out["heard"].fillna(False).astype(bool)
    if "downloaded" not in out.columns:
        out["downloaded"] = False
    else:
        out["downloaded"] = out["downloaded"].fillna(False).astype(bool)
    if "status" not in out.columns:
        out["status"] = "Nie słuchałem"
    else:
        out["status"] = out["status"].fillna("Nie słuchałem").map(normalized_status)
    if "note" not in out.columns:
        out["note"] = ""
    else:
        out["note"] = out["note"].fillna("").astype(str)
    return out


def spotify_search_url(artist: str, title: str) -> str:
    query = quote(f"{artist} {title}", safe="")
    return f"https://open.spotify.com/search/{query}"


def olis_awards_url() -> str:
    """Official ZPAV/OLiS searchable Gold/Platinum/Diamond awards database."""
    return "https://www.olis.pl/charts/oficjalna-lista-wyroznien"


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



SPOTIFY_SHARE_FORMATTER = JsCode("""
function(params) {
  return String(params.value || '') ? 'Udostępnij ↗' : '-';
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
  return '#' + Math.round(v) + ' (' + weekLabel + ')';
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

  if (field === 'spotify') {
    const url = String(row.spotify || params.value || '');
    if (!url) return;
    // Never return a DOM node from a streamlit-aggrid renderer: React treats
    // HTMLAnchorElement as an invalid child (React error #31). Handle the
    // navigation from the cell event instead. Modifier/middle clicks always
    // open a new tab and immediately restore focus to RadioCharts so several
    // Spotify results can be queued without leaving the table.
    try {
      const tab = host.open(url, '_blank', 'noopener,noreferrer');
      if (ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.button === 1) {
        try { host.focus(); } catch(e) {}
      }
    } catch(e) {}
    return;
  }

  if (field === 'spotify_copy') {
    const artist = String(row.artist || '');
    const title = String(row.title || '');
    if (!artist && !title) return;

    // Open synchronously so the browser does not block the tab after the
    // asynchronous JSONP lookup. We then redirect it to an exact Songlink page.
    let tab = null;
    try { tab = host.open('about:blank', '_blank'); } catch(e) {}

    const doc = host.document || document;
    const norm = (v) => String(v || '')
      .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
      .toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
    const nt = norm(title), na = norm(artist);
    const cb = '__rcShareCB_' + Date.now() + '_' + Math.floor(Math.random()*1000000);
    const script = doc.createElement('script');
    const cleanup = () => {
      try { delete host[cb]; } catch(e) {}
      try { script.remove(); } catch(e) {}
    };
    const fallback = () => {
      const url = String(row.spotify || '');
      if (tab && url) { try { tab.location.replace(url); } catch(e) {} }
      else if (tab) { try { tab.close(); } catch(e) {} }
    };

    host[cb] = function(payload) {
      try {
        const results = (payload && payload.results ? payload.results : []).filter(x => x && x.trackId);
        let best = null, bestScore = -1;
        for (const r of results) {
          const rt = norm(r.trackName), ra = norm(r.artistName);
          let score = 0;
          if (rt === nt) score += 12;
          if (nt && (rt.includes(nt) || nt.includes(rt))) score += 4;
          const artistTokens = na.split(' ').filter(x => x.length > 2);
          score += artistTokens.filter(t => ra.includes(t)).length * 2;
          if (ra === na) score += 8;
          if (score > bestScore) { best = r; bestScore = score; }
        }
        if (best && best.trackId) {
          const shareUrl = 'https://song.link/i/' + encodeURIComponent(String(best.trackId));
          if (tab) { try { tab.location.replace(shareUrl); } catch(e) {} }
          else { try { host.open(shareUrl, '_blank', 'noopener,noreferrer'); } catch(e) {} }
        } else {
          fallback();
        }
      } finally {
        cleanup();
      }
    };
    script.onerror = function() { fallback(); cleanup(); };
    const term = encodeURIComponent(artist + ' ' + title);
    script.src = 'https://itunes.apple.com/search?term=' + term + '&country=PL&media=music&entity=song&limit=8&callback=' + cb;
    doc.body.appendChild(script);
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

GRID_DOUBLE_CLICK_HANDLER = JsCode("""
function(params) {
  const field = params && params.colDef ? String(params.colDef.field || '') : '';
  if (field !== 'artist' && field !== 'title') return;
  const row = params && params.data ? params.data : {};
  const sid = String(row.song_id || '');
  if (!sid) return;
  const ev = (params && params.event) ? params.event : {};
  const url = window.location.origin + '/?view=song&song=' + encodeURIComponent(sid) + '#rc-song-top';
  if (ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.button === 1) {
    try { window.open(url, '_blank', 'noopener,noreferrer'); } catch(e) {}
    return;
  }
  // Return the requested song id to Streamlit through a hidden data field.
  try { params.node.setDataValue('_open_request', sid); } catch(e) {}
}
""")


GRID_CELL_VALUE_CHANGED_HANDLER = JsCode("""
function(params) {
  try {
    const field = params && params.colDef ? String(params.colDef.field || '') : '';
    if (field !== 'status') return;
    const row = params && params.data ? params.data : {};
    const listened = String(row.status || 'Nie słuchałem') !== 'Nie słuchałem';
    // Update the derived listened indicator immediately in the browser.
    // Streamlit persists it from Status on the rerun; this client-side refresh
    // prevents the checkbox from lagging behind the just-selected status.
    row.heard = listened;
    if (params.api && params.node) {
      params.api.refreshCells({rowNodes: [params.node], columns: ['heard'], force: true});
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


TOP_HSCROLL_INSTALLER = JsCode("""
function(params) {
  // Duplicate AG Grid's horizontal scrollbar directly below the column header.
  // This lives inside the grid iframe, so it works reliably even when Streamlit
  // sandboxes the component and prevents us from attaching UI to window.top.
  try {
    if (window.__rcTopHScrollInstalled) return;
    window.__rcTopHScrollInstalled = true;

    const header = document.querySelector('.ag-header');
    if (!header || !header.parentElement) return;
    const parent = header.parentElement;

    const bar = document.createElement('div');
    bar.className = 'rc-top-hscroll';
    bar.style.cssText = [
      'display:none','flex:0 0 16px','height:16px','min-height:16px','width:100%',
      'box-sizing:border-box','overflow-x:auto','overflow-y:hidden','background:#171c23',
      'border-bottom:1px solid rgba(150,160,175,.34)','z-index:20'
    ].join(';');
    const inner = document.createElement('div');
    inner.style.height = '1px';
    inner.style.minWidth = '1px';
    bar.appendChild(inner);
    parent.insertBefore(bar, header.nextSibling);

    const findViewport = () => document.querySelector('.ag-body-horizontal-scroll-viewport')
      || document.querySelector('.ag-center-cols-viewport');
    const findContent = () => document.querySelector('.ag-body-horizontal-scroll-container')
      || document.querySelector('.ag-center-cols-container');
    let syncing = false;

    const update = () => {
      try {
        const vp = findViewport();
        const content = findContent();
        if (!vp || !content) return;
        const contentWidth = Math.max(content.scrollWidth || 0, content.offsetWidth || 0, vp.scrollWidth || 0);
        const overflow = contentWidth > (vp.clientWidth || 0) + 4;
        bar.style.display = overflow ? 'block' : 'none';
        if (!overflow) return;
        // The proxy spans the whole grid, including pinned identity columns. Add
        // that width difference so both scrollbars have exactly the same range.
        const pinnedDiff = Math.max(0, (bar.clientWidth || 0) - (vp.clientWidth || 0));
        inner.style.width = (contentWidth + pinnedDiff) + 'px';
        if (!syncing && Math.abs(bar.scrollLeft - vp.scrollLeft) > 1) {
          syncing = true;
          bar.scrollLeft = vp.scrollLeft;
          syncing = false;
        }
      } catch(e) {}
    };

    bar.addEventListener('scroll', function() {
      if (syncing) return;
      const vp = findViewport();
      if (!vp) return;
      syncing = true;
      try { vp.scrollLeft = bar.scrollLeft; } catch(e) {}
      syncing = false;
    }, {passive:true});

    const bind = () => {
      const vp = findViewport();
      if (vp && !vp.__rcTopProxyBound) {
        vp.__rcTopProxyBound = true;
        vp.addEventListener('scroll', function() {
          if (syncing) return;
          syncing = true;
          try { bar.scrollLeft = vp.scrollLeft; } catch(e) {}
          syncing = false;
        }, {passive:true});
      }
      update();
    };

    try {
      if (params && params.api) {
        ['columnResized','columnVisible','columnPinned','displayedColumnsChanged','gridSizeChanged'].forEach(function(name) {
          try { params.api.addEventListener(name, update); } catch(e) {}
        });
      }
    } catch(e) {}
    try {
      const ro = new ResizeObserver(update);
      ro.observe(parent);
      const vp = findViewport();
      if (vp) ro.observe(vp);
    } catch(e) {}
    setTimeout(bind, 60);
    setTimeout(bind, 250);
    setTimeout(bind, 800);
  } catch(e) {}
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
              'display:none','position:fixed','left:50%','bottom:75px','transform:translateX(-50%)',
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
                player.querySelector('#__rcPlayerStatus').textContent = '';
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
def render_song_note_editor(
    song_id: int,
    status_value: str,
    downloaded_value: bool,
    note_value: str,
) -> None:
    """Song editor: status/downloaded autosave; the Save button is only for notes."""
    current_status = normalized_status(status_value)
    status_key = f"song_status_{song_id}"
    downloaded_key = f"song_downloaded_{song_id}"
    note_key = f"song_note_{song_id}"
    saved_note_key = f"song_saved_note_{song_id}"

    if status_key not in st.session_state:
        st.session_state[status_key] = current_status
    if downloaded_key not in st.session_state:
        st.session_state[downloaded_key] = bool(downloaded_value)
    if note_key not in st.session_state:
        st.session_state[note_key] = note_value or ""
    if saved_note_key not in st.session_state:
        st.session_state[saved_note_key] = note_value or ""

    real_base = set(BASE_STATUSES)

    def _save_status() -> None:
        status = normalized_status(st.session_state.get(status_key))
        downloaded = bool(st.session_state.get(downloaded_key, False))
        if status in real_base:
            downloaded = True
            st.session_state[downloaded_key] = True
        update_note(
            song_id,
            status != "Nie słuchałem",
            status,
            str(st.session_state.get(saved_note_key, note_value or "")),
            downloaded=downloaded,
        )
        st.toast("Status zapisany")

    def _save_downloaded() -> None:
        status = normalized_status(st.session_state.get(status_key))
        downloaded = bool(st.session_state.get(downloaded_key, False))
        if status in real_base:
            # Real Baza statuses always imply a local download. Keep the UI in
            # sync with the invariant enforced by update_note().
            downloaded = True
            st.session_state[downloaded_key] = True
        update_note(
            song_id,
            status != "Nie słuchałem",
            status,
            str(st.session_state.get(saved_note_key, note_value or "")),
            downloaded=downloaded,
        )
        st.toast("Downloaded zapisany")

    with st.container(border=True):
        n1, n2 = st.columns([1.65, 1.15])
        n1.selectbox(
            "Status",
            STATUSES,
            key=status_key,
            on_change=_save_status,
            help="Zmiana statusu zapisuje się automatycznie. Każdy status poza „Nie słuchałem” oznacza, że utwór został przesłuchany.",
        )
        n2.checkbox(
            "Downloaded",
            key=downloaded_key,
            on_change=_save_downloaded,
            help="Utwór pobrany / dodany do lokalnej biblioteki.",
        )
        with st.form(f"note_form_{song_id}"):
            note = st.text_input("Notatka", key=note_key)
            save_note = st.form_submit_button("Zapisz", use_container_width=True)
            if save_note:
                status = normalized_status(st.session_state.get(status_key))
                update_note(
                    song_id,
                    status != "Nie słuchałem",
                    status,
                    note,
                    downloaded=bool(st.session_state.get(downloaded_key, False)),
                )
                st.session_state[saved_note_key] = note
                st.toast("Notatka zapisana")


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


@st.dialog("Scal utwory")
def confirm_song_merge_dialog(song_ids: tuple[int, ...], state_key: str) -> None:
    """Confirmation for the Emisje-table duplicate merge workflow."""
    ids = tuple(dict.fromkeys(int(x) for x in song_ids if int(x) > 0))
    rows = []
    for sid in ids:
        row = get_song(sid)
        if row:
            rows.append({
                "ID": int(row.get("song_id") or sid),
                "Wykonawca": str(row.get("artist") or ""),
                "Tytuł": str(row.get("title") or ""),
            })
    st.warning(
        "Scalanie jest trwałe. Emisje, notowania, status, Downloaded i notatki zostaną połączone. "
        "Dawne nazwy i ID pozostaną aliasami, więc nowe dane z tym samym starym opisem trafią już do rekordu głównego."
    )
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True, height=min(280, 42 + 35 * len(rows)))
    st.caption(
        "RadioCharts automatycznie zachowa jako rekord główny najlepiej udokumentowaną wersję "
        "(najpierw historia toplist, potem liczba emisji)."
    )
    left, right = st.columns(2)
    if left.button("Anuluj", use_container_width=True):
        st.rerun()
    if right.button("Scal utwory", type="primary", use_container_width=True, disabled=len(ids) < 2):
        result = merge_song_group(ids)
        st.session_state[state_key] = []
        st.session_state["song_merge_notice"] = (
            f"Scalono {int(result.get('merged') or 0)} rekordów → "
            f"{result.get('artist','')} — {result.get('title','')}."
        )
        st.cache_data.clear()
        st.rerun()


@st.fragment
def render_song_grid(
    frame: pd.DataFrame,
    *,
    key: str,
    height: int = 640,
    editable_state: bool = True,
    source_layout: str = "full",
    station_total: int | None = None,
    floating_hscroll: bool = False,
    row_numbers: bool = False,
    merge_select_mode: bool = False,
) -> pd.DataFrame:
    """AG Grid table: row highlight, editing, responsive source columns and preview player."""
    show = frame.copy()
    if row_numbers and "_row_number" not in show.columns:
        # Display-only row header. valueGetter uses the current visual rowIndex,
        # so after any AG Grid sort the column still reads 1,2,3... top-to-bottom.
        show.insert(0, "_row_number", 0)
    if show.empty:
        st.info("Brak utworów do pokazania.")
        return show
    if "preview" not in show.columns:
        show["preview"] = "▶"
    if "song_id" in show.columns:
        show["_open_request"] = ""
    # Przesłuchany is a visual state derived from Status. Keep the legacy DB
    # column, but never allow the checkbox to diverge from the status shown in
    # the same row.
    if "status" in show.columns and "heard" in show.columns:
        show["heard"] = show["status"].fillna("Nie słuchałem").astype(str).ne("Nie słuchałem")

    merge_state_key = f"{key}__merge_selected"
    if merge_select_mode and "song_id" in show.columns:
        visible_ids = {int(x) for x in show["song_id"].dropna().tolist()}
        remembered = {int(x) for x in st.session_state.get(merge_state_key, []) if int(x) in visible_ids}
        # Appending here deliberately puts the checkbox at the far right, after
        # Notatka in the Emisje layout, so accidental clicks are unlikely.
        show["_merge_select"] = [int(sid) in remembered for sid in show["song_id"]]

    gb = GridOptionsBuilder.from_dataframe(show)
    gb.configure_default_column(resizable=True, sortable=True, filter=True, editable=False)
    if "_row_number" in show.columns:
        gb.configure_column(
            "_row_number", "L.p.", pinned="left", width=58, minWidth=52, maxWidth=62,
            sortable=False, filter=False, editable=False, suppressMenu=True,
            # Cell renderer reads the node's *displayed* rowIndex. The explicit
            # refresh hooks below force this column to redraw after sorting or
            # filtering, so L.p. always stays 1,2,3... from top to bottom.
            cellRenderer=JsCode("function(params){ return (params.node && params.node.rowIndex != null) ? String(params.node.rowIndex + 1) : ''; }")
        )
    gb.configure_selection(selection_mode="single", use_checkbox=False, suppressRowClickSelection=False)
    gb.configure_grid_options(
        rowHeight=36, animateRows=False,
        onCellClicked=GRID_CLICK_HANDLER,
        onCellDoubleClicked=GRID_DOUBLE_CLICK_HANDLER,
        onCellValueChanged=GRID_CELL_VALUE_CHANGED_HANDLER,
    )
    if "_row_number" in show.columns:
        row_number_refresh = JsCode("""
        function(params) {
          try {
            params.api.refreshCells({columns: ['_row_number'], force: true});
          } catch (e) {}
        }
        """)
        gb.configure_grid_options(
            onSortChanged=row_number_refresh,
            onFilterChanged=row_number_refresh,
        )
    if floating_hscroll:
        gb.configure_grid_options(onGridReady=TOP_HSCROLL_INSTALLER)

    if "song_id" in show.columns:
        gb.configure_column("song_id", hide=True)
    if "_open_request" in show.columns:
        gb.configure_column("_open_request", hide=True, editable=False)
    pin_identity = source_layout in {"auto", "compact", "airplay"}
    if "artist" in show.columns:
        gb.configure_column(
            "artist", "Wykonawca", minWidth=170 if pin_identity else 190, width=205 if pin_identity else 220,
            pinned="left" if pin_identity else None,
            headerTooltip="Dwuklik na wykonawcy otwiera kartę utworu.",
            cellStyle={"cursor": "default"},
        )
    if "title" in show.columns:
        gb.configure_column(
            "title", "Tytuł", minWidth=185 if pin_identity else 210, width=235 if pin_identity else 260,
            pinned="left" if pin_identity else None,
            headerTooltip="Dwuklik na tytule otwiera kartę utworu.",
            cellStyle={"cursor": "default"},
        )
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
    if "spotify" in show.columns:
        gb.configure_column(
            "spotify", "Spotify", minWidth=90, width=95, sortable=False, filter=False,
            valueFormatter=SPOTIFY_LABEL_FORMATTER,
            cellStyle={"cursor": "pointer", "color": "#d7f9df", "fontWeight": "650"},
            headerTooltip="Klik otwiera Spotify w nowej karcie. Ctrl/Cmd+klik lub środkowy przycisk pozwala otwierać kolejne wyniki bez opuszczania tabeli.",
        )
    if "spotify_copy" in show.columns:
        gb.configure_column(
            "spotify_copy", "Udostępnij", minWidth=92, width=102, sortable=False, filter=False,
            valueFormatter=SPOTIFY_SHARE_FORMATTER,
            headerTooltip="Otwórz bezpośredni smart-link Songlink/Odesli do konkretnego utworu (Spotify, Apple Music i inne serwisy).",
            cellStyle={"cursor": "pointer", "textAlign": "center", "fontWeight": "700"},
        )
    if "preview" in show.columns:
        gb.configure_column("preview", "Odsłuch", minWidth=90, width=98, sortable=False, filter=False, valueFormatter=PREVIEW_LABEL_FORMATTER, cellStyle={"cursor": "pointer"})
    if "heard" in show.columns:
        gb.configure_column(
            "heard", "✓", width=62, minWidth=58, maxWidth=68,
            editable=False, sortable=True, filter=False, cellDataType="boolean",
            cellRenderer="agCheckboxCellRenderer",
            # Keep the native renderer visually active, but block pointer events
            # below so this derived checkbox remains read-only.
            cellRendererParams={"disabled": False},
            cellClass="rc-listened-checkbox",
            headerTooltip="Przesłuchany — zaznacza się automatycznie, gdy Status jest inny niż „Nie słuchałem”.",
            cellStyle={
                "textAlign": "center",
                "--ag-checkbox-checked-color": "#ff2d2d",
                "--ag-checkbox-unchecked-color": "#6b7280",
                "--ag-checkbox-background-color": "#15191f",
            },
        )
    if "status" in show.columns:
        gb.configure_column(
            "status", "Status", minWidth=150, width=165,
            editable=bool(editable_state),
            cellEditor="agSelectCellEditor",
            cellEditorParams={"values": STATUSES, "valueListMaxHeight": 310, "valueListMaxWidth": 220},
        )
    if "downloaded" in show.columns:
        gb.configure_column(
            "downloaded", "Downloaded", width=108, minWidth=98,
            editable=bool(editable_state), cellDataType="boolean",
            cellRenderer="agCheckboxCellRenderer", cellEditor="agCheckboxCellEditor",
            cellRendererParams={"disabled": not bool(editable_state)},
            cellClass="rc-downloaded-checkbox",
            cellStyle={
                "--ag-checkbox-checked-color": "#22c55e",
                "--ag-checkbox-unchecked-color": "#6b7280",
                "--ag-checkbox-background-color": "#15191f",
            },
            headerTooltip="Utwór pobrany / dodany do lokalnej biblioteki po odsłuchu.",
        )
    if "note" in show.columns:
        gb.configure_column("note", "Notatka", minWidth=220, width=300, editable=bool(editable_state))
    if "_merge_select" in show.columns:
        gb.configure_column(
            "_merge_select", "Scal", width=72, minWidth=68, maxWidth=78,
            editable=True, sortable=False, filter=False, suppressMenu=True,
            cellDataType="boolean", cellRenderer="agCheckboxCellRenderer", cellEditor="agCheckboxCellEditor",
            headerTooltip="Zaznacz co najmniej dwa rekordy tego samego nagrania, a potem użyj przycisku Scal zaznaczone pod tabelą.",
        )
    for col, label, tooltip in [
        ("popularity", "Popularity", "80% względna liczba emisji z ostatnich 28 dni + 20% bonus z bieżących pozycji; OLiA/OLiS mają największą wagę bonusu."),
        ("familiarity", "Chart Score", "Historyczna siła utworu w obserwowanych notowaniach: peak, długość obecności i Top 10."),
        ("momentum", "Momentum", "Bieżący kierunek zmian na listach; szybko wygasa po zejściu z list."),
    ]:
        if col in show.columns:
            gb.configure_column(col, label, width=115, minWidth=105, valueFormatter=PERCENT_FORMATTER, headerTooltip=tooltip)
    if "radio_presence" in show.columns:
        gb.configure_column(
            "radio_presence", "Radio Presence 7d", width=145, minWidth=132,
            valueFormatter=PERCENT_FORMATTER,
        )
    if "radio_reach" in show.columns:
        gb.configure_column("radio_reach", "Zasięg 7d", width=108, minWidth=98, valueFormatter=PERCENT_FORMATTER)
    if "airplay_spins_7d" in show.columns:
        gb.configure_column("airplay_spins_7d", "Emisje 7d", width=102, minWidth=92)
    if "airplay_spins_period" in show.columns:
        gb.configure_column(
            "airplay_spins_period", "Emisje okres", width=112, minWidth=102,
            headerTooltip="Liczba emisji ze wszystkich aktywnych stacji w okresie odpowiadającym wybranemu Okresowi wskaźników; dla Całości = cała dostępna historia Emisji.",
        )
    if "radio_rotation" in show.columns:
        gb.configure_column("radio_rotation", "Rotacja", width=100, minWidth=92, valueFormatter=PERCENT_FORMATTER)
    if "radio_presence_period" in show.columns:
        gb.configure_column("radio_presence_period", "Radio Presence", width=132, minWidth=120, valueFormatter=PERCENT_FORMATTER)

    source_names = [c for c in ["RMF", "ZET", "OLIA", "OLIS", "ESKA", "UK", "BILLBOARD"] if c in show.columns]
    week_names = [f"{c}_weeks" for c in source_names if f"{c}_weeks" in show.columns]
    compact_initial = source_layout in {"compact", "airplay"}
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
        if station_total is not None and int(station_total) > 0:
            denominator = int(station_total)
            station_formatter = JsCode(f"""
            function(params) {{
              const v = Number(params.value);
              if (!isFinite(v)) return '-';
              const pct = Math.min(100, Math.max(0, 100 * v / {denominator}));
              return Math.round(pct) + '% (' + Math.round(v) + ')';
            }}
            """)
            gb.configure_column(
                "stations_count", "Zasięg", width=108, minWidth=100,
                valueFormatter=station_formatter,
                headerTooltip="Zasięg w wybranym okresie; procent z raportujących stacji, w nawiasie liczba stacji, które zagrały utwór.",
            )
        else:
            gb.configure_column("stations_count", "Zasięg", width=92, minWidth=84)
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
    original = show[[c for c in ["song_id", "status", "downloaded", "note"] if c in show.columns]].copy()

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
            # Use AG Grid's documented checkbox CSS variables.  Setting them
            # on the cell scopes each colour to one column and avoids the
            # Streamlit theme's default red accent leaking into Downloaded.
            ".rc-listened-checkbox": {
                "--ag-checkbox-checked-color": "#ff2d2d !important",
                "--ag-checkbox-unchecked-color": "#6b7280 !important",
                "--ag-checkbox-background-color": "#15191f !important",
            },
            ".rc-listened-checkbox .ag-checkbox-input-wrapper": {
                "opacity": "1 !important",
                "pointer-events": "none !important",
            },
            ".rc-downloaded-checkbox": {
                "--ag-checkbox-checked-color": "#22c55e !important",
                "--ag-checkbox-unchecked-color": "#6b7280 !important",
                "--ag-checkbox-background-color": "#15191f !important",
            },
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

    if merge_select_mode and {"song_id", "_merge_select"}.issubset(edited.columns):
        selected_ids: list[int] = []
        for sid, selected in edited[["song_id", "_merge_select"]].itertuples(index=False, name=None):
            try:
                if bool(selected):
                    selected_ids.append(int(sid))
            except Exception:
                continue
        selected_ids = list(dict.fromkeys(selected_ids))
        st.session_state[merge_state_key] = selected_ids
        controls_left, controls_right = st.columns([1, 4], vertical_alignment="center")
        if controls_left.button(
            f"Scal zaznaczone ({len(selected_ids)})",
            disabled=len(selected_ids) < 2,
            key=f"{key}__merge_button",
            type="primary",
            use_container_width=True,
        ):
            confirm_song_merge_dialog(tuple(selected_ids), merge_state_key)
        controls_right.caption(
            "Zaznacz 2+ warianty tego samego utworu w ostatniej kolumnie. "
            "Scalanie zapamiętuje stare nazwy jako aliasy dla przyszłych importów."
        )
        notice = st.session_state.pop("song_merge_notice", None)
        if notice:
            st.toast(str(notice))

    if editable_state and {"song_id", "status"}.issubset(edited.columns) and not original.empty:
        before = original.set_index("song_id")
        changed = 0
        cols_for_edit = [c for c in ["song_id", "status", "downloaded", "note"] if c in edited.columns]
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
            old_downloaded = bool(prev["downloaded"]) if "downloaded" in before.columns else False
            new_downloaded = bool(getattr(r, "downloaded", old_downloaded))
            if (
                str(r.status) != str(prev.status)
                or new_downloaded != old_downloaded
                or new_note != old_note
            ):
                new_status = normalized_status(str(r.status))
                update_note(sid, new_status != "Nie słuchałem", new_status, new_note, downloaded=new_downloaded)
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

    stations = cached_airplay_stations(AIR_REV, True)
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
    can_backfill = bool(selected_ids) and estimated_windows <= AIRPLAY_BACKFILL_MAX_WINDOWS and not running
    if estimated_windows > AIRPLAY_BACKFILL_MAX_WINDOWS:
        st.warning(f"Zakres przekracza limit {AIRPLAY_BACKFILL_MAX_WINDOWS:,} okien. Zmniejsz zakres lub liczbę stacji.".replace(",", " "))
    run_col, _ = st.columns([1.8, 4.2])
    if run_col.button("Backfill emisji", disabled=not can_backfill, type="primary", use_container_width=True, key="data_airplay_bf_run"):
        start_job("airplay-backfill", params={
            "station_ids": selected_ids,
            "start_date": bf_start.isoformat(),
            "end_date": bf_end.isoformat(),
        })
        st.rerun()
    st.caption(f"Pełna zakończona doba jednej stacji = 12 bloków po 2h. Limit jednego procesu: {AIRPLAY_BACKFILL_MAX_WINDOWS:,} okien. Backfill najpierw wczytuje zapisane bloki, pomija już kompletne okna i pobiera tylko brakujące lub wymagające ponowienia — możesz więc bezpiecznie wskazać także długi zakres, np. rok lub więcej.".replace(",", " "))
    render_job_status_fragment("airplay", "data_airplay")

    with st.expander("🔎 Co dokładnie zostało pobrane — pokrycie per stacja", expanded=False):
        first_date_raw = cov.get("first_date")
        try:
            coverage_earliest = date.fromisoformat(str(first_date_raw)) if first_date_raw else last_date
        except Exception:
            coverage_earliest = last_date
        cov_start, cov_end = render_airplay_range_picker(
            key_prefix="data_airplay_coverage_range",
            default_end=last_date,
            earliest=coverage_earliest,
            default_preset="Ostatni tydzień",
        )
        cov_expected = len(completed_windows_in_range(cov_start, cov_end))
        cov_rows = airplay_station_coverage(active_ids, cov_start, cov_end)
        cov_df = pd.DataFrame(cov_rows)
        if cov_df.empty:
            st.caption("Brak danych pokrycia w wybranym zakresie.")
        else:
            cov_df["expected"] = cov_expected
            cov_df["missing"] = (cov_df["expected"] - cov_df["ok_windows"].fillna(0).astype(int)).clip(lower=0)
            cov_df["coverage_pct"] = [
                round(100.0 * int(ok or 0) / cov_expected, 1) if cov_expected else 0.0
                for ok in cov_df["ok_windows"]
            ]
            cov_df["status"] = [
                ("✅ komplet" if int(ok or 0) >= cov_expected and int(plays or 0) > 0
                 else "⚪ komplet, 0 emisji" if int(ok or 0) >= cov_expected and cov_expected > 0
                 else "⚠️ braki")
                for ok, plays in zip(cov_df["ok_windows"], cov_df["plays"])
            ]
            shown_cov = cov_df[["name", "status", "coverage_pct", "ok_windows", "expected", "missing", "zero_windows", "plays"]].rename(columns={
                "name": "Stacja", "status": "Stan", "coverage_pct": "Pokrycie %",
                "ok_windows": "Bloki OK", "expected": "Oczekiwane", "missing": "Brakuje",
                "zero_windows": "Puste bloki", "plays": "Emisje",
            })
            st.dataframe(shown_cov, hide_index=True, use_container_width=True, height=min(610, 44 + 35 * len(shown_cov)))
            st.caption(
                f"{cov_start} → {cov_end}. Pusty blok = odSluchane odpowiedziało poprawnie, ale parser znalazł 0 emisji. "
                "To jest diagnostyka pobierania, dlatego mieszka w Danych, nie w Emisjach."
            )

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



LOCAL_EVENT_LABELS = {
    "song": "Song",
    "jingle": "Jingle",
    "show": "Audycja",
    "bed": "Podkład",
    "info": "Informacje",
    "etm": "ETM",
    "traffic": "Reklama",
    "command": "Komenda Zetta",
    "other": "Inne",
}

LOCAL_ELEMENT_FILTER_PRESETS = {
    "Wszystkie": list(LOCAL_EVENT_LABELS),
    "Song": ["song"],
    "Song + Jingle": ["song", "jingle"],
    "Programowe (bez ETM/komend)": ["song", "jingle", "show", "bed", "info", "traffic", "other"],
    "Tylko ETM": ["etm"],
}
LOCAL_ETM_KINDS = ["Hard", "Soft", "Reset", "Hit", "Inne"]
LOCAL_ETM_PRESETS = {
    "Wszystkie": set(LOCAL_ETM_KINDS),
    "Hard": {"Hard"},
    "Soft": {"Soft"},
    "Reset": {"Reset"},
    "Hit": {"Hit"},
    "Hard + Soft": {"Hard", "Soft"},
    "Reset + Hit": {"Reset", "Hit"},
}


def _local_etm_kind(row: dict) -> str:
    if str(row.get("event_type") or "") != "etm":
        return ""
    value = str(row.get("title") or row.get("category") or "").upper()
    for label in ("HARD", "SOFT", "RESET", "HIT"):
        if f"_{label}" in value or label in value:
            return label.title()
    return "Inne"


def _local_normalize_gap(raw: str) -> str:
    value = str(raw or "").strip()
    if not value:
        return ""
    # GSelector usually writes +00:54.0. Keep tenths only when meaningful.
    if re.fullmatch(r"[+-]\d{2,}:\d{2}\.0", value):
        return value[:-2]
    return value


def _local_gap_ms_to_raw(value: object) -> str:
    try:
        gap_seconds = float(value) / 1000.0
    except (TypeError, ValueError):
        return ""
    sign = "+" if gap_seconds >= 0 else "-"
    value_abs = abs(gap_seconds)
    minutes = int(value_abs // 60)
    seconds = value_abs - minutes * 60
    return f"{sign}{minutes:02d}:{seconds:04.1f}".rstrip("0").rstrip(".")


def _local_row_clock_seconds(row: dict) -> float | None:
    raw = str(row.get("air_time_raw") or "").strip()
    m = re.fullmatch(r"(\d{1,2}):(\d+):(\d{1,2}(?:\.\d+)?)", raw)
    if not m:
        return None
    hour = int(m.group(1))
    minute = int(m.group(2))
    second = float(m.group(3))
    if second >= 60 or minute >= 180:
        return None
    return hour * 3600.0 + minute * 60.0 + second



def _local_apply_hour_boundary_gaps(rows: list[dict]) -> list[dict]:
    """Rebuild full-hour Hard/Soft gap without counting queued 60+ rows.

    Zetta2GO loads one log hour at a time and commonly reports 00:00/HH:00 ETMs
    as zero.  For the UI we restore the carry from the previous scheduling hour.

    Crucially, only an element that *started before* the boundary may define the
    tail crossing that boundary. Rows whose start is already 60+ minutes are
    queued overrun rows; counting them is what produced false +17/+30/+50 min
    values in 1.2.12-1.2.15.
    """
    out = [dict(row) for row in rows]
    by_hour: dict[int, list[dict]] = {}
    for row in out:
        try:
            hour = int(row.get("schedule_hour"))
        except (TypeError, ValueError):
            continue
        by_hour.setdefault(hour, []).append(row)

    def offset_in_hour(row: dict, hour: int) -> float | None:
        clock = _local_row_clock_seconds(row)
        if clock is None:
            return None
        return clock - hour * 3600.0

    def first_playable_after(group: list[dict], index: int, reset_clock: float) -> float | None:
        for candidate in group[index + 1:]:
            if str(candidate.get("event_type") or "") == "etm":
                kind = _local_etm_kind(candidate)
                if kind in {"Hard", "Soft", "Reset"}:
                    return None
                continue
            if bool(candidate.get("zetta_skip")):
                continue
            clock = _local_row_clock_seconds(candidate)
            if clock is None:
                continue
            return (clock - reset_clock) * 1000.0
        return None

    for hour in range(1, 24):
        current = by_hour.get(hour, [])
        marker = next(
            (
                row for row in current
                if str(row.get("source_system") or "") == "zetta2go"
                and str(row.get("event_type") or "") == "etm"
                and _local_etm_kind(row) in {"Hard", "Soft"}
                and (lambda off: off is not None and abs(off) <= 0.05)(offset_in_hour(row, hour))
            ),
            None,
        )
        if marker is None:
            continue

        prev_hour = hour - 1
        previous = by_hour.get(prev_hour, [])
        if not previous:
            continue

        last_control = 0.0
        boundary_reset: tuple[int, dict, float] | None = None
        for idx, row in enumerate(previous):
            if str(row.get("event_type") or "") != "etm":
                continue
            kind = _local_etm_kind(row)
            off = offset_in_hour(row, prev_hour)
            if off is None:
                continue
            if kind in {"Hard", "Soft"} and 0 <= off < 3600.0:
                last_control = max(last_control, off)
            if kind == "Reset" and 3590.0 <= off <= 3600.0:
                boundary_reset = (idx, row, off)

        derived_ms: float | None = None
        source = ""
        if boundary_reset is not None:
            idx, reset_row, reset_off = boundary_reset
            reset_clock = _local_row_clock_seconds(reset_row)
            local_ms = first_playable_after(previous, idx, reset_clock) if reset_clock is not None else None
            if local_ms is None:
                value = reset_row.get("zetta_reset_local_gap_ms")
                if value is None:
                    value = reset_row.get("zetta_gap_native_ms")
                if value is None:
                    value = reset_row.get("zetta_gap_ms")
                try:
                    local_ms = float(value) if value is not None else None
                except (TypeError, ValueError):
                    local_ms = None
            if local_ms is not None:
                derived_ms = local_ms - (3600.0 - reset_off) * 1000.0
                source = "previous_hour_reset"
        else:
            ends: list[float] = []
            for candidate in previous:
                if str(candidate.get("event_type") or "") == "etm" or bool(candidate.get("zetta_skip")):
                    continue
                off = offset_in_hour(candidate, prev_hour)
                if off is None or not (last_control <= off < 3600.0):
                    continue
                try:
                    runtime = float(candidate.get("runtime_seconds") or 0.0)
                except (TypeError, ValueError):
                    runtime = 0.0
                if runtime > 0:
                    ends.append(off + runtime)
            if ends:
                derived_ms = (max(ends) - 3600.0) * 1000.0
                source = "previous_hour_tail"

        if derived_ms is None:
            continue
        marker["zetta_gap_ms"] = derived_ms
        marker["zetta_gap_source"] = source
        marker["etm_delta_raw"] = _local_gap_ms_to_raw(derived_ms)

    return out



def _local_apply_ignore_reset_gaps(rows: list[dict]) -> list[dict]:
    """Return a display copy where RESET does not zero the ETM gap.

    Zetta's own RESET gap is the authoritative delta.  RESET changes the gap
    calculation baseline but does not force playout to the marker clock, so the
    deltas are accumulated until the next Hard/Soft anchor.  If a RESET has no
    gap in GetLog, it is ignored rather than reconstructed from row airtimes;
    that fallback could produce false +30/+50 minute values on backtimed logs.
    """
    out: list[dict] = []
    carry_ms = 0.0
    last_reset_ms: float | None = None
    reset_count = 0
    missing_reset_count = 0

    for original in rows:
        row = dict(original)
        out.append(row)
        if str(row.get("source_system") or "") != "zetta2go":
            continue
        if str(row.get("event_type") or "") != "etm":
            continue

        kind = _local_etm_kind(row)
        if kind == "Reset":
            try:
                gap_ms = float(row.get("zetta_gap_ms")) if row.get("zetta_gap_ms") is not None else None
            except (TypeError, ValueError):
                gap_ms = None
            if gap_ms is None:
                missing_reset_count += 1
            else:
                carry_ms += gap_ms
                last_reset_ms = gap_ms
                reset_count += 1
            continue

        if kind not in {"Hard", "Soft"}:
            # HIT remains informational and does not reset the alternative view.
            continue

        try:
            base_ms = float(row.get("zetta_gap_ms")) if row.get("zetta_gap_ms") is not None else None
        except (TypeError, ValueError):
            base_ms = None

        if base_ms is not None:
            correction = carry_ms
            if str(row.get("zetta_gap_source") or "") == "previous_hour_reset" and last_reset_ms is not None:
                correction -= last_reset_ms
            effective_ms = base_ms + correction
            row["zetta_gap_ignore_resets_ms"] = effective_ms
            row["zetta_gap_ignore_resets_carry_ms"] = correction
            row["zetta_gap_ignore_resets_reset_count"] = reset_count
            row["zetta_gap_ignore_resets_missing_reset_count"] = missing_reset_count
            row["etm_delta_raw"] = _local_gap_ms_to_raw(effective_ms)
            row["zetta_gap_display_mode"] = "ignore_resets"

        carry_ms = 0.0
        last_reset_ms = None
        reset_count = 0
        missing_reset_count = 0

    return out

def _local_filter_etm_rows(rows: list[dict], kinds: set[str]) -> list[dict]:
    if not kinds:
        return [r for r in rows if str(r.get("event_type") or "") != "etm"]
    return [
        r for r in rows
        if str(r.get("event_type") or "") != "etm" or _local_etm_kind(r) in kinds
    ]


def _render_local_etm_gap_summary(rows: list[dict], *, ignore_resets: bool = False) -> None:
    markers = [
        row for row in rows
        if str(row.get("event_type") or "") == "etm" and _local_etm_kind(row) in {"Hard", "Soft"}
    ]
    if not markers:
        return

    def gap_seconds(raw: str) -> float | None:
        m = re.fullmatch(r"([+-])(\d+):(\d{2}(?:\.\d+)?)", str(raw or "").strip())
        if not m:
            return None
        value = int(m.group(2)) * 60.0 + float(m.group(3))
        return value if m.group(1) == "+" else -value

    parsed = [(row, gap_seconds(str(row.get("etm_delta_raw") or ""))) for row in markers]
    direct_zetta = all(str(row.get("source_system") or "") == "zetta2go" for row in markers)
    nonzero = sum(1 for _row, value in parsed if value is not None and abs(value) >= .05)
    positives = [value for _row, value in parsed if value is not None and value > 0]
    negatives = [value for _row, value in parsed if value is not None and value < 0]

    # The GSelector export does not contain the runtime of traffic/spot blocks
    # loaded later by Zetta. It can therefore never reproduce Zetta's ETM Gap
    # exactly. Mark Hard/Soft segments where this is especially relevant instead
    # of silently presenting the GSelector number as a Zetta-equivalent value.
    diagnostic_by_id: dict[int, tuple[int, int]] = {}
    previous_control_index = 0
    for idx, row in enumerate(rows):
        if str(row.get("event_type") or "") != "etm" or _local_etm_kind(row) not in {"Hard", "Soft"}:
            continue
        segment = rows[previous_control_index:idx]
        reset_count = sum(
            1 for item in segment
            if str(item.get("event_type") or "") == "etm" and _local_etm_kind(item) == "Reset"
        )
        unknown_traffic = sum(
            1 for item in segment
            if str(item.get("event_type") or "") == "traffic" and item.get("runtime_seconds") is None
        )
        diagnostic_by_id[int(row.get("id") or id(row))] = (reset_count, unknown_traffic)
        previous_control_index = idx + 1

    def fmt_seconds(value: float | None) -> str:
        if value is None:
            return "—"
        sign = "+" if value >= 0 else "-"
        value = abs(value)
        minutes = int(value // 60)
        seconds = value - minutes * 60
        if abs(seconds - round(seconds)) < .05:
            return f"{sign}{minutes:02d}:{int(round(seconds)):02d}"
        return f"{sign}{minutes:02d}:{seconds:04.1f}"

    max_late = fmt_seconds(max(positives)) if positives else "—"
    max_early = fmt_seconds(min(negatives)) if negatives else "—"
    if direct_zetta:
        st.markdown("#### ETM Hard / Soft — gapy Zetta")
        if ignore_resets:
            reset_markers = sum(int(row.get("zetta_gap_ignore_resets_reset_count") or 0) for row, _value in parsed)
            missing_resets = sum(int(row.get("zetta_gap_ignore_resets_missing_reset_count") or 0) for row, _value in parsed)
            missing_note = f" · bez gapu w GetLog: {missing_resets}" if missing_resets else ""
            st.caption(
                f"{len(markers)} markerów · ≠ 0: {nonzero} · max +: {max_late} · max −: {max_early}. "
                f"Ignoruj resety: ON · doliczono {reset_markers} RESET-ów{missing_note}. Carry bierze bezpośrednio "
                "gap RESET zwrócony przez Zetta2GO; RESET bez gapu nie jest zgadywany z AirTime/runtime. HARD i SOFT "
                "są traktowane jako dokładne kotwice czasu."
            )
        else:
            carried_reset = sum(1 for row, _value in parsed if str(row.get("zetta_gap_source") or "") == "previous_hour_reset")
            carried_tail = sum(1 for row, _value in parsed if str(row.get("zetta_gap_source") or "") == "previous_hour_tail")
            st.caption(
                f"{len(markers)} markerów · ≠ 0: {nonzero} · max +: {max_late} · max −: {max_early}. "
                "Gapy śródgodzinne pochodzą bezpośrednio z Zetta2GO/GetLog. Przy pełnej godzinie Zetta2GO zeruje TOH, "
                f"więc RadioCharts przenosi końcowy RESET poprzedniej godziny ({carried_reset}) albo, gdy go nie ma, "
                f"liczy tylko element rozpoczęty przed 60:00 po ostatnim Hard/Soft ({carried_tail}); pozycje startujące "
                "już jako 60+ nie zawyżają gapu."
            )
    else:
        st.markdown("#### ETM Hard / Soft — gapy planu GSelector")
        st.caption(
            f"{len(markers)} markerów · ≠ 0: {nonzero} · max +: {max_late} · max −: {max_early}. "
            "To są wartości +/- zapisane w eksporcie GSelectora, nie gap Zetty. Zetta może mieć inny wynik po załadowaniu "
            "realnych bloków reklamowych; ⚠ oznacza segment z RESET-em lub blokiem traffic bez runtime."
        )

    cards = []
    for row, value in parsed:
        raw_time = str(row.get("air_time_raw") or "")
        hhmm = raw_time[:5] if len(raw_time) >= 5 else raw_time
        kind = _local_etm_kind(row).upper()
        gap = _local_normalize_gap(str(row.get("etm_delta_raw") or "")) or "—"
        muted = value is not None and abs(value) < .05
        css = "rc-etm-chip rc-etm-zero" if muted else "rc-etm-chip"
        resets, traffic = diagnostic_by_id.get(int(row.get("id") or id(row)), (0, 0))
        warnings = []
        if not direct_zetta:
            if resets:
                warnings.append(f"RESET: {resets}")
            if traffic:
                warnings.append(f"traffic bez runtime: {traffic}")
        warning = ""
        if warnings:
            warning = (
                f'<span class="rc-etm-risk" title="{html.escape("; ".join(warnings))}">⚠</span>'
            )
        cards.append(
            f'<div class="{css}"><span class="rc-etm-time">{html.escape(hhmm)}</span>'
            f'<span class="rc-etm-kind">{html.escape(kind)}</span>'
            f'<span class="rc-etm-gap">{html.escape(gap)}</span>{warning}</div>'
        )
    st.markdown(
        '<div class="rc-etm-grid">' + "".join(cards) + "</div>",
        unsafe_allow_html=True,
    )


def _local_default_date(values: list[str], kind: str) -> date | None:
    if not values:
        return None
    parsed = [date.fromisoformat(v) for v in values]
    if kind == "schedule":
        today = date.today()
        future = [d for d in parsed if d >= today]
        return min(future) if future else max(parsed)
    return max(parsed)


def _local_timeline_frame(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    frame["_event_type"] = frame["event_type"].fillna("other")
    frame["Typ"] = frame["event_type"].map(LOCAL_EVENT_LABELS).fillna(frame["event_type"])
    frame["Czas"] = frame["air_time_raw"].fillna("")
    frame["Gap"] = frame.get("gap_raw", "").fillna("") if "gap_raw" in frame.columns else ""
    if "etm_delta_raw" in frame.columns:
        etm_mask = frame["event_type"].fillna("").eq("etm")
        frame.loc[etm_mask, "Gap"] = frame.loc[etm_mask, "etm_delta_raw"].fillna("").map(_local_normalize_gap)
    frame["Kategoria"] = frame["category"].fillna("")
    frame["Wykonawca"] = frame["artist"].fillna("")
    frame["Element / tytuł"] = frame["title"].fillna("")
    frame["Runtime"] = frame["runtime_raw"].fillna("")
    frame["ID"] = frame["external_id"].fillna("")
    frame["⚠"] = frame["time_anomaly"].fillna(0).astype(bool)
    raw_labels = {key: label for key, label, _idx in LOCAL_GSELECTOR_SONG_COLUMNS}
    for key, label in raw_labels.items():
        if label in {"Runtime", "ID", "Exact Time"}:
            continue
        frame[label] = frame[key].fillna("") if key in frame.columns else ""
    frame["Exact Time"] = frame["exact_time_raw"].fillna("")

    # ETM exports carry their own signed timing offset in the third raw field.
    # Keep it available as an optional diagnostic column; it is not conflated
    # with the 60+ minutes/hour overtime shown in Gap.
    # events_for_day exposes only song-field projections.  For ETM the timing
    # delta is added separately by local_station as etm_delta_raw.
    frame["ETM Δ"] = frame["etm_delta_raw"].fillna("") if "etm_delta_raw" in frame.columns else ""
    return frame


LOCAL_TIMELINE_DEFAULT_COLUMNS = [
    "Czas", "Gap", "Typ", "Kategoria", "Wykonawca", "Element / tytuł", "Runtime"
]
LOCAL_TIMELINE_EXTRA_COLUMNS = [
    "Mood", "Opener", "Timing", "Content", "Energy", "Texture Close", "Texture Open",
    "Edit Code", "Exact Time", "Sound Code", "Vocal", "ETM Δ", "ID",
    "Pole 18", "Pole 19", "Pole 20", "Pole 21", "⚠",
]

LOCAL_TIMELINE_ROW_STYLE = JsCode("""
function(params) {
  if (!params || !params.data) return {};
  const t = String(params.data._event_type || '');
  const base = {backgroundColor:'#0d1117'};
  if (t === 'song')    return {...base, color:'#f4f4f5'};
  if (t === 'traffic') return {...base, color:'#ff5d5d'};
  return {...base, color:'#f4cf57'};
}
""")


def _render_local_timeline_grid(frame: pd.DataFrame, columns: list[str], *, key: str) -> None:
    if frame.empty:
        st.info("Brak elementów dla wybranych filtrów.")
        return
    chosen = [c for c in columns if c in frame.columns]
    if not chosen:
        chosen = LOCAL_TIMELINE_DEFAULT_COLUMNS.copy()
    show = frame[[*chosen, "_event_type"]].copy()
    gb = GridOptionsBuilder.from_dataframe(show)
    gb.configure_default_column(resizable=True, sortable=True, filter=True, editable=False)
    gb.configure_grid_options(rowHeight=34, animateRows=False, getRowStyle=LOCAL_TIMELINE_ROW_STYLE)
    gb.configure_column("_event_type", hide=True)
    for col in show.columns:
        if col == "Czas":
            gb.configure_column(col, width=105, minWidth=96, pinned="left")
        elif col == "Gap":
            gb.configure_column(col, width=82, minWidth=74, headerTooltip="ETM: bezpośredni gap +/- z GSelectora. Pozostałe elementy: nadczas 60+ minutes/hour, np. 08:62:47 = +02:47.")
        elif col == "Typ":
            gb.configure_column(col, width=105, minWidth=92, pinned="left")
        elif col in {"Runtime", "Mood", "Opener", "Energy", "Texture Close", "Texture Open", "Edit Code", "Sound Code", "Vocal", "ETM Δ", "⚠"}:
            gb.configure_column(col, width=105, minWidth=88)
        elif col in {"Kategoria", "Wykonawca", "ID"}:
            gb.configure_column(col, minWidth=165, width=195)
        elif col == "Element / tytuł":
            gb.configure_column(col, minWidth=220, width=300)
        elif col.startswith("Pole "):
            gb.configure_column(col, minWidth=105, width=120)
    AgGrid(
        show,
        gridOptions=gb.build(),
        height=690,
        theme="streamlit",
        allow_unsafe_jscode=True,
        enable_enterprise_modules=False,
        custom_css={
            ".ag-cell-focus": {"border": "none !important", "outline": "none !important"},
        },
        key=key,
    )


def _render_local_timeline(kind: str, key_prefix: str, revision: str) -> None:
    dates = cached_local_dates(revision, kind)
    if not dates:
        label = "Scheduled" if kind == "schedule" else "Played"
        st.info(f"Brak danych {label}. Zaimportuj plik GSelectora w zakładce Import.")
        return

    default_date = _local_default_date(dates, kind) or date.fromisoformat(dates[-1])
    dcol, hcol, pcol, ccol = st.columns([.82, .82, 1.35, .72], vertical_alignment="bottom")
    selected_date = dcol.selectbox(
        "Dzień",
        dates,
        index=dates.index(default_date.isoformat()) if default_date.isoformat() in dates else len(dates) - 1,
        format_func=lambda raw: date.fromisoformat(raw).strftime("%d.%m.%Y"),
        key=f"{key_prefix}_date",
    )
    hour_options: list[object] = ["Cały dzień", *range(24)]
    selected_hour = hcol.selectbox(
        "Godzina",
        hour_options,
        format_func=lambda value: str(value) if isinstance(value, str) else f"{int(value):02d}:00–{int(value):02d}:59+",
        key=f"{key_prefix}_hour",
    )
    preset_options = [*LOCAL_ELEMENT_FILTER_PRESETS, "Własny"]
    element_preset = pcol.selectbox(
        "Preset elementów",
        preset_options,
        index=0,
        key=f"{key_prefix}_element_preset",
    )
    with ccol:
        with st.popover("Kolumny", use_container_width=True):
            all_columns = LOCAL_TIMELINE_DEFAULT_COLUMNS + LOCAL_TIMELINE_EXTRA_COLUMNS
            selected_columns = st.multiselect(
                "Widoczne kolumny",
                all_columns,
                default=LOCAL_TIMELINE_DEFAULT_COLUMNS,
                key=f"{key_prefix}_columns",
                help="ID i pola techniczne są dostępne, ale domyślnie ukryte.",
            )
            if not selected_columns:
                st.caption("Gdy nic nie zaznaczysz, tabela wróci do zestawu domyślnego.")

    if element_preset == "Własny":
        selected_types = st.multiselect(
            "Typy elementów",
            list(LOCAL_EVENT_LABELS),
            default=list(LOCAL_EVENT_LABELS),
            format_func=lambda value: LOCAL_EVENT_LABELS.get(value, value),
            key=f"{key_prefix}_types_custom",
        )
    else:
        selected_types = list(LOCAL_ELEMENT_FILTER_PRESETS[element_preset])

    etm_kinds = set(LOCAL_ETM_KINDS)
    ignore_resets = False
    if "etm" in selected_types:
        ecol, xcol, rcol = st.columns([1.25, 2.15, 1.05], vertical_alignment="bottom")
        etm_preset_options = [*LOCAL_ETM_PRESETS, "Własna kombinacja"]
        etm_preset = ecol.selectbox(
            "ETM",
            etm_preset_options,
            index=0,
            key=f"{key_prefix}_etm_preset",
            help="Filtruje ETM-y po nazwie GSelectora: Hard / Soft / Reset / Hit.",
        )
        if etm_preset == "Własna kombinacja":
            etm_kinds = set(xcol.multiselect(
                "Kombinacja ETM",
                LOCAL_ETM_KINDS,
                default=LOCAL_ETM_KINDS,
                key=f"{key_prefix}_etm_custom",
            ))
        else:
            etm_kinds = set(LOCAL_ETM_PRESETS[etm_preset])
            xcol.caption(" ")
        if kind == "schedule":
            ignore_resets = rcol.toggle(
                "Ignoruj resety",
                value=False,
                key=f"{key_prefix}_ignore_resets",
                help=(
                    "RESET nie wymusza startu o swojej godzinie. RadioCharts bierze przesunięcie pierwszego "
                    "elementu po RESET względem czasu RESET i przenosi je do kolejnego HARD/SOFT."
                ),
            )

    # One cached SQLite read per selected day. Hour/type filters and summary are
    # computed in memory instead of reading/decoding the same day 2–3 times.
    full_day_rows = cached_local_day_events(revision, kind, selected_date)
    if kind == "schedule":
        # Rebuild HH:00 Hard/Soft carry from the preceding scheduling hour in
        # memory as well. This fixes already-stored snapshots from 1.2.12-1.2.15
        # without rewriting the cutoff in SQLite.
        full_day_rows = _local_apply_hour_boundary_gaps(full_day_rows)
    if kind == "schedule" and ignore_resets:
        # Recalculate on the complete day before applying the hour filter so
        # RESET carry can cross hourly GetLog windows.
        full_day_rows = _local_apply_ignore_reset_gaps(full_day_rows)
    hour_rows = [
        row for row in full_day_rows
        if selected_hour == "Cały dzień" or row.get("schedule_hour") == int(selected_hour)
    ]
    if kind == "schedule":
        # ETM cards must follow the selected hour. Previously the hour selector
        # filtered only the table while the ETM summary still showed the whole
        # day, which made e.g. 01:00 look like it contained the 00:00 markers.
        _render_local_etm_gap_summary(hour_rows, ignore_resets=ignore_resets)

    rows = [
        row for row in hour_rows
        if not selected_types or str(row.get("event_type") or "") in selected_types
    ]
    if "etm" in selected_types:
        rows = _local_filter_etm_rows(rows, etm_kinds)

    counts: dict[str, int] = {}
    for row in full_day_rows:
        typ = str(row.get("event_type") or "other")
        counts[typ] = counts.get(typ, 0) + 1
    render_compact_metrics([
        ("Elementy", len(full_day_rows)),
        ("Song", counts.get("song", 0)),
        ("Jingle", counts.get("jingle", 0)),
        ("Audycje", counts.get("show", 0)),
    ])
    frame = _local_timeline_frame(rows)
    if frame.empty:
        st.info("Brak elementów dla wybranych filtrów.")
        return

    if selected_hour != "Cały dzień" and "gap_seconds" in pd.DataFrame(rows).columns:
        over = [float(r.get("gap_seconds")) for r in rows if r.get("gap_seconds") is not None]
        if over:
            peak = max(over)
            mins, secs = divmod(peak, 60)
            st.caption(f"Godzina {int(selected_hour):02d}: największy zapisany nadczas 60+ = +{int(mins):02d}:{secs:04.1f}.")

    _render_local_timeline_grid(
        frame,
        selected_columns or LOCAL_TIMELINE_DEFAULT_COLUMNS,
        key=f"{key_prefix}_grid_{selected_date}_{selected_hour}_{element_preset}_{'-'.join(sorted(etm_kinds))}_{int(ignore_resets)}",
    )
    if rows and all(str(r.get("source_system") or "") == "zetta2go" for r in rows):
        st.caption(
            "Gap przy ETM pochodzi bezpośrednio z Zetta2GO. Played pokazuje tylko elementy zagrane / będące w trakcie; "
            "pełny stan READY/NOT_PLAYED jest zachowany w tle do porównania z cutoff Scheduled."
        )
    else:
        st.caption(
            "Gap przy ETM pokazuje wartość +/- z eksportu GSelectora (nie gap wyliczony przez Zettę); przy pozostałych "
            "elementach pokazuje nadczas 60+ minutes/hour. Presety elementów i filtr ETM pozwalają szybko wybrać Hard, "
            "Soft, Reset, Hit albo dowolną kombinację."
        )


def _local_status_symbol(status: str) -> tuple[str, str, str]:
    lowered = str(status or "OK").casefold()
    if status == "Niezagrane":
        return "✕", "rc-status-bad", "Nie zagrano / usunięte"
    if status == "Dodane":
        return "+", "rc-status-bad", "Dodane po cutoff"
    if "zmieniony" in lowered:
        return "≠", "rc-status-bad", "Zmieniony po cutoff"
    if "kolejność" in lowered:
        return "↻", "rc-status-move", "Zmieniona kolejność"
    if "ścięty" in lowered:
        return "✂", "rc-status-cut", "Ścięty / fade"
    if status == "W trakcie":
        return "▶", "rc-status-move", "Aktualnie odtwarzany / stan przejściowy"
    if status == "Oczekuje":
        return "○", "rc-status-move", "Jeszcze nie odtworzono"
    return "✓", "rc-status-ok", "Zgodne"


def _local_log_row_html(
    row: dict,
    status: str = "OK",
    *,
    ghost: bool = False,
    ghost_note: str = "",
) -> str:
    event_type = str(row.get("event_type") or "other")
    if ghost:
        color = "#8b929c"
    elif event_type == "song":
        color = "#f4f4f5"
    elif event_type == "traffic":
        color = "#ff5d5d"
    else:
        color = "#f4cf57"

    category = str(row.get("category") or "")
    short_cat = category.split("/", 1)[0] if category else LOCAL_EVENT_LABELS.get(event_type, event_type)
    artist = str(row.get("artist") or "").strip()
    title = str(row.get("title") or "").strip()
    content = f"{artist} — {title}" if event_type == "song" and artist else (title or category)
    raw_time = str(row.get("air_time_raw") or "")
    gap = str(row.get("gap_raw") or "")
    time_label = raw_time + (f"  ({gap} gap)" if gap else "")
    runtime = str(row.get("runtime_raw") or "")
    type_label = LOCAL_EVENT_LABELS.get(event_type, event_type)
    meta = f"{type_label} · {category}"
    if ghost_note:
        meta += f" · {ghost_note}"

    symbol, status_class, status_title = _local_status_symbol(status)
    badge = ""
    if "ścięty" in str(status).casefold():
        badge = '<span class="rc-log-badge rc-log-badge-fade">FADE</span>'

    row_class = "rc-log-row rc-log-ghost" if ghost else "rc-log-row"
    return (
        f'<div class="{row_class}" style="color:{color}">'
        f'<div class="rc-log-status {status_class}" title="{html.escape(status_title)}">{html.escape(symbol)}</div>'
        f'<div class="rc-log-time">{html.escape(time_label)}</div>'
        f'<div class="rc-log-cat">{html.escape(short_cat)}</div>'
        f'<div class="rc-log-main"><div class="rc-log-title">{html.escape(content)}</div>'
        f'<div class="rc-log-meta">{html.escape(meta)}</div></div>'
        f'<div class="rc-log-runtime">{html.escape(runtime)}</div>'
        f'<div class="rc-log-flags">{badge}</div></div>'
    )


def _local_compare_rows_html(hour: int, pairs: list[dict]) -> str:
    body = []
    for pair in pairs:
        status = str(pair.get("status") or "OK")
        scheduled = pair.get("scheduled_row")
        played = pair.get("played_row")
        if scheduled is None and played is not None:
            left = _local_log_row_html(
                played, status, ghost=True, ghost_note="brak w Scheduled — element dodany",
            )
            right = _local_log_row_html(played, status)
        elif played is None and scheduled is not None:
            left = _local_log_row_html(scheduled, status)
            right = _local_log_row_html(
                scheduled, status, ghost=True, ghost_note="nie zagrano — pozycja z Scheduled",
            )
        elif scheduled is not None and played is not None:
            left = _local_log_row_html(scheduled, status)
            if status == "Oczekuje":
                right = _local_log_row_html(
                    played,
                    status,
                    ghost=True,
                    ghost_note="jeszcze nie zagrano — oczekuje w Zetta",
                )
            else:
                right = _local_log_row_html(played, status)
        else:
            continue
        body.append(f'<div class="rc-compare-pair">{left}{right}</div>')

    if not body:
        body.append(
            '<div class="rc-compare-pair"><div class="rc-log-empty">Brak elementów.</div>'
            '<div class="rc-log-empty">Brak elementów.</div></div>'
        )
    return (
        '<div class="rc-compare-scroll">'
        '<div class="rc-compare-head">'
        f'<div>Scheduled · {int(hour):02d}:00–{int(hour):02d}:59+</div>'
        f'<div>Played · {int(hour):02d}:00–{int(hour):02d}:59+</div>'
        '</div>' + "".join(body) + '</div>'
    )


def _render_local_comparison(revision: str) -> None:
    scheduled_dates = set(cached_local_dates(revision, "schedule"))
    played_dates = set(cached_local_dates(revision, "played"))
    overlap = sorted(scheduled_dates & played_dates)
    if not overlap:
        st.info(
            "Nie ma jeszcze dnia, dla którego są jednocześnie Scheduled i Played. "
            "Po pierwszym eksporcie Played dla dnia z planem porównanie pojawi się automatycznie."
        )
        return

    st.markdown(
        """
        <style>
          .rc-compare-scroll { max-height:690px; overflow:auto; border:1px solid #313844; border-radius:7px; background:#090d12; }
          .rc-compare-head { display:grid; grid-template-columns:minmax(520px,1fr) minmax(520px,1fr); gap:1rem; min-width:1080px; position:sticky; top:0; z-index:4; }
          .rc-compare-head > div { padding:.48rem .62rem; background:#11161d; border-bottom:1px solid #313844; font-weight:700; color:#e7e9ed; }
          .rc-compare-pair { display:grid; grid-template-columns:minmax(520px,1fr) minmax(520px,1fr); gap:1rem; min-width:1080px; align-items:stretch; }
          .rc-log-row { display:grid; grid-template-columns:28px 118px 52px minmax(0,1fr) 62px; gap:.42rem; align-items:start; padding:.31rem .48rem; border-bottom:1px solid #1b222c; background:#090d12; font-size:.80rem; min-width:0; height:100%; }
          .rc-log-row:hover { background:#0f151d; }
          .rc-log-status { display:flex; align-items:center; justify-content:center; min-height:1.25rem; font-size:1rem; font-weight:850; line-height:1; }
          .rc-status-ok { color:#45c878; }
          .rc-status-bad { color:#ff5d5d; }
          .rc-status-move { color:#f4b942; }
          .rc-status-cut { color:#ff8c5a; }
          .rc-log-time { font-variant-numeric:tabular-nums; white-space:nowrap; font-weight:650; }
          .rc-log-cat { font-weight:760; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
          .rc-log-main { min-width:0; }
          .rc-log-title { font-weight:650; white-space:normal; overflow-wrap:anywhere; }
          .rc-log-meta { margin-top:.08rem; font-size:.67rem; opacity:.66; white-space:normal; overflow-wrap:anywhere; }
          .rc-log-runtime { text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; opacity:.88; }
          .rc-log-flags { grid-column:4 / 6; margin-top:-.10rem; }
          .rc-log-badge { display:inline-block; margin:.10rem .25rem 0 0; padding:.02rem .24rem; border:1px solid #8a792e; border-radius:4px; color:#f4cf57; font-size:.60rem; font-weight:750; }
          .rc-log-badge-fade { border-color:#a84848; color:#ff6b6b; }
          .rc-log-ghost { opacity:.27; filter:grayscale(.85); }
          .rc-log-ghost:hover { opacity:.36; filter:grayscale(.7); }
          .rc-log-empty { padding:1rem; color:#858c96; border-bottom:1px solid #1b222c; }
          @media (max-width:900px) {
            .rc-compare-head, .rc-compare-pair { min-width:980px; grid-template-columns:minmax(470px,1fr) minmax(470px,1fr); }
            .rc-log-row { grid-template-columns:26px 92px 46px minmax(0,1fr) 52px; font-size:.74rem; }
          }
        </style>
        """,
        unsafe_allow_html=True,
    )

    selected_date = st.selectbox(
        "Dzień do porównania",
        overlap,
        index=len(overlap) - 1,
        format_func=lambda raw: date.fromisoformat(raw).strftime("%d.%m.%Y"),
        key="our_radio_compare_date",
    )
    # One cached full-day comparison supplies both the 24 h summary and the
    # selected hour. 1.2.5 still reopened/decoded SQLite for compare_hour here.
    day_cmp = cached_local_compare_day(revision, selected_date)
    hour_meta = {int(item["hour"]): item for item in day_cmp.get("hours", [])}
    hour_details = {int(item["hour"]): item for item in day_cmp.get("hour_details", [])}

    def _hour_label(hour: int) -> str:
        item = hour_meta.get(int(hour), {})
        diffs = int(item.get("differences") or 0)
        suffix = "OK" if diffs == 0 else f"{diffs} różn."
        return f"{int(hour):02d}:00–{int(hour):02d}:59+  ·  {suffix}"

    default_hour = 0
    problem_hours = [h for h in range(24) if int(hour_meta.get(h, {}).get("differences") or 0) > 0]
    if selected_date == date.today().isoformat():
        default_hour = datetime.now().hour
    elif problem_hours:
        default_hour = problem_hours[0]

    selected_hour = st.selectbox(
        "Blok godzinny",
        list(range(24)),
        index=default_hour,
        format_func=_hour_label,
        key="our_radio_compare_hour",
    )
    comparison = hour_details.get(int(selected_hour))
    if comparison is None:
        st.info("Brak danych porównania dla wybranego bloku godzinnego.")
        return

    render_compact_metrics([
        ("Scheduled cutoff", comparison["scheduled"]),
        ("Zagrane / w trakcie", comparison.get("played_actual", comparison["played"])),
        ("Oczekuje", comparison.get("waiting", 0)),
        ("Różnice", comparison["differences"]),
        ("Niezagrane / dodane", f"{comparison['missed']} / {comparison['added']}"),
    ])
    st.caption(
        "✓ zgodne · ✕ niezagrane/usunięte · + dodane po cutoff · ↻ zmieniona kolejność · ≠ podmieniony asset · "
        "○ oczekuje · ▶ w trakcie. Scheduled to ostatni snapshot przed emisją; prawa strona to aktualny log Zetty, "
        "więc ingerencje po cutoff widać jeszcze zanim dany element miał zagrać."
    )

    st.markdown(
        _local_compare_rows_html(int(selected_hour), comparison.get("display_pairs") or []),
        unsafe_allow_html=True,
    )
    st.caption(
        "Scheduled i Played mają jeden wspólny pionowy scroll — rolka myszy przewija oba logi jednocześnie. "
        "Celowo nie dokładam osobnych scrolli bocznych, żeby nie komplikować obsługi i synchronizacji."
    )

    st.markdown("#### Różnice w tej godzinie")
    diffs = pd.DataFrame(comparison["difference_rows"])
    if diffs.empty:
        st.success("Kolejność i zawartość bloku są zgodne. Różnice czasu startu są ignorowane.")
    else:
        diffs["Typ"] = diffs["event_type"].map(LOCAL_EVENT_LABELS).fillna(diffs["event_type"])
        diffs["Pozycja"] = diffs.apply(
            lambda r: (
                f"{int(r['scheduled_position'])} → {int(r['played_position'])}"
                if pd.notna(r.get("scheduled_position")) and pd.notna(r.get("played_position"))
                else (f"plan {int(r['scheduled_position'])}" if pd.notna(r.get("scheduled_position")) else f"played {int(r['played_position'])}")
            ),
            axis=1,
        )
        diffs = diffs.rename(columns={
            "status": "Status", "scheduled_time": "Plan", "played_time": "Played",
            "start_delta": "Δ startu", "runtime_cut": "Ścięcie", "artist": "Wykonawca",
            "title": "Element / tytuł", "note": "Uwagi",
        })
        st.dataframe(
            diffs[["Status", "Pozycja", "Plan", "Played", "Δ startu", "Ścięcie", "Typ", "Wykonawca", "Element / tytuł", "Uwagi"]],
            hide_index=True, use_container_width=True, height=min(620, 42 + 35 * len(diffs)),
        )
        st.caption(
            "Δ startu ma format +M:SS / -M:SS i jest informacją pomocniczą — sama różnica czasu nie tworzy błędu. "
            "„Ścięty” dla utworu pojawia się dopiero, gdy Played jest co najmniej 10% i minimum 10 s krótszy od Scheduled; "
            "kilkusekundowe trimy/crossfade'y nie są liczone jako cięcie."
        )

    with st.expander("Podsumowanie wszystkich 24 godzin", expanded=False):
        hours = pd.DataFrame(day_cmp.get("hours") or [])
        if not hours.empty:
            hours["Godzina"] = hours["hour"].map(lambda h: f"{int(h):02d}:00")
            hours = hours.rename(columns={
                "scheduled": "Scheduled", "played": "Live log", "differences": "Różnice",
                "missed": "Niezagrane", "added": "Dodane", "reordered": "Kolejność", "faded": "Ścięte",
                "changed": "Zmienione", "waiting": "Oczekuje", "in_progress": "W trakcie",
                "played_actual": "Zagrane / w trakcie",
            })
            st.dataframe(
                hours[[c for c in ["Godzina", "Scheduled", "Zagrane / w trakcie", "Live log", "Oczekuje", "Różnice", "Niezagrane", "Dodane", "Zmienione", "Kolejność", "Ścięte", "W trakcie"] if c in hours.columns]],
                hide_index=True, use_container_width=True, height=430,
            )


def _render_local_song_stats(revision: str) -> None:
    schedule_dates = cached_local_dates(revision, "schedule")
    played_dates = cached_local_dates(revision, "played")
    available_kinds = []
    if schedule_dates:
        available_kinds.append("schedule")
    if played_dates:
        available_kinds.append("played")
    if not available_kinds:
        st.info("Brak danych do statystyk.")
        return
    labels = {"schedule": "Scheduled", "played": "Played"}
    source_kind = st.radio(
        "Źródło", available_kinds, format_func=lambda value: labels[value],
        horizontal=True, key="our_radio_stats_kind",
    )
    dates = schedule_dates if source_kind == "schedule" else played_dates
    c1, c2 = st.columns(2)
    start = c1.selectbox(
        "Od", dates, index=0,
        format_func=lambda raw: date.fromisoformat(raw).strftime("%d.%m.%Y"),
        key=f"our_radio_stats_start_{source_kind}",
    )
    end = c2.selectbox(
        "Do", dates, index=len(dates) - 1,
        format_func=lambda raw: date.fromisoformat(raw).strftime("%d.%m.%Y"),
        key=f"our_radio_stats_end_{source_kind}",
    )
    if start > end:
        start, end = end, start
    stats = cached_local_song_stats(revision, source_kind, start, end)
    if not stats:
        st.info("Brak utworów w wybranym okresie.")
        return
    frame = pd.DataFrame(stats).rename(columns={
        "artist": "Wykonawca", "title": "Tytuł", "category": "Kategoria", "external_id": "ID",
        "plays": "Emisje / plan", "days_with_play": "Dni", "per_calendar_day": "Na dzień",
        "avg_active_day": "Na aktywny dzień", "max_day": "Max/dzień", "peak_hour": "Najczęstsza godz.",
        "song_id": "song_id",
    })
    frame["Najczęstsza godz."] = frame["Najczęstsza godz."].map(
        lambda value: "—" if pd.isna(value) else f"{int(value):02d}:00"
    )
    render_compact_metrics([
        ("Różne utwory", len(frame)), ("Wszystkie emisje/sloty", int(frame["Emisje / plan"].sum())),
        ("Śr. na utwór", round(float(frame["Emisje / plan"].mean()), 1)),
        ("Zakres", f"{date.fromisoformat(start).strftime('%d.%m')}–{date.fromisoformat(end).strftime('%d.%m')}"),
    ])
    st.dataframe(
        frame[["Wykonawca", "Tytuł", "Kategoria", "Emisje / plan", "Dni", "Na dzień", "Na aktywny dzień", "Max/dzień", "Najczęstsza godz."]],
        hide_index=True, use_container_width=True, height=690,
    )


def _render_emaus_song_activity(song_id: int) -> None:
    # Song detail is the first place outside /EMAUS that needs local-station
    # data. Keep seed/relink deferred until this panel is actually rendered.
    _bootstrap_local_station_seed_once()
    _cached_local_station_song_links(catalog_revision())
    revision = local_station_revision()
    dates = sorted(set(cached_local_dates(revision, "schedule")) | set(cached_local_dates(revision, "played")))
    if not dates:
        return
    activity_all = cached_local_song_activity(revision, int(song_id))
    if not activity_all.get("date_from"):
        st.markdown("### EMAUS")
        st.caption("Ten utwór nie jest jeszcze powiązany z żadnym zaimportowanym elementem EMAUS.")
        return

    st.markdown("### EMAUS")
    st.caption("Plan z GSelectora i faktycznie odegrane po reconciliation są liczone po tym samym canonical song_id co reszta RadioCharts.")
    song_dates = [d for d in dates if str(activity_all["date_from"]) <= d <= str(activity_all["date_to"])] or dates
    c1, c2 = st.columns(2)
    start = c1.selectbox(
        "EMAUS od", song_dates, index=0,
        format_func=lambda raw: date.fromisoformat(raw).strftime("%d.%m.%Y"), key=f"emaus_song_start_{song_id}",
    )
    end = c2.selectbox(
        "EMAUS do", song_dates, index=len(song_dates) - 1,
        format_func=lambda raw: date.fromisoformat(raw).strftime("%d.%m.%Y"), key=f"emaus_song_end_{song_id}",
    )
    if start > end:
        start, end = end, start
    activity = cached_local_song_activity(revision, int(song_id), start, end)
    render_compact_metrics([
        ("Played", int(activity.get("played") or 0)), ("Played / dzień", activity.get("played_per_day") or 0),
        ("Scheduled", int(activity.get("scheduled") or 0)),
        ("Następna", (str(activity.get("next_scheduled") or "—").replace("2026-", ""))),
    ])
    daily = pd.DataFrame(activity.get("daily") or [])
    if not daily.empty:
        daily["Δ Played−Scheduled"] = daily["played"] - daily["scheduled"]
        daily = daily.rename(columns={"date": "Dzień", "scheduled": "Scheduled", "played": "Played"})
        st.dataframe(daily[["Dzień", "Scheduled", "Played", "Δ Played−Scheduled"]], hide_index=True, use_container_width=True, height=min(300, 42 + 35 * len(daily)))
    meta = []
    if activity.get("last_played"):
        meta.append(f"ostatnio: {activity['last_played']}")
    if activity.get("next_scheduled"):
        meta.append(f"następny plan: {activity['next_scheduled']}")
    if meta:
        st.caption(" · ".join(meta))


def _render_local_import(revision: str) -> None:
    st.markdown("#### Zetta2GO — automatyczna synchronizacja")
    zcfg = zetta2go_settings()
    if zcfg.configured:
        st.caption(
            f"Skonfigurowano {zcfg.base_url} · horyzont Scheduled: {zcfg.schedule_horizon_days} dni. "
            "Worker odświeża Played co minutę. Codziennie o 23:59 pobiera przyszłe logi; jutrzejszy log staje się cutoff "
            "i nie jest już później nadpisywany jako Scheduled, więc zmiany po cutoff są widoczne jako ingerencje."
        )
        z1, z2, z3 = st.columns(3)
        if z1.button("Test Zetta2GO", key="zetta_test_btn"):
            try:
                st.session_state["zetta_ui_result"] = {"kind": "test", "data": local_test_zetta2go_connection()}
            except Exception as exc:
                st.session_state["zetta_ui_result"] = {"kind": "error", "data": str(exc)}
            st.rerun()
        if z2.button("Odśwież Played teraz", key="zetta_live_btn"):
            try:
                st.session_state["zetta_ui_result"] = {"kind": "live", "data": local_sync_zetta2go_live()}
            except Exception as exc:
                st.session_state["zetta_ui_result"] = {"kind": "error", "data": str(exc)}
            st.rerun()
        if z3.button("Odśwież przyszłe Scheduled", key="zetta_schedule_btn"):
            try:
                st.session_state["zetta_ui_result"] = {
                    "kind": "schedule",
                    "data": local_sync_zetta2go_schedule_horizon(horizon_days=zcfg.schedule_horizon_days, mark_cutoff=False),
                }
            except Exception as exc:
                st.session_state["zetta_ui_result"] = {"kind": "error", "data": str(exc)}
            st.rerun()
    else:
        st.info(
            "Zetta2GO nie jest jeszcze skonfigurowane. Ustaw login i hasło w zakładce Ustawienia. "
            "Web i worker korzystają z tej samej zapisanej konfiguracji."
        )
        st.markdown('<a href="?view=settings" target="_self">→ Otwórz Ustawienia</a>', unsafe_allow_html=True)

    zetta_result = st.session_state.pop("zetta_ui_result", None)
    if zetta_result:
        if zetta_result.get("kind") == "error":
            st.error(f"Zetta2GO: {zetta_result.get('data')}")
        else:
            data = zetta_result.get("data") or {}
            if zetta_result.get("kind") == "schedule":
                st.success(
                    f"Scheduled: odświeżono {len(data.get('days') or [])} dni · cutoff {data.get('cutoff_date') or '—'}."
                )
            elif zetta_result.get("kind") == "live":
                st.success(
                    f"Played live: {data.get('rows', 0)} elementów · zagrane/w trakcie {data.get('played_rows', 0)} · "
                    f"niezagrane {data.get('nonplayed_rows', 0)} · oczekujące {data.get('upcoming_rows', 0)}."
                )
            else:
                st.success(f"Zetta2GO działa · rekordów bieżącego dnia: {data.get('records', 0)}.")

    st.markdown("#### Ręczny importer GSelector (fallback / archiwum)")
    st.caption(
        "Importer przyjmuje obecny eksport TSV/TXT. Wielodniowy plik jest dzielony po znacznikach UTF-8 BOM, "
        "a nowszy import tego samego dnia staje się bieżącym snapshotem; starsza wersja zostaje w historii."
    )
    upload = st.file_uploader("Plik GSelector", type=["txt", "tsv", "log"], key="our_radio_file")
    if upload is not None:
        payload = upload.getvalue()
        preview = preview_local_import(payload, upload.name)
        p1, p2, p3 = st.columns(3)
        p1.metric("Wiersze", preview["rows"])
        p2.metric("Dni", preview["days"])
        p3.metric("Zakres z nazwy", f"{preview.get('inferred_start') or '—'} → {preview.get('inferred_end') or '—'}")
        counts = preview.get("event_counts") or {}
        st.caption(" · ".join(f"{LOCAL_EVENT_LABELS.get(k,k)}: {v}" for k, v in sorted(counts.items())))
        for warning in preview.get("warnings") or []:
            st.warning(warning)

        kind_col, date_col = st.columns(2)
        kind_label = kind_col.radio("Rodzaj", ["Scheduled", "Played"], horizontal=True, key="our_radio_import_kind")
        kind = "schedule" if kind_label == "Scheduled" else "played"
        inferred = preview.get("inferred_start")
        default_start = date.fromisoformat(inferred) if inferred else date.today()
        import_start = date_col.date_input("Data pierwszego dnia w pliku", value=default_start, key="our_radio_import_start")
        if st.button("Importuj do EMAUS", type="primary", key="our_radio_import_btn"):
            result = import_local_gselector_export(
                payload,
                filename=upload.name,
                kind=kind,
                start_date=import_start,
                source="manual-ui",
            )
            st.session_state["our_radio_import_result"] = result
            st.rerun()

    result = st.session_state.pop("our_radio_import_result", None)
    if result:
        verb = "już był zaimportowany" if result.get("duplicate") else "zaimportowano"
        st.success(
            f"{verb}: {result['rows']} wierszy / {result['days']} dni · "
            f"{result['date_from']} → {result['date_to']}."
        )

    deleted = st.session_state.pop("our_radio_deleted_import", None)
    if deleted:
        st.success(
            f"Usunięto import #{deleted['deleted_import_id']}: {deleted['source_name']} · "
            f"{deleted['date_from']} → {deleted['date_to']}. "
            f"Przywrócono wcześniejszy snapshot dla {deleted['restored_days']} dni."
        )

    history_raw = cached_local_import_history(revision)
    history = pd.DataFrame(history_raw)
    if not history.empty:
        history_view = history.rename(columns={
            "kind": "Typ", "source_name": "Plik", "date_from": "Od", "date_to": "Do",
            "day_count": "Dni", "row_count": "Wiersze", "source": "Źródło", "imported_at": "Import",
        })
        st.markdown("#### Historia importów")
        st.dataframe(history_view[["Typ", "Plik", "Od", "Do", "Dni", "Wiersze", "Źródło", "Import"]], hide_index=True, use_container_width=True)

        with st.expander("🗑️ Usuń błędny import", expanded=False):
            choices = {
                int(row["id"]): (
                    f"#{int(row['id'])} · {'Scheduled' if row['kind'] == 'schedule' else 'Played'} · "
                    f"{row['source_name']} · {row['date_from']} → {row['date_to']} · {int(row['row_count'])} wierszy"
                )
                for row in history_raw
            }
            selected_import_id = st.selectbox(
                "Import do usunięcia",
                list(choices),
                format_func=lambda value: choices[int(value)],
                key="our_radio_delete_import_id",
            )
            confirm_delete = st.checkbox(
                "Potwierdzam usunięcie tego importu i jego elementów",
                key="our_radio_delete_import_confirm",
            )
            st.caption(
                "Jeżeli usuwany import był bieżącym snapshotem dnia, RadioCharts automatycznie przywróci poprzedni import tego samego typu i dnia."
            )
            if st.button(
                "Usuń import",
                disabled=not confirm_delete,
                type="secondary",
                key="our_radio_delete_import_btn",
            ):
                result = delete_local_import(int(selected_import_id))
                st.session_state["our_radio_deleted_import"] = result
                st.rerun()


def _render_settings() -> None:
    st.subheader("⚙️ Ustawienia")
    st.caption("Ustawienia aplikacji wspólne dla web i workera. Dane są przechowywane lokalnie w bazie RadioCharts i nie trafiają do repozytorium Git.")

    st.markdown("### EMAUS / Zetta2GO")
    zcfg = zetta2go_settings()
    if isinstance(zcfg.verify_tls, str):
        st.info(f"Weryfikacja TLS korzysta obecnie z CA bundle: {zcfg.verify_tls}. Pole poniżej zmieni zwykłe verify on/off dopiero po usunięciu ZETTA2GO_CA_BUNDLE z konfiguracji środowiska.")

    with st.form("zetta2go_settings_form", clear_on_submit=False):
        c1, c2 = st.columns(2)
        username = c1.text_input("Login Zetta2GO", value=zcfg.username, autocomplete="username")
        password = c2.text_input("Hasło Zetta2GO", value=zcfg.password, type="password", autocomplete="current-password")

        a1, a2 = st.columns([1.35, 1])
        base_url = a1.text_input("Adres Zetta2GO", value=zcfg.base_url)
        station_id = a2.text_input("Station ID EMAUS", value=zcfg.station_id)

        o1, o2, o3 = st.columns(3)
        verify_tls = o1.checkbox("Weryfikuj certyfikat TLS", value=(zcfg.verify_tls is True))
        live_enabled = o2.checkbox("Played live co minutę", value=zcfg.live_enabled)
        schedule_enabled = o3.checkbox("Scheduled + cutoff", value=zcfg.schedule_enabled)
        horizon = st.number_input(
            "Ile dni Scheduled pobierać do przodu", min_value=1, max_value=31,
            value=int(zcfg.schedule_horizon_days), step=1,
        )
        st.caption("Cutoff jutrzejszego logu: 23:59 dnia poprzedniego. Po zapisaniu ustawień worker zobaczy je automatycznie przy następnym cyklu — restart kontenera nie jest potrzebny.")

        b1, b2, _ = st.columns([1, 1, 2.5])
        save_only = b1.form_submit_button("Zapisz", type="primary", use_container_width=True)
        save_test = b2.form_submit_button("Zapisz i testuj", use_container_width=True)

    if save_only or save_test:
        save_zetta2go_settings(
            username=username, password=password, base_url=base_url, station_id=station_id,
            verify_tls=verify_tls, schedule_horizon_days=int(horizon),
            live_enabled=live_enabled, schedule_enabled=schedule_enabled,
        )
        if save_test:
            try:
                result = local_test_zetta2go_connection()
                st.session_state["settings_zetta_message"] = ("success", f"Zetta2GO działa · rekordów bieżącego dnia: {result.get('records', 0)}.")
            except Exception as exc:
                st.session_state["settings_zetta_message"] = ("error", f"Zetta2GO: {exc}")
        else:
            st.session_state["settings_zetta_message"] = ("success", "Ustawienia Zetta2GO zapisane. Worker użyje ich przy następnym cyklu.")
        st.rerun()

    message = st.session_state.pop("settings_zetta_message", None)
    if message:
        kind, text = message
        (st.success if kind == "success" else st.error)(text)

    if st.button("Wyczyść login i hasło Zetta2GO", key="clear_zetta_credentials"):
        save_zetta2go_settings(
            username="", password="", base_url=zcfg.base_url, station_id=zcfg.station_id,
            verify_tls=(zcfg.verify_tls is True), schedule_horizon_days=zcfg.schedule_horizon_days,
            live_enabled=zcfg.live_enabled, schedule_enabled=zcfg.schedule_enabled,
        )
        st.session_state["settings_zetta_message"] = ("success", "Login i hasło Zetta2GO wyczyszczone; automatyczna synchronizacja będzie pomijana.")
        st.rerun()


view_key = BOOT_VIEW_KEY
render_nav_tabs(view_key)
install_client_helpers()

# Resolve each revision at most once per Streamlit rerun.  Tab changes rerun the
# script, so repeated revision queries used to add visible latency before the
# actual page query even started.
_chart_views = {"dashboard", "archive", "song", "airplay", "library"}
_air_views = {"archive", "song", "airplay", "library"}
CHART_REV = chart_revision() if view_key in _chart_views else ""
AIR_REV = airplay_revision() if view_key in _air_views else ""
AIR_DATA_REV = airplay_data_revision() if view_key == "dashboard" else ""
REVISION = CHART_REV

if view_key in {"dashboard", "archive"}:
    if view_key == "dashboard":
        # Cache the expensive immutable score+airplay merge.  Only live notes are
        # overlaid on each Streamlit rerun.
        df = with_notes(cached_dashboard_base_frame(REVISION, AIR_DATA_REV, 0))
    else:
        df = with_notes(cached_scores(REVISION))
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
        ctl_count, ctl_period, ctl_scope, ctl_status, ctl_dl, ctl_layout, ctl_fam, ctl_mom = st.columns(
            [.88, .96, 1.18, 1.02, .78, .68, .80, .80],
            vertical_alignment="bottom",
        )
        period_label = ctl_period.selectbox(
            "Okres wskaźników",
            list(period_map),
            index=len(period_map) - 1,
            help="Chart Score i Momentum są liczone ponownie tylko z obserwacji z wybranego okresu. Widok Całość najlepiej oddaje historię list; krótsze okresy służą do analizy świeżego zachowania.",
        )
        lookback = int(period_map[period_label])
        period_df = df if lookback == 0 else with_notes(
            cached_dashboard_base_frame(REVISION, AIR_DATA_REV, lookback)
        )

        # Dashboard: selected-period spin count.  Całość uses the song-ordered
        # index (very fast even for a multi-million-row archive); finite periods
        # use the time covering index. No station-list/coverage scan is needed.
        dash_snapshot = cached_dashboard_airplay(AIR_DATA_REV)
        dash_last = dash_snapshot.get("end_date")
        if dash_last:
            dash_air_end = date.fromisoformat(str(dash_last))
            if lookback == 0:
                dash_counts_raw = cached_dashboard_period_spins(AIR_DATA_REV, "", "")
            else:
                dash_air_start = dash_air_end - timedelta(days=max(0, lookback - 1))
                dash_counts_raw = cached_dashboard_period_spins(
                    AIR_DATA_REV, dash_air_start.isoformat(), dash_air_end.isoformat()
                )
            dash_counts = pd.DataFrame(dash_counts_raw)
            if not dash_counts.empty:
                dash_counts = dash_counts[["song_id", "spins"]].rename(columns={"spins": "airplay_spins_period"})
                period_df = period_df.merge(dash_counts, on="song_id", how="left")
            if "airplay_spins_period" not in period_df.columns:
                period_df["airplay_spins_period"] = 0
            period_df["airplay_spins_period"] = pd.to_numeric(
                period_df["airplay_spins_period"], errors="coerce"
            ).fillna(0).astype(int)
        else:
            period_df["airplay_spins_period"] = 0

        if period_df.empty:
            st.info("Brak danych w wybranym okresie.")
        else:
            scope = ctl_scope.selectbox(
                "Zakres",
                ["W najnowszych notowaniach", "PL w najnowszych", "Zagraniczne w najnowszych", "Cała historia"],
                index=0,
                help="„W najnowszych” = utwór jest obecny w najnowszym zapisanym notowaniu co najmniej jednego odpowiedniego źródła. To nie znaczy po prostu „kiedyś ostatnio pobrany”.",
            )
            selected_statuses = render_status_checkbox_filter(
                ctl_status, key="dashboard_status_filter", base_only=False
            )
            downloaded_choice = ctl_dl.selectbox(
                "Downloaded", DOWNLOAD_FILTER_OPTIONS, index=0, key="dashboard_downloaded_filter"
            )
            table_layout_label = ctl_layout.selectbox(
                "Tabela",
                ["Auto", "Pełny", "Kompaktowy"],
                index=2,
                help="Kompaktowy jest domyślny. Auto może rozwinąć tygodnie do osobnych kolumn na bardzo szerokim ekranie.",
            )
            min_fam = ctl_fam.slider("Min. Chart Score", 0, 100, 0, format="%d%%")
            min_mom = ctl_mom.slider("Min. Momentum", 0, 100, 0, format="%d%%")
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
            view = apply_status_filter(view, selected_statuses)
            view = apply_download_filter(view, downloaded_choice)
            song_query = st.text_input(
                "Szukaj w Dashboardzie",
                placeholder="wykonawca lub tytuł, np. meskie / Waligóra / Azizam",
                key="dashboard_song_search",
                help="Przeszukuje wszystkie utwory po zastosowaniu zakresu i progów, jeszcze przed wyświetleniem tabeli. Polskie znaki nie mają znaczenia.",
            )
            if song_query.strip():
                view = filter_song_rows(view, song_query)
            view = view.reset_index(drop=True)

            count_key = "dashboard_count_display"
            st.session_state[count_key] = f"{len(view)} / {len(period_df)}"
            ctl_count.text_input(
                "Utwory (filtr / okres)",
                key=count_key,
                disabled=True,
                label_visibility="visible",
            )

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
            view["spotify"] = [spotify_search_url(a, t) for a, t in zip(view.artist, view.title)]
            view["spotify_copy"] = view["spotify"]
            view["preview"] = "▶"
            view["status"] = view["status"].fillna("Nie słuchałem").astype(str)
            if "downloaded" not in view.columns:
                view["downloaded"] = False
            else:
                view["downloaded"] = view["downloaded"].fillna(False).astype(bool)

            cols = [
                "song_id", "artist", "title", "release_month", "preview", "heard", "status", "downloaded", "spotify", "spotify_copy",
                "popularity", "familiarity", "momentum", "radio_presence", "radio_reach", "airplay_spins_7d", "airplay_spins_period", "radio_rotation",
                "avg_position", "RMF_pos", "RMF_weeks", "ZET_pos", "ZET_weeks", "OLIA_pos", "OLIA_weeks",
                "OLIS_pos", "OLIS_weeks", "ESKA_pos", "ESKA_weeks",
                "UK_pos", "UK_weeks", "BILLBOARD_pos", "BILLBOARD_weeks", "note",
            ]
            show = view[[c for c in cols if c in view.columns]].copy()
            pos_cols = [c for c in show.columns if c.endswith("_pos")]
            for col in pos_cols:
                show[col] = show[col].map(position_sort_value).astype(int)
            show = show.rename(columns={c: c.replace("_pos", "") for c in pos_cols})
            # streamlit-aggrid keeps its own frontend row model for a stable widget key.
            # When Dashboard filters/search changed, the Python frame was fresh but the
            # existing grid could keep showing the previous rows until a full browser
            # refresh.  Include every row-affecting control in the component key so the
            # grid is remounted immediately as the user types/clears the search box.
            dashboard_grid_state = quote(
                f"{min_fam}|{min_mom}|{downloaded_choice}|{','.join(sorted(selected_statuses))}|{normalize(song_query)}",
                safe="",
            )[:120]
            render_song_grid(
                show,
                key=f"dashboard_grid_{lookback}_{scope}_{source_layout}_{dashboard_grid_state}",
                height=660,
                editable_state=True,
                source_layout=source_layout,
                floating_hscroll=True,
                row_numbers=True,
            )
            st.caption("Kompaktowy składa pozycję i tygodnie do jednej komórki, np. #7 (5w). Popularity bazuje głównie na emisjach z ostatnich 28 dni; szczegóły są w Manualu. ▶ 30s otwiera player przyklejony do dołu ekranu.")

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
                row["downloaded"] = bool(song_meta.get("downloaded", False))
                row["note"] = str(song_meta.get("note") or "")

                radio = cached_airplay_song_presence(AIR_REV, song_id, 7)
                reporting = int(radio.get("reporting_stations") or 0)
                spotify_url = spotify_search_url(str(row.artist), str(row.title))

                with st.container(border=True):
                    head1, head2, head3, head4 = st.columns([5.2, 1.05, .9, 1.2])
                    with head1:
                        st.markdown(
                            f'<div class="rc-song-title">{html.escape(str(row.artist))} — {html.escape(str(row.title))}</div>'
                            f'<div class="rc-song-meta">{html.escape(str(row.status))}</div>',
                            unsafe_allow_html=True,
                        )
                    with head2:
                        render_preview_button(song_id, row.artist, row.title, spotify_url)
                    with head3:
                        st.link_button("Spotify ↗", spotify_url, use_container_width=True)
                    with head4:
                        st.link_button("OLiS wyróżnienia ↗", olis_awards_url(), use_container_width=True)

                    pop_frame = with_popularity(pd.DataFrame([row.to_dict()]), AIR_REV)
                    popularity_label = f"{float(pop_frame.iloc[0].get('popularity', 0)):.0f}%" if not pop_frame.empty else "—"
                    fam_label = f"{float(row.familiarity):.0f}%" if has_chart_data else "—"
                    mom_label = f"{float(row.momentum):.0f}%" if has_chart_data else "—"
                    radio_label = f"{float(radio.get('radio_presence') or 0):.0f}%" if reporting else "—"
                    reach_label = f"{float(radio.get('radio_reach') or 0):.0f}%" if reporting else "—"
                    rotation_label = f"{float(radio.get('radio_rotation') or 0):.0f}%" if reporting else "—"
                    render_compact_metrics([
                        ("Popularity", popularity_label),
                        ("Chart Score", fam_label),
                        ("Momentum", mom_label),
                        ("Zasięg 7d", reach_label),
                        ("Emisje 7d", int(radio.get("spins") or 0) if reporting else "—"),
                        ("Radio Presence 7d", radio_label),
                    ], columns=6)
                    if row.note:
                        st.caption(f"Notatka: {row.note}")

                # Load history once. It is reused by the source summary and the
                # interactive chart, so peak dates are exact when that peak is
                # present in our stored archive.
                h = cached_song_history(REVISION, song_id)

                def _source_peak_label(src: str) -> str:
                    peak_value = row.get(f"{src}_peak")
                    label = position_display(peak_value)
                    if h.empty or label == "—":
                        return label
                    try:
                        peak_pos = int(float(peak_value))
                    except (TypeError, ValueError):
                        return label
                    src_h = h[h["source"] == src].copy()
                    if src_h.empty:
                        return label
                    pos = pd.to_numeric(src_h["position"], errors="coerce")
                    dates = pd.to_datetime(src_h.loc[pos == peak_pos, "chart_date"], errors="coerce").dropna()
                    if dates.empty:
                        # A source can report a historical peak older than our archive.
                        return label
                    return f"{label} · {dates.min().strftime('%d.%m.%Y')}"

                def _source_frame(sources: list[str]) -> pd.DataFrame:
                    rows = []
                    for src in sources:
                        rows.append({
                            "Źródło": src,
                            "Pozycja": position_display(row.get(f"{src}_pos")),
                            "Tygodnie": int(row.get(f"{src}_weeks", 0) or 0),
                            "Peak": _source_peak_label(src),
                        })
                    return pd.DataFrame(rows)

                st.markdown("### Pozycje i historia źródłowa")
                source_table = pd.concat([
                    _source_frame(["OLIA", "RMF", "ZET", "OLIS", "ESKA"]).assign(Rola="Polska / Chart Score"),
                    _source_frame(["UK", "BILLBOARD"]).assign(Rola="Sygnał międzynarodowy"),
                ], ignore_index=True)
                source_table = source_table[["Źródło", "Rola", "Pozycja", "Tygodnie", "Peak"]]
                render_info_grid(source_table, key=f"song_sources_{song_id}", height=258)
                st.caption("Peak pokazuje też datę pierwszego osiągnięcia tej pozycji, jeśli ten punkt znajduje się w naszym archiwum. UK/Billboard są sygnałami pomocniczymi i nie zmieniają wag Chart Score.")

                st.markdown("### Historia pozycji")
                if h.empty:
                    st.caption("Brak zapisanej historii pozycji dla tego utworu. Jeśli trafił tu z Emisji, może jeszcze nie występować w żadnym naszym notowaniu.")
                else:
                    available_sources = list(dict.fromkeys(h["source"].tolist()))
                    default_sources = available_sources
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
                        plot_df["chart_date"] = pd.to_datetime(plot_df["chart_date"], errors="coerce").dt.normalize()
                        plot_df = plot_df.dropna(subset=["chart_date", "position"]).sort_values(["source", "chart_date"])
                        maxpos = max(20, int(pd.to_numeric(plot_df.position, errors="coerce").max()))
                        if scale_mode.startswith("Nieliniowa"):
                            plot_df["position_plot"] = pd.to_numeric(plot_df["position"], errors="coerce").astype(float).map(math.sqrt)
                            fig = px.line(
                                plot_df, x="chart_date", y="position_plot", color="source", markers=True,
                                custom_data=["position"],
                            )
                            ticks = [x for x in [1, 2, 3, 5, 10, 20, 40, 60, 80, 100, 150, 200] if x <= maxpos]
                            if maxpos not in ticks:
                                ticks.append(maxpos)
                            fig.update_yaxes(
                                autorange="reversed", range=[math.sqrt(maxpos + 3), 1], tickmode="array",
                                tickvals=[math.sqrt(x) for x in ticks], ticktext=[str(x) for x in ticks],
                                title="Pozycja (skala nieliniowa)",
                            )
                        else:
                            fig = px.line(
                                plot_df, x="chart_date", y="position", color="source", markers=True,
                                custom_data=["position"],
                            )
                            fig.update_yaxes(autorange="reversed", range=[maxpos + 3, 1], dtick=5, title="Pozycja")

                        # custom_data is attached per trace by Plotly Express. The
                        # old code assigned one global DataFrame to every trace,
                        # which could show e.g. '#1' while hovering a completely
                        # different vertical position.
                        fig.update_traces(
                            hovertemplate="%{fullData.name} · #%{customdata[0]}<extra></extra>",
                            marker=dict(size=7),
                        )
                        fig.update_layout(
                            height=430,
                            hovermode="x unified",
                            hoverdistance=100,
                            spikedistance=-1,
                            legend=dict(orientation="h", yanchor="top", y=-0.12, x=0),
                            margin=dict(t=12, b=65, l=35, r=20),
                        )
                        fig.update_xaxes(
                            title=None,
                            hoverformat="%d.%m.%Y",
                            showspikes=True,
                            spikemode="across",
                            spikesnap="cursor",
                            spikethickness=1,
                            spikecolor="rgba(255,255,255,0.45)",
                        )
                        st.plotly_chart(fig, use_container_width=True)
                        st.caption("Najedź na datę: pionowa linia pokazuje wspólny przekrój, a dymek wszystkie listy mające punkt tego dnia. Data jest dzienna — bez godziny.")

                st.markdown("### Emisje radiowe")
                song_airplay_stations = cached_airplay_stations(AIR_REV, True)
                all_song_station_ids = [int(s["station_id"]) for s in song_airplay_stations]
                song_station_labels = {int(s["station_id"]): str(s["name"]) for s in song_airplay_stations}
                song_core_ids = [
                    sid for sid, name in song_station_labels.items()
                    if name.casefold() in {"rmf fm", "zet", "eska", "radio zet", "radio eska"}
                ]
                if not all_song_station_ids:
                    st.caption("Brak aktywnych stacji w Emisjach.")
                else:
                    song_scope_col, song_station_col = st.columns([1, 3])
                    song_station_scope = song_scope_col.radio(
                        "Stacje",
                        ["Wszystkie stacje", "Wybrane stacje"],
                        horizontal=True,
                        key="song_airplay_station_scope",
                    )
                    if song_station_scope == "Wszystkie stacje":
                        song_station_ids = all_song_station_ids
                        song_station_col.caption(f"Analiza {len(song_station_ids)} aktywnych stacji.")
                    else:
                        chosen_song_station_ids = song_station_col.multiselect(
                            "Wybierz stacje",
                            all_song_station_ids,
                            default=song_core_ids or all_song_station_ids[: min(5, len(all_song_station_ids))],
                            format_func=lambda sid: song_station_labels.get(int(sid), str(sid)),
                            key="song_airplay_station_multiselect",
                        )
                        song_station_ids = [int(x) for x in chosen_song_station_ids]

                    if not song_station_ids:
                        st.info("Wybierz przynajmniej jedną stację.")
                    else:
                        song_cov = cached_airplay_coverage(AIR_REV, tuple(sorted(all_song_station_ids)))
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
                            AIR_REV,
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
                        song_station_cov = cached_airplay_station_coverage(AIR_REV, tuple(sorted(song_station_ids)), song_air_start.isoformat(), song_air_end.isoformat())
                        song_reporting_count = sum(1 for x in song_station_cov if int(x.get("plays") or 0) > 0)
                        range_reach = (100.0 * song_station_count / song_reporting_count) if song_reporting_count else float("nan")
                        range_rotation = min(100.0, 100.0 * song_avg_station_day / 6.0)
                        range_presence = (0.70 * range_reach + 0.30 * range_rotation) if song_reporting_count else float("nan")
                        station_rows = list(song_air_detail.get("stations") or [])
                        top_station_row = max(station_rows, key=lambda x: int(x.get("spins") or 0), default={})
                        max_station_spins = int(top_station_row.get("spins") or 0)
                        top_station_name = str(top_station_row.get("station") or "")
                        core_values = [pd.to_numeric(row.get(f"{src}_pos"), errors="coerce") for src in ["RMF", "ZET", "ESKA", "OLIA", "OLIS"]]
                        valid_core = [float(x) for x in core_values if not pd.isna(x)]
                        current_avg_position = round(sum(valid_core) / len(valid_core), 1) if valid_core else float("nan")
                        song_release_month = release_month(
                            song_meta.get("release_date"),
                            row.get("first_chart_date") if has_chart_data else None,
                        )
                        song_air_row = {
                            "song_id": song_id,
                            "spins": song_spins,
                            "artist": str(row.artist),
                            "title": str(row.title),
                            "release_month": song_release_month,
                            "heard": bool(row.heard),
                            "status": normalized_status(str(row.status)),
                            "downloaded": bool(row.downloaded),
                            "popularity": float(pop_frame.iloc[0].get("popularity", 0)) if not pop_frame.empty else 0.0,
                            "familiarity": float(row.familiarity) if has_chart_data else float("nan"),
                            "momentum": float(row.momentum) if has_chart_data else float("nan"),
                            "radio_reach": float(radio.get("radio_reach")) if reporting else float("nan"),
                            "airplay_spins_7d": int(radio.get("spins") or 0) if reporting else 0,
                            "avg_position": current_avg_position,
                            "stations_count": song_station_count,
                            "radio_rotation": round(range_rotation, 1),
                            "radio_presence_period": round(range_presence, 1) if song_reporting_count else float("nan"),
                            "avg_per_day": round(song_avg_day, 1),
                            "avg_station_day": round(song_avg_station_day, 2),
                            "max_station_spins": max_station_spins,
                            "top_station": top_station_name,
                            "last_play": song_last_play,
                            "RMF": position_sort_value(row.get("RMF_pos")),
                            "RMF_weeks": int(row.get("RMF_weeks", 0) or 0),
                            "ZET": position_sort_value(row.get("ZET_pos")),
                            "ZET_weeks": int(row.get("ZET_weeks", 0) or 0),
                            "OLIA": position_sort_value(row.get("OLIA_pos")),
                            "OLIA_weeks": int(row.get("OLIA_weeks", 0) or 0),
                            "OLIS": position_sort_value(row.get("OLIS_pos")),
                            "OLIS_weeks": int(row.get("OLIS_weeks", 0) or 0),
                            "ESKA": position_sort_value(row.get("ESKA_pos")),
                            "ESKA_weeks": int(row.get("ESKA_weeks", 0) or 0),
                            "note": str(row.note or ""),
                        }
                        song_station_sig = "-".join(str(x) for x in sorted(song_station_ids)) or "none"
                        render_song_grid(
                            pd.DataFrame([song_air_row]),
                            key=f"song_airplay_grid_{song_id}_{song_air_start}_{song_air_end}_{song_station_sig}",
                            height=92,
                            editable_state=True,
                            source_layout="airplay",
                            station_total=song_reporting_count,
                        )
                        selected_scope_label = (
                            f"wszystkie aktywne ({len(song_station_ids)})"
                            if song_station_scope == "Wszystkie stacje"
                            else f"wybrane ({len(song_station_ids)})"
                        )
                        st.caption(
                            f"{song_air_start} → {song_air_end} · stacje: {selected_scope_label} · "
                            f"raportujące w okresie: {song_reporting_count}/{len(song_station_ids)}. "
                            "Zasięg 7d i Emisje 7d pozostają globalnym sygnałem 7-dniowym; dane okresowe i szczegóły poniżej respektują wybór stacji."
                        )

                        with st.expander("Szczegóły emisji per stacja i dzień", expanded=True):
                            # Resolve the detail from the currently selected range here
                            # as well. The cached helper is date-keyed, so changing the
                            # preset or either exact date immediately changes both the
                            # one-row summary above and these station/day details.
                            detail_for_range = cached_airplay_track_detail(
                                AIR_REV,
                                tuple(sorted(song_station_ids)),
                                song_air_start.isoformat(),
                                song_air_end.isoformat(),
                                song_id,
                            )
                            st.caption(f"Zakres szczegółów: {song_air_start} → {song_air_end}")
                            detail_left, detail_right = st.columns([1.15, 1])
                            station_df = pd.DataFrame(detail_for_range.get("stations") or [])
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
                                daily_df = pd.DataFrame(detail_for_range.get("daily") or [])
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

                _render_emaus_song_activity(song_id)

                render_song_note_editor(
                    song_id,
                    str(row.status),
                    bool(row.downloaded),
                    str(row.note or ""),
                )

                # Ręczne scalanie duplikatów jest celowo tylko w tabeli Emisje:
                # tam widać wszystkie warianty obok siebie i trudniej pomylić kierunek scalania.

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
                hist_core = [c for c in ["RMF_pos", "ZET_pos", "ESKA_pos", "OLIA_pos", "OLIS_pos"] if c in historical_scores.columns]
                historical_scores["avg_position"] = historical_scores[hist_core].apply(pd.to_numeric, errors="coerce").mean(axis=1).round(1) if hist_core else float("nan")
                score_cols = ["song_id", "familiarity", "momentum", "avg_position", "status", "downloaded", "note",
                              "RMF_pos", "ZET_pos", "ESKA_pos", "OLIA_pos", "OLIS_pos"]
                entries = entries.drop(columns=[c for c in ["status", "downloaded", "note"] if c in entries.columns]).merge(
                    historical_scores[score_cols], on="song_id", how="left",
                )
            hist_presence = pd.DataFrame(
                cached_airplay_presence_at(AIR_REV, 7, str(meta["chart_date"])).get("rows") or []
            )
            if not hist_presence.empty and "radio_reach" in hist_presence.columns:
                hist_keep = [c for c in ["song_id", "radio_reach", "spins"] if c in hist_presence.columns]
                hist_ref = hist_presence[hist_keep].drop_duplicates("song_id").rename(columns={"spins": "airplay_spins_7d"})
                entries = entries.merge(hist_ref, on="song_id", how="left")
            else:
                if "radio_reach" not in entries.columns:
                    entries["radio_reach"] = float("nan")
                entries["airplay_spins_7d"] = 0

            hist_pop = pd.DataFrame(
                cached_airplay_presence_at(AIR_REV, 28, str(meta["chart_date"])).get("rows") or []
            )
            if not hist_pop.empty and {"song_id", "spins"}.issubset(hist_pop.columns):
                hist_pop = hist_pop[hist_pop["song_id"].notna()].copy()
                hist_pop["song_id"] = hist_pop["song_id"].astype(int)
                hist_pop["spins"] = pd.to_numeric(hist_pop["spins"], errors="coerce").fillna(0)
                hist_pop = hist_pop.groupby("song_id", as_index=False)["spins"].sum()
                positive = hist_pop["spins"] > 0
                hist_pop["airplay_volume_index"] = 0.0
                if positive.any():
                    hist_pop.loc[positive, "airplay_volume_index"] = (
                        hist_pop.loc[positive, "spins"].rank(method="average", pct=True) * 100.0
                    )
                entries = entries.merge(
                    hist_pop[["song_id", "airplay_volume_index"]], on="song_id", how="left"
                )
                entries["airplay_volume_index"] = entries["airplay_volume_index"].fillna(0.0)
                entries["popularity"] = (
                    0.80 * entries["airplay_volume_index"] + 0.20 * _chart_popularity_bonus(entries)
                ).clip(lower=0.0, upper=100.0).round(1)
            else:
                entries["popularity"] = float("nan")
            if "airplay_spins_7d" in entries.columns:
                entries["airplay_spins_7d"] = pd.to_numeric(entries["airplay_spins_7d"], errors="coerce").fillna(0).astype(int)
            entries["heard"] = entries.get("heard", False).fillna(False).astype(bool)
            entries["status"] = entries.get("status", "Nie słuchałem").fillna("Nie słuchałem").astype(str)
            if "downloaded" not in entries.columns:
                entries["downloaded"] = False
            else:
                entries["downloaded"] = entries["downloaded"].fillna(False).astype(bool)
            entries["spotify"] = [spotify_search_url(a, t) for a, t in zip(entries.artist, entries.title)]
            entries["spotify_copy"] = entries["spotify"]
            entries["preview"] = "▶"
            for c in ["position", "previous_position", "reported_peak"]:
                if c in entries:
                    entries[c] = entries[c].map(position_sort_value).astype(int)

            archive_cols = [
                "song_id", "position", "artist", "title", "preview", "heard", "status", "downloaded", "spotify", "spotify_copy",
                "popularity", "familiarity", "momentum", "radio_reach", "airplay_spins_7d", "avg_position",
                "previous_position", "reported_weeks", "reported_peak", "note",
            ]
            archive_show = entries[[c for c in archive_cols if c in entries.columns]].copy()
            render_song_grid(
                archive_show,
                key=f"issue_grid_{int(issue_id)}",
                height=770,
                editable_state=True,
            )
            st.caption("Poprzednio/Tygodnie/Peak są uzupełniane z danych źródła, a gdy ich brakuje — z naszej zapisanej historii. Chart Score, Momentum i Śr. poz. są liczone do daty notowania; Zasięg 7d kończy się na tej samej dacie, jeśli mamy wtedy dane emisji. Status, Downloaded i notatka są Twoim obecnym stanem.")

elif view_key == "airplay":
    st.subheader("📡 Emisje")
    stations = cached_airplay_stations(AIR_REV, True)
    running = active_job() is not None

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
        all_coverage = cached_airplay_coverage(AIR_REV, tuple(sorted(all_station_ids)))
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
        range_coverage = cached_airplay_coverage(AIR_REV, tuple(sorted(selected_ids)), range_start.isoformat(), range_end.isoformat()) if selected_ids else {}
        ok_windows = int(range_coverage.get("ok_windows") or 0)
        coverage_pct = (100.0 * ok_windows / expected_windows) if expected_windows else 0.0
        per_station_expected = len(completed_windows_in_range(range_start, range_end)) if selected_ids else 0
        station_cov_rows = cached_airplay_station_coverage(AIR_REV, tuple(sorted(selected_ids)), range_start.isoformat(), range_end.isoformat()) if selected_ids else []
        reporting_station_count = sum(1 for r in station_cov_rows if int(r.get("plays") or 0) > 0)

        if not selected_ids:
            st.info("Wybierz przynajmniej jedną stację.")
            summary_rows = []
            air_rev = AIR_REV
        else:
            air_rev = AIR_REV
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
        if expected_windows and ok_windows < expected_windows:
            st.warning(
                f"Dane w tym zakresie są niepełne: zapisano {ok_windows} z {expected_windows} zakończonych bloków 2h "
                f"({coverage_pct:.0f}%). Ranking liczy tylko zapisane emisje. Około 20–30 utworów na stację/dzień "
                "zwykle oznacza, że mamy tylko jeden blok 2h, a nie całą dobę. Uzupełnienie 24h i backfill są w zakładce Dane."
            )
        if air.empty:
            st.info("Brak zapisanych emisji dla wybranych stacji i dat. Pobieranie bieżące i backfill są w zakładce Dane.")
        else:
            st.markdown("### 🔥 Najczęściej grane")
            r0, rstatus, rdl, r1, r2, r3 = st.columns([1.85, 1.0, .62, .66, .82, .62], vertical_alignment="bottom")
            airplay_query = r0.text_input(
                "Szukaj w Emisjach",
                placeholder="wykonawca lub tytuł",
                key="airplay_rank_search",
                help="Filtr jest wykonywany na wszystkich utworach w wybranym okresie, zanim zadziała limit Pokaż. Polskie znaki są ignorowane.",
            )
            airplay_selected_statuses = render_status_checkbox_filter(
                rstatus, key="airplay_status_filter", base_only=False
            )
            airplay_downloaded_choice = rdl.selectbox(
                "Downloaded", DOWNLOAD_FILTER_OPTIONS, index=0, key="airplay_downloaded_filter"
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
            ranked = with_notes(ranked)
            ranked = apply_status_filter(ranked, airplay_selected_statuses)
            ranked = apply_download_filter(ranked, airplay_downloaded_choice)
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
            # Standard parameters shown in every song table. Score only rows
            # that survived search/sort/limit, so a large airplay database does
            # not force compute_scores() across the whole catalogue. Zasięg 7d
            # is global: all active/reporting stations, independent of this filter.
            basic = cached_basic_song_metrics(
                CHART_REV, air_rev, tuple(sorted(int(x) for x in ranked["song_id"].tolist()))
            )
            if not basic.empty:
                ranked = ranked.merge(basic, on="song_id", how="left")
            source_cols = ["RMF", "ZET", "OLIA", "OLIS", "ESKA"]
            for src in source_cols:
                pos_col = f"{src}_pos"
                ranked[src] = ranked[pos_col].map(position_sort_value).astype(int) if pos_col in ranked.columns else 999

            ranked["preview"] = "▶"
            ranked["spotify"] = [spotify_search_url(a, t) for a, t in zip(ranked["artist"], ranked["title"])]
            ranked["spotify_copy"] = ranked["spotify"]
            air_cols = [
                "song_id", "spins", "artist", "title", "release_month", "preview", "heard", "status", "downloaded", "spotify", "spotify_copy",
                "popularity", "familiarity", "momentum", "radio_reach", "airplay_spins_7d", "avg_position",
                "stations_count", "radio_rotation", "radio_presence_period",
                "avg_per_day", "avg_station_day", "max_station_spins", "top_station", "last_play",
                "RMF", "RMF_weeks", "ZET", "ZET_weeks", "OLIA", "OLIA_weeks", "OLIS", "OLIS_weeks", "ESKA", "ESKA_weeks", "note",
            ]
            air_show = ranked[[c for c in air_cols if c in ranked.columns]].copy()
            station_key = "-".join(str(x) for x in selected_ids)
            render_song_grid(
                air_show,
                key=f"airplay_rank_{range_start}_{range_end}_{sort_mode}_{top_n}_{min_station_count}_{airplay_downloaded_choice}_{quote(','.join(sorted(airplay_selected_statuses)), safe='')}_{normalize(airplay_query)}_{station_key}",
                height=690,
                editable_state=True,
                source_layout="airplay",
                station_total=reporting_station_count,
                floating_hscroll=True,
                row_numbers=True,
                merge_select_mode=True,
            )

elif view_key == "library":
    st.subheader("🎵 Baza")
    library_rows = cached_radio_library_catalog(song_catalog_revision()).copy()
    if library_rows.empty:
        st.warning("Nie ma jeszcze utworów ze statusem Baza. W zakładce Dane → Synchronizacja bazy radia wklej eksport i uruchom synchronizację.")
    else:
        stations = cached_airplay_stations(AIR_REV, True)
        all_station_ids = [int(s["station_id"]) for s in stations]
        station_labels = {int(s["station_id"]): str(s["name"]) for s in stations}
        coverage_all = cached_airplay_coverage(AIR_REV, tuple(sorted(all_station_ids))) if all_station_ids else {}
        last_date = coverage_all.get("last_date")
        first_date = coverage_all.get("first_date")
        default_end = date.fromisoformat(str(last_date)) if last_date else date.today()
        earliest = date.fromisoformat(str(first_date)) if first_date else default_end - timedelta(days=6)

        bscope, bstations = st.columns([1, 2])
        library_station_scope = bscope.radio(
            "Stacje", ["Wszystkie stacje", "Wybrane stacje"], horizontal=True, key="library_station_scope"
        )
        if library_station_scope == "Wszystkie stacje":
            selected_ids = all_station_ids
            bstations.caption(f"Porównujemy bazę z {len(selected_ids)} aktywnymi stacjami.")
        else:
            selected_ids = bstations.multiselect(
                "Wybierz stacje",
                all_station_ids,
                default=all_station_ids[: min(8, len(all_station_ids))],
                format_func=lambda sid: station_labels.get(int(sid), str(sid)),
                key="library_station_multiselect",
            )
            selected_ids = [int(x) for x in selected_ids]

        range_start, range_end = render_airplay_range_picker(
            key_prefix="library_range_v1",
            default_end=default_end,
            earliest=earliest,
            default_preset="Ostatni tydzień",
        )
        air_rev = AIR_REV
        summary_rows = cached_airplay_summary(
            air_rev, tuple(sorted(selected_ids)), range_start.isoformat(), range_end.isoformat()
        ) if selected_ids else []
        air = pd.DataFrame(summary_rows)
        station_cov_rows = cached_airplay_station_coverage(AIR_REV, tuple(sorted(selected_ids)), range_start.isoformat(), range_end.isoformat()) if selected_ids else []
        reporting_station_count = sum(1 for r in station_cov_rows if int(r.get("plays") or 0) > 0)
        period_days = max(1, (range_end - range_start).days + 1)

        lib = library_rows.copy()
        lib["song_id"] = lib["song_id"].astype(int)
        # SQLite returns INTEGER 0/1. AG Grid's checkbox renderer expects real
        # booleans; leaving int64 here makes a stored 1 look unchecked.
        for state_col in ["heard", "downloaded"]:
            if state_col in lib.columns:
                lib[state_col] = lib[state_col].fillna(0).astype(bool)
        metric_ids = tuple(sorted(int(x) for x in lib["song_id"].tolist()))
        basic = cached_basic_song_metrics(CHART_REV, air_rev, metric_ids)
        if not basic.empty:
            lib = lib.merge(basic, on="song_id", how="left")

        air_keep = [
            "song_id", "spins", "stations_count", "max_station_spins", "top_station", "last_play"
        ]
        if not air.empty:
            lib = lib.merge(air[[c for c in air_keep if c in air.columns]], on="song_id", how="left")
        for col in ["spins", "stations_count", "max_station_spins"]:
            if col not in lib.columns:
                lib[col] = 0
            lib[col] = pd.to_numeric(lib[col], errors="coerce").fillna(0).astype(int)
        for col in ["top_station", "last_play"]:
            if col not in lib.columns:
                lib[col] = ""
            lib[col] = lib[col].fillna("").astype(str).replace("nan", "")
        for col in ["familiarity", "momentum", "radio_reach"]:
            if col not in lib.columns:
                lib[col] = 0.0
            lib[col] = pd.to_numeric(lib[col], errors="coerce").fillna(0.0)

        lib["avg_per_day"] = (lib["spins"] / period_days).round(1)
        lib["avg_station_day"] = (
            lib["spins"] / period_days / lib["stations_count"].clip(lower=1)
        ).round(2)
        lib["station_reach"] = (
            100.0 * lib["stations_count"] / reporting_station_count
        ).clip(upper=100).round(1) if reporting_station_count else 0.0
        lib["radio_rotation"] = (100.0 * lib["avg_station_day"] / 6.0).clip(upper=100).round(1)
        lib["radio_presence_period"] = (0.70 * lib["station_reach"] + 0.30 * lib["radio_rotation"]).round(1)
        lib["release_month"] = [
            release_month(rel, first) for rel, first in zip(
                lib["release_date"] if "release_date" in lib.columns else [""] * len(lib),
                lib["first_chart_date"] if "first_chart_date" in lib.columns else [""] * len(lib),
            )
        ]
        source_cols = ["RMF", "ZET", "OLIA", "OLIS", "ESKA"]
        for src in source_cols:
            pos_col = f"{src}_pos"
            lib[src] = lib[pos_col].map(position_sort_value).astype(int) if pos_col in lib.columns else 999
        lib["preview"] = "▶"
        lib["spotify"] = [spotify_search_url(a, t) for a, t in zip(lib["artist"], lib["title"])]
        lib["spotify_copy"] = lib["spotify"]

        render_compact_metrics([
            ("Utwory w bazie", len(lib)),
            ("Grane w okresie", int((lib["spins"] > 0).sum())),
            ("Niegrane w okresie", int((lib["spins"] == 0).sum())),
            ("Raportujące stacje", f"{reporting_station_count}/{len(selected_ids)}" if selected_ids else "—"),
        ])

        qcol, scol, dlcol, zerocol, sortcol, showcol = st.columns([1.95, 1.0, .62, .78, .92, .62], vertical_alignment="bottom")
        library_query = qcol.text_input(
            "Szukaj w Bazie", placeholder="wykonawca lub tytuł", key="library_search"
        )
        library_statuses = render_status_checkbox_filter(
            scol, key="library_status_filter", base_only=True
        )
        library_downloaded = dlcol.selectbox(
            "Downloaded", DOWNLOAD_FILTER_OPTIONS, index=0, key="library_downloaded_filter"
        )
        with zerocol:
            st.caption("Emisje")
            only_zero = st.checkbox("Tylko niegrane", key="library_only_zero")
        library_sort = sortcol.selectbox(
            "Sortuj",
            ["Status", "Popularity", "Emisje", "Zasięg", "Radio Presence", "Chart Score", "Momentum", "Śr. poz."],
            index=0, key="library_sort",
        )
        library_top = showcol.selectbox(
            "Pokaż", [100, 250, 500, "Wszystkie"], index=3, key="library_top"
        )

        view = apply_status_filter(lib, library_statuses)
        view = apply_download_filter(view, library_downloaded)
        if library_query.strip():
            view = filter_song_rows(view, library_query)
        if only_zero:
            view = view[view["spins"] == 0]
        if library_sort == "Popularity":
            view = view.sort_values(["popularity", "spins"], ascending=[False, False])
        elif library_sort == "Emisje":
            view = view.sort_values(["spins", "stations_count"], ascending=[False, False])
        elif library_sort == "Zasięg":
            view = view.sort_values(["station_reach", "spins"], ascending=[False, False])
        elif library_sort == "Radio Presence":
            view = view.sort_values(["radio_presence_period", "spins"], ascending=[False, False])
        elif library_sort == "Chart Score":
            view = view.sort_values(["familiarity", "spins"], ascending=[False, False])
        elif library_sort == "Momentum":
            view = view.sort_values(["momentum", "spins"], ascending=[False, False])
        elif library_sort == "Śr. poz.":
            view = view.sort_values(["avg_position", "spins"], ascending=[True, False], na_position="last")
        else:
            status_rank = {status: i for i, status in enumerate(STATUSES)}
            view = view.assign(_status_rank=view["status"].map(status_rank).fillna(999)).sort_values(
                ["_status_rank", "artist", "title"], ascending=[False, True, True]
            ).drop(columns=["_status_rank"])
        if library_top != "Wszystkie":
            view = view.head(int(library_top))
        view = view.reset_index(drop=True)

        library_cols = [
            "song_id", "spins", "artist", "title", "release_month", "preview", "heard", "status", "downloaded",
            "spotify", "spotify_copy", "popularity", "familiarity", "momentum", "radio_reach", "airplay_spins_7d", "avg_position",
            "stations_count", "radio_rotation", "radio_presence_period", "avg_per_day", "avg_station_day",
            "max_station_spins", "top_station", "last_play",
            "RMF", "RMF_weeks", "ZET", "ZET_weeks", "OLIA", "OLIA_weeks", "OLIS", "OLIS_weeks", "ESKA", "ESKA_weeks", "note",
        ]
        show = view[[c for c in library_cols if c in view.columns]].copy()
        station_key = "-".join(str(x) for x in selected_ids)
        render_song_grid(
            show,
            key=f"library_grid_{range_start}_{range_end}_{library_downloaded}_{quote(','.join(sorted(library_statuses)), safe='')}_{library_sort}_{library_top}_{int(only_zero)}_{normalize(library_query)}_{station_key}",
            height=700, editable_state=True, source_layout="airplay",
            station_total=reporting_station_count, floating_hscroll=True, row_numbers=True,
        )
        st.caption(
            "Baza pokazuje wszystkie utwory ze statusem Baza oraz Baza Hold, także gdy w wybranym okresie mają 0 emisji. "
            "Zasięg i Radio Presence odnoszą się do wybranego okresu; Zasięg 7d i Emisje 7d są globalne dla ostatnich 7 dni, a Popularity dla ostatnich 28 dni."
        )

elif view_key == "our_radio":
    st.subheader("📻 EMAUS")
    st.caption(
        "EMAUS jest trzymany osobno od monitoringu rynku. Przy skonfigurowanym Zetta2GO Scheduled = ostatni snapshot "
        "logu przed emisją (cutoff 23:59 dnia poprzedniego), a Played = live log Zetty odświeżany co minutę. "
        "Ręczny GSelector zostaje jako fallback i archiwum."
    )
    # st.tabs executes every tab body on every rerun. That made /EMAUS load the
    # timeline, comparison, song stats and import history before the user saw
    # the first screen. A segmented selector renders only the active subview.
    _bootstrap_local_station_seed_once()
    local_rev = local_station_revision()
    section = st.segmented_control(
        "Widok EMAUS",
        ["Scheduled", "Played", "Porównanie", "Utwory", "Import"],
        default="Scheduled",
        key="our_radio_section",
        label_visibility="collapsed",
    ) or "Scheduled"
    if section == "Scheduled":
        _render_local_timeline("schedule", "our_radio_schedule", local_rev)
    elif section == "Played":
        _render_local_timeline("played", "our_radio_played", local_rev)
    elif section == "Porównanie":
        _render_local_comparison(local_rev)
    elif section == "Utwory":
        _cached_local_station_song_links(catalog_revision())
        _render_local_song_stats(local_rev)
    elif section == "Import":
        _render_local_import(local_rev)

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

    with st.expander("🎵 Synchronizacja bazy radia", expanded=False):
        overview = radio_library_overview()
        bundled_seed = Path(__file__).resolve().parent / "data" / "radio_library_seed_20260825.tsv"
        expected_rows = 0
        expected_categories = {}
        if bundled_seed.exists():
            try:
                seed_rows, seed_meta = parse_radio_library_tsv(bundled_seed.read_text(encoding="utf-8-sig"))
                expected_rows = int(seed_meta.get("rows") or 0)
                expected_categories = dict(seed_meta.get("categories") or {})
            except Exception:
                pass
        render_compact_metrics([
            ("W bazie RadioCharts", overview.get("total", 0)),
            ("Oczekiwane z ostatniego eksportu", expected_rows or "—"),
            ("Downloaded", overview.get("downloaded", 0)),
            ("Hold", overview.get("hold", 0)),
            ("Seed", "OK" if str(overview.get("seed_marker", "")).startswith("rows=") else str(overview.get("seed_marker") or "—")[:24]),
        ])
        if expected_rows and int(overview.get("total") or 0) < expected_rows:
            st.warning(
                f"W aktywnych statusach Baza jest {overview.get('total', 0)} utworów, a ostatni dołączony eksport ma {expected_rows}. "
                "Wklej eksport poniżej i uruchom synchronizację; 0.3.27 naprawia też jednorazowy seed z 0.3.26."
            )
        elif expected_rows:
            st.success(f"Aktywne statusy Baza: {overview.get('total', 0)} utworów · ostatni dołączony eksport: {expected_rows} wierszy.")
        counts = overview.get("categories") or {}
        if counts:
            count_df = pd.DataFrame([
                {"Kategoria": code, "RadioCharts": int(counts.get(code, 0)), "Eksport": int(expected_categories.get(code, 0))}
                for code in RADIO_STATUS_BOTTOM_UP
            ])
            st.dataframe(count_df, hide_index=True, use_container_width=True, height=220)

        st.caption(
            "Wklej cały eksport TXT/TSV z nagłówkiem Active / Cat / Pack / Ver / Title / Artist / Album / Runtime. "
            "Synchronizacja dopasowuje istniejące utwory, dodaje brakujące, ustawia Baza <Cat> i Downloaded. Notatka zostaje."
        )
        radio_text = st.text_area(
            "Wklej eksport bazy radia",
            value="",
            height=220,
            key="radio_library_sync_text",
            placeholder="Active\tCat\tPack\tVer\tTitle\tArtist\tAlbum\tRuntime\nChecked\tR2\t...",
        )
        if radio_text.strip():
            try:
                preview_rows, preview_meta = parse_radio_library_tsv(radio_text)
            except Exception as exc:
                st.error(f"Nie udało się rozpoznać eksportu bazy radia: {type(exc).__name__}: {exc}")
            else:
                category_text = ", ".join(
                    f"{cat}: {count}" for cat, count in sorted((preview_meta.get("categories") or {}).items())
                )
                st.caption(
                    f"Rozpoznano **{preview_meta.get('rows', 0)}** utworów"
                    + (f" · {category_text}" if category_text else "")
                )
                unsupported = preview_meta.get("unsupported") or {}
                if unsupported:
                    st.warning("Pominięte nieznane kategorie: " + ", ".join(f"{k} ({v})" for k, v in sorted(unsupported.items())))
                if st.button("Synchronizuj z RadioCharts", type="primary", key="radio_library_sync_button"):
                    result = sync_radio_library_tsv(radio_text)
                    cached_song_catalog.clear()
                    cached_basic_song_metrics.clear()
                    st.success(
                        "Synchronizacja zakończona: "
                        f"{result.get('processed', 0)} przetworzonych · "
                        f"{result.get('added', 0)} nowych · "
                        f"{result.get('matched', 0)} dopasowanych · "
                        f"{result.get('status_updated', 0)} statusów zmienionych · "
                        f"{result.get('downloaded_marked', 0)} oznaczonych jako Downloaded."
                    )
                    st.rerun()

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


elif view_key == "settings":
    _render_settings()

else:
    st.markdown("## 📘 Manual RadioCharts")
    st.caption("Co pokazuje każda zakładka, jak czytać wskaźniki i jak odróżniać dane z list przebojów od realnych emisji radiowych.")

    with st.expander("1. Najkrótsza ścieżka pracy", expanded=False):
        st.markdown(
            """
1. **Dane** — sprawdź, czy źródła są świeże i czy backfill nie ma luk.
2. **Dashboard** — znajdź utwory warte odsłuchu; sortuj po Popularity, Chart Score, Momentum i Radio Presence.
3. **Utwór** — zobacz pełną historię pozycji, emisje, odsłuchaj i ustaw własny status/notatkę.
4. **Emisje** — sprawdź, co faktycznie grają stacje, jak szeroko i jak często.
5. **Baza** — oceń, czy utwory faktycznie trzymane w Twojej bibliotece nadal mają sens: widzisz też pozycje z zerową emisją w wybranym okresie.
6. **Notowania** — podejrzyj konkretny historyczny tydzień/listę bez mieszania go z bieżącym stanem.

**Status, Downloaded i Notatka są wspólne** dla wszystkich zakładek. To ten sam rekord utworu, niezależnie od tego, czy trafiłeś do niego z notowania czy z emisji. **Downloaded** oznacza, że utwór został już pobrany / dodany do lokalnej biblioteki. Kolumna **✓ (Przesłuchany)** jest tylko czytelnym wskaźnikiem: zaznacza się automatycznie dla każdego statusu poza **Nie słuchałem**.

W **Dane → Synchronizacja bazy radia** wklejasz eksport TSV/TXT z kategorią, tytułem i wykonawcą. RadioCharts dopasowuje istniejące utwory, dodaje brakujące, ustawia `Baza <Cat>` oraz zaznacza **Downloaded**. Nad polem wklejania widać liczbę utworów i rozkład kategorii, więc można od razu sprawdzić, czy synchronizacja faktycznie weszła.

W edytorze statusów, licząc od dołu, kolejność kategorii bazy to **CF1 → CF2 → R1 → R2 → G1 → G2 → SP1 → SP2 → NB → F3**, wyżej jest **Baza Hold**, a jeszcze wyżej analogiczne statusy **Candidate** w tej samej kolejności. Na górze pozostają **Watch, Słabe, Poza formatem, Nie słuchałem**. Stare `Candidate` i `CF Candidate` są migrowane do `CF1 Candidate`, `Ignore` do `Poza formatem`, a `Poza bazą` do `Baza Hold`.
            """
        )

    with st.expander("2. Dashboard — zakresy i filtry", expanded=False):
        st.markdown(
            """
**Okres wskaźników** określa, z jak długiej historii list przebojów liczymy Chart Score i Momentum. `Całość` najlepiej opisuje trwałą znajomość utworu; krótsze okresy są przydatne do analizowania świeżych zmian.

**W najnowszych notowaniach** oznacza: utwór znajduje się w **najnowszym zapisanym notowaniu przynajmniej jednego źródła** w danej grupie. To nie znaczy „pojawił się gdzieś w ostatnio pobranych danych”.

- **W najnowszych notowaniach** — dowolne z PL + UK/Billboard.
- **PL w najnowszych** — RMF, ZET, OLiA, OLiS lub ESKA.
- **Zagraniczne w najnowszych** — UK lub Billboard.
- **Cała historia** — również utwory, które już zeszły ze wszystkich najnowszych list.

Minimalne Chart Score/Momentum są tylko filtrami tabeli — nie zmieniają obliczeń. Pole **Szukaj w Dashboardzie** filtruje po wykonawcy i tytule, ignoruje polskie znaki i działa na całym aktualnym zakresie przed wyrenderowaniem tabeli. Filtr **Statusy** otwiera listę checkboxów — możesz zaznaczyć kilka statusów naraz; brak zaznaczeń oznacza wszystkie. Osobny filtr **Downloaded** ma wartości Any/Yes/No. Kolumna **✓ (Przesłuchany)** wynika automatycznie ze Statusu i nie jest niezależnie edytowana.

Widok **Kompaktowy** jest domyślny. Nad filtrami widzisz tylko licznik **Utwory (filtr / okres)**. Dawne kafle Current Familiar / Rising / Pokrycie źródeł zostały usunięte, bo te same informacje można uzyskać przez sortowanie i filtry tabeli.

**Śr. poz.** to zwykła średnia arytmetyczna z bieżących pozycji **RMF, ZET, ESKA, OLiA i OLiS**, ale tylko z tych list, na których utwór aktualnie występuje. To szybki skrót orientacyjny, nie osobny scoring.

**Standardowe parametry tabel utworów** to: **Popularity, Chart Score, Momentum, Zasięg 7d, Emisje 7d i Śr. poz.** Dashboard, Emisje, Notowania oraz jednowierszowy wycinek Emisji na karcie Utwór pokazują ten sam zestaw, gdy dla danego okresu mamy dane.

**Premiera** jest pokazywana jako `YYYY/MM`. Gdy baza ma dokładną datę wydania, miesiąc jest bez prefiksu. `~YYYY/MM` oznacza, że dokładnej daty nie mamy i pokazujemy miesiąc **pierwszego pojawienia się w naszych notowaniach**.
            """
        )

    with st.expander("3. Chart Score — historyczna siła na listach", expanded=False):
        st.markdown(
            """
Chart Score jest **pamięcią sukcesu na listach**, a nie wskaźnikiem „czy utwór jest gorący dzisiaj”. Po zejściu z listy ma spadać bardzo powoli.

Najpierw pozycja jest zamieniana na siłę 0–100 z uwzględnieniem długości listy. Dla każdego źródła Chart Score składa się z:

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

Przykład: wielki przebój po miesiącu bez obecności na liście nadal powinien mieć wysoki Chart Score. To, że **teraz** przestaje być grany/promowany, ma być widoczne przede wszystkim w Momentum i Radio Presence, nie przez gwałtowne „zapominanie”.
            """
        )

    with st.expander("4. Popularity — realna bieżąca popularność", expanded=False):
        st.markdown(
            """
**Popularity** ma odpowiadać na pytanie: *jak szeroko ten utwór jest teraz realnie eksponowany?* Nie jest historią list i nie zależy od zakresu dat ustawionego w tabeli.

Wynik 0–100 składa się z:
- **80% — wolumen emisji z ostatnich 28 dni**, liczony jako percentyl liczby emisji względem wszystkich utworów, które w tym oknie faktycznie zagrały;
- **20% — bonus chartowy** z bieżących pozycji. W tej części celowo większą wagę mają **OLiA 35% i OLiS 25%**, dalej RMF 20%, ZET 12%, ESKA 8%.

Dzięki temu gold, który nie siedzi już na listach, ale wciąż jest intensywnie grany przez wiele stacji, może mieć wysoki Popularity mimo niskiego Chart Score. Z kolei świeży utwór wysoko na OLiA/OLiS dostaje dodatkowy bonus, zanim zbuduje długą historię emisji.

Dla stabilnego Popularity najważniejsze jest kompletne **ostatnie 28 dni Emisji**. Backfill 3–6 miesięcy nie zmienia samego bieżącego Popularity, ale bardzo pomaga przy audycie Bazy i porównywaniu gold/recurrent/current w dłuższym okresie.
            """
        )

    with st.expander("5. Momentum — co dzieje się teraz na listach", expanded=False):
        st.markdown(
            """
Momentum jest celowo **chart-only**. Patrzy na zmianę siły pozycji w maksymalnie czterech ostatnich tygodniowych punktach danego źródła.

- około **50%** — stabilnie,
- **>65%** — wyraźny wzrost,
- **<40%** — spadek.

Po zejściu z listy stary trend szybko traci znaczenie: wynik jest dodatkowo wygaszany ze stałą ok. **2,5 tygodnia**. Dzięki temu utwór może mieć np. Chart Score 80%, ale Momentum 10% — czyli „wszyscy go znają, lecz obecnie nie rośnie na listach”.

Emisje radiowe nie są dodawane do Momentum.
            """
        )

    with st.expander("6. Radio Presence — szerokość + intensywność grania", expanded=False):
        st.markdown(
            """
Radio Presence opisuje **realną bieżącą obecność na antenach** i jest niezależne od list przebojów.

**Zasięg** = procent raportujących stacji, które zagrały utwór przynajmniej raz w aktualnie wybranym okresie. W tabeli obok procentu w nawiasie pokazujemy też liczbę takich stacji.

**Rotacja** = jak często utwór jest grany na stacjach, które go grają. Liczymy średnią `emisje / grająca stacja / dzień` i skalujemy ją tak, że:

- ok. **1 emisja/stację/dzień ≈ 17% rotacji** — typowy lekko rotowany gold,
- **3 emisje/stację/dzień ≈ 50%**,
- **6 lub więcej/stację/dzień = 100%** — bardzo mocna rotacja/current.

**Radio Presence = 70% Zasięgu + 30% Rotacji.**

Zasięg ma większą wagę, bo utwór obecny w 40 różnych stacjach jest innym sygnałem niż utwór grany bardzo często przez jedną stację. Rotacja powoduje jednak, że recurrent grany 7× dziennie nie wygląda tak samo jak gold grany 1× dziennie.

Na karcie Utwór/Dashboard domyślnie jest to sygnał z **ostatnich 7 dni**. W rankingu Emisji analogiczne parametry są liczone dla aktualnie wybranego zakresu dat.
            """
        )

    with st.expander("7. Emisje — znaczenie wszystkich parametrów", expanded=False):
        st.markdown(
            """
**Emisja** to jedno zapisane odtworzenie utworu przez jedną stację.

- **Emisje** — suma wszystkich odtworzeń ze wszystkich wybranych stacji w okresie.
- **Zasięg** — procent raportujących stacji, które zagrały utwór w wybranym okresie; w nawiasie liczba stacji, np. `46% (26)`.
- **Rotacja** — intensywność grania na stacjach, które grają utwór; 6+/stację/dzień = 100%.
- **Zasięg 7d** — prosty, wspólny sygnał: jaki procent wszystkich aktywnych **raportujących** stacji z ostatnich 7 dni zagrał utwór. Jest niezależny od wybranego zakresu Emisji.\n- **Emisje 7d** — bezwzględna liczba odtworzeń tego utworu w tym samym globalnym 7-dniowym oknie.
- **Radio Presence** — `70% zasięgu + 30% rotacji`; w tabeli Emisji wersja zakresowa odnosi się do aktualnie wybranych dat/stacji.
- **Emisje/dzień łącznie** — wszystkie emisje utworu / liczba dni kalendarzowych. **17 oznacza 17 odtworzeń dziennie łącznie w całej wybranej grupie stacji, nie 17 na każdej stacji.**
- **Śr./grającą stację/dzień** — emisje / dni / liczba stacji, które faktycznie zagrały utwór.
- **Max/stacja** — ile razy najaktywniejsza stacja zagrała utwór w całym wybranym okresie.
- **Najmocniejsza stacja** — stacja z największą liczbą emisji tego utworu.
- **Ostatnio** — ostatnia zapisana godzina emisji.

Zakres Emisji ma presety **Dzisiaj (1d) / ostatni tydzień / 2 tygodnie / miesiąc / 3 miesiące / pół roku / rok** oraz dokładne daty. Domyślny pozostaje **ostatni tydzień (7d)**. Preset tylko wstawia daty; ręczna zmiana dowolnej z nich automatycznie przełącza preset na **Własny zakres**. Szybkie zakresy kończą się na najnowszym dniu, dla którego mamy zapisane dane emisji.

Pole **Szukaj w Emisjach** filtruje **cały wybrany okres**, zanim zadziała limit `Pokaż 50/100/...`. Wyszukiwanie ignoruje polskie znaki. Szczegóły konkretnego nagrania otwierasz **dwuklikiem na tytule lub wykonawcy**. Pozycje RMF/ZET/OLiA/OLiS/ESKA są w Emisjach pokazywane kompaktowo razem z tygodniami, np. `#7 (5w)`.

W szerokich tabelach Dashboardu i Emisji poziomy scrollbar jest dodatkowo **przyklejony do dołu okna przeglądarki**, gdy tabela jest na ekranie. Jest zsynchronizowany z natywnym paskiem AG Grid.

Na karcie **Utwór** jest osobna sekcja **Emisje radiowe**, która ma taki sam wybór zakresu i pokazuje jeden wiersz w tym samym układzie co tabela Emisji. Możesz analizować **Wszystkie stacje** albo wybrać konkretne rozgłośnie; wybór stacji zmienia dane okresowe oraz szczegóły per stacja/dzień. Globalne **Zasięg 7d** i **Emisje 7d** pozostają wspólnym sygnałem 7-dniowym dla całej aktywnej sieci. Rozwijane **Szczegóły emisji per stacja i dzień** dodają tabelę stacji oraz niewielki wykres dzienny bez rozpychania całej karty.

W szczegółach jednego utworu:

- **Dni z emisją** — w ilu dniach konkretna stacja zagrała utwór przynajmniej raz,
- **Śr./aktywny dzień** — emisje tej stacji / tylko dni, w których ta stacja faktycznie go zagrała,
- **Pierwsza/Ostatnia emisja** — granice zapisanej historii w wybranym okresie.

**Stacja raportująca** = stacja, dla której mamy przynajmniej jedną zapisaną emisję w wybranym okresie. To ważne: stacja bez playlisty/RDS nie obniża sztucznie zasięgu, jeżeli została rozpoznana jako nieraportująca.
            """
        )

    with st.expander("8. Baza — audyt własnej biblioteki", expanded=False):
        st.markdown(
            """
Zakładka **Baza** nie jest rankingiem zewnętrznym. Jej punktem wyjścia są wszystkie utwory ze statusem `Baza <kategoria>` **oraz `Baza Hold`** — również te, których żadna obserwowana stacja nie zagrała w wybranym okresie. Hold zostaje widoczny właśnie po to, żeby można było sprawdzić, czy czegoś nie wycofałeś niesłusznie.

Możesz zmieniać zakres dat i stacje dokładnie jak w Emisjach, a następnie sortować m.in. po Emisjach, Zasięgu, Radio Presence, Chart Score, Momentum albo średniej pozycji. **Tylko niegrane** szybko pokazuje rzeczy obecne u Ciebie, ale nieobecne w monitorowanych stacjach w danym okresie.

Filtr statusu rozbija własną bazę na CF1/CF2/R1/R2/G1/G2/SP1/SP2/NB/F3. Dzięki temu można np. osobno sprawdzić, czy CF-y naprawdę mają szeroką i intensywną rotację, a goldy nadal pojawiają się wystarczająco często.
            """
        )

    with st.expander("9. Pokrycie emisji i bloki 2h", expanded=False):
        st.markdown(
            """
odSluchane udostępnia historię w **blokach po 2 godziny**. Pełna zakończona doba jednej stacji to **12 bloków**.

- **Pokrycie bloków 2h `X/Y`** — ile oczekiwanych bloków zakończyło się poprawnym pobraniem.
- **Bloki OK** — poprawnie sprawdzone okna.
- **Brakuje** — zakończone okna, których nie mamy.
- **Puste bloki** — serwis odpowiedział poprawnie, ale parser znalazł 0 emisji. To coś innego niż brak pobrania.

Ranking Emisji liczy tylko to, co faktycznie jest zapisane. Przy niepełnym pokryciu wyniki mogą być zaniżone.

Pobieranie, uzupełnianie 24h, backfill i zarządzanie stacjami są teraz w zakładce **Dane**.
            """
        )

    with st.expander("10. Utwór i identyfikacja między źródłami", expanded=False):
        st.markdown(
            """
RadioCharts utrzymuje **jeden wspólny rekord nagrania** dla notowań, emisji i Twojej warstwy redakcyjnej. RDS potrafi jednak zapisać ten sam numer z innym zestawem wykonawców, rokiem projektu albo długim kredytem gościnnym.

Od 1.1 system zapamiętuje aliasy po scaleniu i automatycznie łączy konserwatywne warianty na podstawie **charakterystycznego tytułu + powiązanego kredytu wykonawców**. Od 1.1.4 rozpoznaje też typowe listy gości dopisane w nawiasie bez słowa `Feat.` — np. `Nareszcie (Herbut & Zalia & Vito Bambino)`, `Tańczę (Igor Herbut, Zalia, Vito Bambino)` czy `Świt (Gośc.: …)`. Nadal osobno zostają warianty typu Remix/Live/Acoustic/Edit. Po scaleniu emisje, historia list, Status, Downloaded i Notatki zostają przy jednym rekordzie.

**Stary rekord nie jest „zapominany”.** Jego dokładny podpis `wykonawca + tytuł` trafia do tabeli aliasów, a stare `song_id` do tabeli przekierowań. Dlatego jeżeli za tydzień odSluchane znowu poda dokładnie tę samą starą nazwę, importer od razu przypnie emisję do rekordu głównego zamiast tworzyć nowy duplikat. Surowy tekst wykonawcy/tytułu przy samej emisji pozostaje zachowany.

Automat jest celowo konserwatywny: nie łączymy agresywnie wyłącznie po podobnym tytule, szczególnie dla krótkich nazw typu „Home” czy „Stay”. Przy pierwszym uruchomieniu 1.1.4 działa tylko wąski skan `song_alias_merge_v4` dla bezpiecznych guest-creditów; to nie jest pełny fuzzy-matcher całego katalogu.

Ręczny backup jest teraz w **Emisje**. W ostatniej kolumnie **Scal** zaznacz co najmniej dwa rekordy, a pod tabelą kliknij **Scal zaznaczone**. Pojawi się potwierdzenie z listą wybranych rekordów. RadioCharts sam zachowa jako rekord główny najlepiej udokumentowaną wersję (preferuje historię toplist, potem liczbę emisji), a pozostałe zapisze jako trwałe aliasy. Mechanizm scalania z karty Utwór został usunięty, bo przy jednym otwartym rekordzie trudno było ocenić, który wariant jest właściwy.

Wyszukiwarka Utwór pokazuje przede wszystkim utwory z notowań oraz te, którym nadałeś status/notatkę. Surowe, jednorazowe warianty RDS nie zaśmiecają selektora; nadal można je otworzyć bezpośrednio z Emisji.
            """
        )

    with st.expander("11. Format Fit — dlaczego został wycofany", expanded=False):
        st.markdown(
            """
**Format Fit nie jest już pokazywany.** Sama pozycja na RMF/ZET/ESKA/OLiA nie mówi wiarygodnie, czy nagranie pasuje do konkretnego Mainstream AC.

Przykład: utwór może być wielkim hitem w źródłach, a brzmieniowo być dance/CHR, rockiem lub inną estetyką niepasującą do Twojego formatu. Żeby uczciwie przywrócić Format Fit, potrzebowalibyśmy dodatkowych danych — np. ręcznych tagów formatu/soundcode, cech audio albo wytrenowania wyniku na Twoich realnych decyzjach programowych. Do tego czasu lepiej nie pokazywać precyzyjnie wyglądającego, ale mylącego procentu.
            """
        )

    with st.expander("12. Dane, backfill i logi", expanded=False):
        st.markdown(
            """
Zakładka **Dane** służy do całej obsługi pobierania: bieżących notowań, backfillu list oraz **backfillu Emisji / odSluchane**. Jest tu też diagnostyka **„Co dokładnie zostało pobrane — pokrycie per stacja”** z własnym zakresem dat. Tabela „Stan źródeł” pokazuje kadencję publikacji, najnowsze pobrane notowanie oraz datę, której co najmniej oczekujemy dzisiaj.

Backfill Emisji jest **wznawialny i odporny na duplikaty**. Jednostką kontrolną jest blok `stacja + data + 2h`; przed długim backfillem RadioCharts jednym zapytaniem wczytuje już poprawnie zapisane bloki i pomija je w pamięci. Możesz więc bezpiecznie poprosić o rok danych, nawet jeśli kilka miesięcy już masz — pobrane zostaną tylko brakujące lub stare, przedwcześnie zapisane bloki. Ponowne pobranie jednego bloku atomowo zastępuje jego zawartość, a unikalny klucz emisji dodatkowo chroni przed zdublowaniem pojedynczego odtworzenia.

Każdy nowy proces zapisuje pełny log w `/app/data/jobs/`. Nazwa zaczyna się od czasu uruchomienia:

`YYYY-MM-DD_HH-MM-SS_typ-procesu_jobid.log`

Dzięki temu pliki sortują się chronologicznie. JSON joba nadal ma osobny identyfikator i wskazuje właściwy `log_file`.

Worker sprawdza automatyczne źródła dwa razy dziennie — 07:30 i 20:30 czasu Europe/Warsaw. Nieudane pobranie nie usuwa ostatniego poprawnego notowania.
            """
        )

    with st.expander("13. Spotify, odsłuch i własna ocena", expanded=False):
        st.markdown(
            """
**▶ 30s** uruchamia podgląd Apple/iTunes w przyklejonym odtwarzaczu. **Spotify ↗** otwiera wyszukiwanie wykonawca + tytuł; w tabelach obsługa kliknięcia jest realizowana bezpiecznie przez AG Grid, a Ctrl/Cmd+klik i środkowy przycisk mogą otwierać wiele kart bez opuszczania bieżącego widoku. Kolumna **Udostępnij ↗** wyszukuje dokładny utwór przez iTunes i otwiera jego smart-link Songlink/Odesli; w razie braku trafienia wraca do wyszukiwania Spotify. Na karcie **Utwór** przycisk **OLiS wyróżnienia ↗** prowadzi do oficjalnej, przeszukiwalnej bazy ZPAV/OLiS ze Złotymi, Platynowymi i Diamentowymi Płytami.

Twoje pola **Status, Downloaded i Notatka** są warstwą redakcyjną i nie zmieniają automatycznych wskaźników. Notatka jest celowo ostatnią kolumną tabel, żeby nie zabierała miejsca najważniejszym danym liczbowym.
            """
        )


    with st.expander("14. EMAUS — Scheduled, Played i reconciliation", expanded=False):
        st.markdown(
            """
Zakładka **EMAUS** jest oddzielona od monitoringu rynku. **Scheduled** to snapshot planu wyeksportowany z GSelectora przed emisją, a **Played** to plik po reconciliation / zakończeniu dnia.

Importer przyjmuje obecny TSV/TXT, zachowuje wszystkie typy elementów (Song, jingle, audycje, podkłady, informacje, ETM-y, reklamy i pozostałe wpisy) oraz surowe pola wiersza. Wielodniowy eksport jest rozbijany na dni po znacznikach BOM. Ponowny import tego samego dnia tworzy nowy bieżący snapshot, ale starszy zostaje w bazie jako historia rewizji planu. W Scheduled/Played przycisk **Kolumny** pozwala dołożyć m.in. Mood, Opener, Timing, Content, Energy, Texture, Edit Code, Exact Time, Sound Code, Vocal i techniczne ID.

Tryb GSelectora **60+ minutes/hour** jest traktowany jako informacja o bilansie godziny, nie błąd. Przykładowo `08:62:47.3` zostaje przypisane do godziny 08 i pokazuje `Gap +02:47.3`; ostrzeżenie ⚠ jest zarezerwowane dla naprawdę uszkodzonych zapisów czasu.

**Porównanie** dopasowuje elementy przede wszystkim po stabilnym ID z eksportu, a gdy go brakuje — po typie/kategorii i nazwie. Pokazuje `OK`, `Przesunięte`, `Pominięte` oraz `Dodane`. Widok **Utwory** liczy rotację w wybranym zakresie: liczbę slotów/emisji, liczbę dni, średnią na dzień, maksimum dzienne i najczęstszą godzinę. Songi EMAUS są dodatkowo wiązane z canonical `song_id` RadioCharts, dlatego na karcie **Utwór** pojawia się osobna sekcja EMAUS z planem i faktycznymi emisjami.

Na etapie 1.2.1 import jest ręczny. Automatyczne pobieranie z udziału sieciowego może zostać dołożone bez zmiany schematu bazy, bo importer i model danych są już oddzielone od sposobu dostarczenia pliku.
            """
        )
