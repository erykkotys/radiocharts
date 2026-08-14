from __future__ import annotations

import html
import json
import math
import re
import unicodedata
from datetime import date, datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.express as px
import streamlit as st
import streamlit.components.v1 as components
from st_aggrid import AgGrid, GridOptionsBuilder, JsCode

from radiocharts.build_info import BUILD_DATE, display_version
from radiocharts.db import DB_PATH, chart_revision, init_db, issue_entries, issue_entries_enriched, latest_issues, latest_source_checks, source_check_day_summary, list_issues, load_notes, update_note, upsert_issue
from radiocharts.job_manager import active_job, latest_job, start_job, stop_job
from radiocharts.metrics import compute_scores, song_history
from radiocharts.sources.eska import probe_eska
from radiocharts.sources.uk import probe_uk
from radiocharts.sources.billboard import probe_billboard
from radiocharts.sources.zet import parse_zet_text, probe_zet
from radiocharts.sources.imports import dataframe_to_issue, parse_tabular
from radiocharts.sources.olis import probe_olis
from radiocharts.sources.rmf import probe_rmf

st.set_page_config(page_title="RadioCharts Research", page_icon="📻", layout="wide")

# Czytelniejsza typografia oraz delikatnie jaśniejszy dark mode.
st.markdown(
    """
    <style>
      html { font-size: 20px; }
      [data-testid="stAppViewContainer"] { background: #1b2028; }
      .block-container, [data-testid="stMainBlockContainer"] { padding-top: 0.65rem !important; }
      [data-testid="stHeader"] { background: rgba(27, 32, 40, 0.94); }
      [data-testid="stSidebar"] { background: #222832; font-size: 1.02rem; }
      [data-testid="stMetricValue"] { font-size: 2.05rem; }
      [data-testid="stDataFrame"] { font-size: 1rem; }
      .stButton button, .stDownloadButton button { font-size: 1rem; }
      label, p, li { line-height: 1.42; }
      .rc-tabs { display:flex; gap:0; border-bottom:1px solid #4a5260; margin:0.2rem 0 1.1rem 0; overflow-x:auto; }
      .rc-tabs a { color:#cfd5df; text-decoration:none; padding:0.62rem 1.05rem; border:1px solid transparent; border-bottom:none; border-radius:8px 8px 0 0; white-space:nowrap; }
      .rc-tabs a:hover { background:#2a313d; color:#fff; }
      .rc-tabs a.active { background:#2b323e; color:#fff; border-color:#4a5260; border-bottom:1px solid #2b323e; margin-bottom:-1px; font-weight:650; }
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
            "Momentum", help="Trend: 50 ≈ stabilnie, >65 = wzrost.", format="%.0f%%", min_value=0.0, max_value=100.0
        ),
        "format_fit": st.column_config.ProgressColumn(
            "Format Fit", help="Dopasowanie do profilu z mocniejszą wagą RMF/ZET.", format="%.0f%%", min_value=0.0, max_value=100.0
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


def song_link(song_id: int, title: str | None = None) -> str:
    """Relative URL to the song detail view (compatible with LinkColumn)."""
    return f"?view=song&song={int(song_id)}"


@st.cache_data(show_spinner=False, max_entries=32)
def cached_scores(revision: str, as_of: str = "", lookback_days: int = 0) -> pd.DataFrame:
    # revision invalidates cache when chart data changes; timeframe arguments
    # let Dashboard and historical Notowania reuse their own cached calculations.
    return compute_scores(as_of=as_of or None, lookback_days=lookback_days or None)


def clear_score_cache() -> None:
    cached_scores.clear()


def source_health_frame() -> tuple[pd.DataFrame, list[str]]:
    """Day-level freshness: any successful fetch today is enough.

    A later failed scheduled/manual retry is useful diagnostic information, but
    it must not turn a source red after today's issue has already been stored.
    """
    sources = ["RMF", "ZET", "OLIA", "OLIS", "ESKA", "UK", "BILLBOARD"]
    issues = {str(x["source"]): x for x in latest_issues()}
    latest = {str(x["source"]): x for x in latest_source_checks()}
    daily = {str(x["source"]): x for x in source_check_day_summary()}
    tz = ZoneInfo("Europe/Warsaw")
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

        # When today's data was obtained successfully, show that successful
        # attempt instead of a later transient failure.
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
            "Status": status,
            "Najnowsze notowanie": str(issue.get("chart_date")) if issue else "—",
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
        ("data", "Dane"),
        ("import", "Import"),
        ("methodology", "Metodologia"),
    ]
    links = []
    for key, label in tabs:
        cls = "active" if key == current else ""
        extra = ""
        if key == "song" and st.query_params.get("song"):
            extra = f"&song={st.query_params.get('song')}"
        links.append(f'<a class="{cls}" href="?view={key}{extra}" target="_self">{label}</a>')
    st.markdown('<div class="rc-tabs">' + ''.join(links) + '</div>', unsafe_allow_html=True)



st.title("📻 RadioCharts Research")
st.caption("Familiarity, momentum i format fit. Narzędzie wspiera odsłuch i ręczną decyzję — nie zastępuje jej.")

with st.sidebar:
    st.caption(f"Build: **{display_version()}**")
    if BUILD_DATE != "unknown":
        st.caption(f"Zbudowano: {BUILD_DATE}")
    st.caption(f"DB: {DB_PATH}")
    st.divider()
    st.markdown("**Wagi Familiarity**")
    st.text("OLiA 30%\nRMF 25%\nZET 20%\nOLiS 15%\nESKA 10%")
    st.caption("Pobieranie, backfille i diagnostyka są w zakładce **Dane**.")



STATUSES = ["Nie słuchałem", "Ignore", "Watch", "Candidate", "Current", "Current Familiar", "Recurrent"]


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
        out["status"] = [str(notes_df.at[i, "status"]) if i in notes_df.index else "Nie słuchałem" for i in ids]
        out["note"] = [str(notes_df.at[i, "note"] or "") if i in notes_df.index else "" for i in ids]
    else:
        out["heard"] = False
        out["status"] = "Nie słuchałem"
        out["note"] = ""
    return out


REVISION = chart_revision()
df = with_notes(cached_scores(REVISION))


def spotify_search_url(artist: str, title: str) -> str:
    query = quote(f"{artist} {title}", safe="")
    return f"https://open.spotify.com/search/{query}"


def search_key(value: object) -> str:
    """Accent-insensitive Polish search key: ę=e, ł=l, ó=o, etc."""
    text = str(value or "").casefold().replace("ł", "l")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def render_live_song_search(frame: pd.DataFrame) -> None:
    """Client-side live search: no Enter/rerun and normal browser text editing."""
    rows = []
    for r in frame[["song_id", "artist", "title"]].itertuples(index=False):
        rows.append({
            "id": int(r.song_id),
            "artist": str(r.artist),
            "title": str(r.title),
            "key": search_key(f"{r.artist} {r.title}"),
            "spotify": spotify_search_url(str(r.artist), str(r.title)),
        })
    payload = json.dumps(rows, ensure_ascii=False).replace("<", "\\u003c")
    components.html(
        f"""
        <style>
          body {{ margin:0; font-family:system-ui,-apple-system,Segoe UI,sans-serif; color:#e7ebf0; background:transparent; }}
          #q {{ box-sizing:border-box; width:100%; padding:10px 12px; border-radius:7px; border:1px solid #596272; background:#202631; color:#fff; font-size:16px; outline:none; }}
          #q:focus {{ border-color:#8995a8; }}
          #hint {{ color:#aeb7c5; font-size:13px; margin:6px 0 8px; }}
          #results {{ max-height:330px; overflow:auto; border-top:1px solid #343c49; }}
          .row {{ display:flex; align-items:center; gap:10px; padding:8px 4px; border-bottom:1px solid #303744; }}
          .song {{ flex:1; min-width:0; color:#f3f5f7; text-decoration:none; }}
          .song:hover {{ text-decoration:underline; }}
          .artist {{ color:#aeb7c5; font-size:13px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
          .spot {{ color:#dbe2ea; text-decoration:none; padding:3px 7px; border:1px solid #4d5767; border-radius:6px; }}
          .empty {{ color:#aeb7c5; padding:10px 4px; }}
        </style>
        <input id="q" type="text" autocomplete="off" placeholder="Wykonawca lub tytuł — polskie znaki nie są wymagane">
        <div id="hint">Wyniki pojawiają się podczas pisania. Ctrl+A / Delete działają normalnie. Kliknięcie utworu otwiera szczegóły w nowej karcie.</div>
        <div id="results"></div>
        <script>
          const songs = {payload};
          const q = document.getElementById('q');
          const results = document.getElementById('results');
          function detailUrl(id) {{
            try {{
              const base = new URL(document.referrer);
              base.search = '?view=song&song=' + encodeURIComponent(id);
              return base.toString();
            }} catch(e) {{ return '?view=song&song=' + encodeURIComponent(id); }}
          }}
          function esc(s) {{ return String(s).replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c])); }}
          function render() {{
            const query = q.value.toLowerCase().replace(/ł/g,'l').normalize('NFD').replace(/[\u0300-\u036f]/g,'').replace(/[^a-z0-9]+/g,' ').trim();
            if (!query) {{ results.innerHTML = ''; return; }}
            const tokens = query.split(/\\s+/).filter(Boolean);
            const found = songs.filter(s => tokens.every(t => s.key.includes(t))).slice(0, 20);
            if (!found.length) {{ results.innerHTML = '<div class="empty">Brak wyników.</div>'; return; }}
            results.innerHTML = found.map(s => `<div class="row"><a class="song" target="_blank" rel="noopener" href="${{detailUrl(s.id)}}"><div>${{esc(s.title)}}</div><div class="artist">${{esc(s.artist)}}</div></a><a class="spot" target="_blank" rel="noopener" href="${{esc(s.spotify)}}">▶</a></div>`).join('');
          }}
          q.addEventListener('input', render);
          q.focus();
        </script>
        """,
        height=420,
        scrolling=False,
    )




DETAIL_RENDERER = JsCode("""
function(params) {
  const a = document.createElement('a');
  a.href = params.value;
  a.target = '_blank';
  a.rel = 'noopener';
  a.textContent = 'Otwórz ↗';
  a.style.color = '#cfe4ff';
  a.style.textDecoration = 'none';
  a.addEventListener('click', e => e.stopPropagation());
  return a;
}
""")

SPOTIFY_RENDERER = JsCode("""
function(params) {
  const a = document.createElement('a');
  a.href = params.value;
  a.target = '_blank';
  a.rel = 'noopener';
  a.textContent = 'Spotify ↗';
  a.style.color = '#d7f9df';
  a.style.textDecoration = 'none';
  a.addEventListener('click', e => e.stopPropagation());
  return a;
}
""")

PREVIEW_RENDERER = JsCode("""
function(params) {
  const btn = document.createElement('button');
  btn.textContent = '▶ 30s';
  btn.title = '30-sekundowy podgląd z katalogu iTunes/Apple. Kliknij ponownie, aby zatrzymać.';
  btn.style.cssText = 'cursor:pointer;border:1px solid #667085;border-radius:6px;background:#252c36;color:#eef2f6;padding:2px 7px;font-size:12px;';

  const resetButton = (b) => { if (b) b.textContent = '▶ 30s'; };
  const stopCurrent = () => {
    if (window.__rcPreviewAudio) {
      try { window.__rcPreviewAudio.pause(); window.__rcPreviewAudio.currentTime = 0; } catch(e) {}
      window.__rcPreviewAudio = null;
    }
    resetButton(window.__rcPreviewButton);
    window.__rcPreviewButton = null;
  };
  const norm = (x) => String(x || '').toLowerCase().replace(/ł/g,'l').normalize('NFD').replace(/[\u0300-\u036f]/g,'').replace(/[^a-z0-9]+/g,' ').trim();

  btn.addEventListener('click', function(ev) {
    ev.stopPropagation();
    if (window.__rcPreviewButton === btn && window.__rcPreviewAudio && !window.__rcPreviewAudio.paused) {
      stopCurrent();
      return;
    }
    stopCurrent();
    btn.textContent = '…';

    const artist = String(params.data.artist || '');
    const title = String(params.data.title || '');
    const cb = '__rcPreviewCB_' + Date.now() + '_' + Math.floor(Math.random()*1000000);
    const script = document.createElement('script');
    const cleanup = () => {
      try { delete window[cb]; } catch(e) {}
      try { script.remove(); } catch(e) {}
    };
    window[cb] = function(payload) {
      try {
        const results = (payload && payload.results ? payload.results : []).filter(x => x.previewUrl);
        const nt = norm(title), na = norm(artist);
        let best = null, bestScore = -1;
        for (const r of results) {
          const rt = norm(r.trackName), ra = norm(r.artistName);
          let score = 0;
          if (rt === nt) score += 10;
          if (rt.includes(nt) || nt.includes(rt)) score += 4;
          const artistTokens = na.split(' ').filter(x => x.length > 2);
          score += artistTokens.filter(t => ra.includes(t)).length;
          if (score > bestScore) { best = r; bestScore = score; }
        }
        if (!best) {
          btn.textContent = 'brak';
          setTimeout(() => resetButton(btn), 1600);
          cleanup();
          return;
        }
        const audio = new Audio(best.previewUrl);
        window.__rcPreviewAudio = audio;
        window.__rcPreviewButton = btn;
        btn.textContent = '■ stop';
        audio.onended = stopCurrent;
        audio.onerror = () => { stopCurrent(); btn.textContent='błąd'; setTimeout(() => resetButton(btn), 1600); };
        const p = audio.play();
        if (p && p.catch) p.catch(() => { stopCurrent(); btn.textContent='błąd'; setTimeout(() => resetButton(btn), 1600); });
      } finally {
        cleanup();
      }
    };
    script.onerror = function() { cleanup(); btn.textContent='błąd'; setTimeout(() => resetButton(btn), 1600); };
    const term = encodeURIComponent(artist + ' ' + title);
    script.src = 'https://itunes.apple.com/search?term=' + term + '&country=PL&media=music&entity=song&limit=5&callback=' + cb;
    document.body.appendChild(script);
  });
  return btn;
}
""")

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


def render_song_grid(
    frame: pd.DataFrame,
    *,
    key: str,
    height: int = 640,
    editable_state: bool = True,
) -> pd.DataFrame:
    """AG Grid table: whole-row highlight, status editing and inline 30s preview."""
    show = frame.copy()
    if show.empty:
        st.info("Brak utworów do pokazania.")
        return show
    if "preview" not in show.columns:
        show["preview"] = "▶"

    gb = GridOptionsBuilder.from_dataframe(show)
    gb.configure_default_column(resizable=True, sortable=True, filter=True, editable=False)
    gb.configure_selection(selection_mode="single", use_checkbox=False, suppressRowClickSelection=False)
    gb.configure_grid_options(rowHeight=36, animateRows=False)

    if "song_id" in show.columns:
        gb.configure_column("song_id", hide=True)
    if "artist" in show.columns:
        gb.configure_column("artist", "Wykonawca", minWidth=190, width=220)
    if "title" in show.columns:
        gb.configure_column("title", "Tytuł", minWidth=210, width=260)
    if "details" in show.columns:
        gb.configure_column("details", "Szczegóły", minWidth=95, width=105, sortable=False, filter=False, cellRenderer=DETAIL_RENDERER)
    if "spotify" in show.columns:
        gb.configure_column("spotify", "Spotify", minWidth=90, width=95, sortable=False, filter=False, cellRenderer=SPOTIFY_RENDERER)
    if "preview" in show.columns:
        gb.configure_column("preview", "Odsłuch", minWidth=80, width=88, sortable=False, filter=False, cellRenderer=PREVIEW_RENDERER)
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
    for col, label in [("familiarity", "Familiarity"), ("momentum", "Momentum"), ("format_fit", "Format Fit")]:
        if col in show.columns:
            gb.configure_column(col, label, width=115, minWidth=105, valueFormatter=PERCENT_FORMATTER)
    if "recommendation" in show.columns:
        gb.configure_column("recommendation", "Rekomendacja", minWidth=190, width=220)

    for col in [c for c in show.columns if c in {"RMF","ZET","OLIA","OLIS","ESKA","UK","BILLBOARD","position","previous_position","reported_peak"}]:
        gb.configure_column(col, valueFormatter=POSITION_FORMATTER, width=88, minWidth=78)
    if "position" in show.columns:
        gb.configure_column("position", "Pozycja", pinned="left", width=82, minWidth=76, valueFormatter=POSITION_FORMATTER)
    if "previous_position" in show.columns:
        gb.configure_column("previous_position", "Poprzednio", width=95, minWidth=90, valueFormatter=POSITION_FORMATTER)
    if "reported_weeks" in show.columns:
        gb.configure_column("reported_weeks", "Tygodnie", width=90, minWidth=84)
    if "reported_peak" in show.columns:
        gb.configure_column("reported_peak", "Peak", width=75, minWidth=70, valueFormatter=POSITION_FORMATTER)

    options = gb.build()
    options.pop("autoSizeStrategy", None)
    original = show[[c for c in ["song_id", "heard", "status"] if c in show.columns]].copy()

    response = AgGrid(
        show,
        gridOptions=options,
        height=height,
        theme="streamlit",
        allow_unsafe_jscode=True,
        enable_enterprise_modules=False,
        data_return_mode="AS_INPUT",
        update_on=["cellValueChanged"],
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

    if editable_state and {"song_id", "heard", "status"}.issubset(edited.columns) and not original.empty:
        before = original.set_index("song_id")
        notes_by_id = df.set_index("song_id")["note"].to_dict() if (not df.empty and "note" in df.columns) else {}
        changed = 0
        for r in edited[["song_id", "heard", "status"]].itertuples(index=False):
            try:
                sid = int(r.song_id)
            except Exception:
                continue
            if sid not in before.index:
                continue
            prev = before.loc[sid]
            if bool(r.heard) != bool(prev.heard) or str(r.status) != str(prev.status):
                update_note(sid, bool(r.heard), str(r.status), str(notes_by_id.get(sid, "") or ""))
                changed += 1
        if changed:
            st.toast(f"Zapisano status dla {changed} utworów.")
            st.rerun()
    return edited


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
    if running_now and st.button("⏹ Zatrzymaj proces", use_container_width=True, key=f"stop_{key_suffix}_{job.get('job_id')}"):
        stop_job(str(job["job_id"]))
        st.rerun()

    state_key = f"_rc_job_state_{key_suffix}"
    previous = st.session_state.get(state_key)
    st.session_state[state_key] = state
    if previous in {"running", "starting", "stopping"} and not running_now:
        st.rerun()


view_key = str(st.query_params.get("view", "dashboard"))
if view_key not in {"dashboard", "song", "archive", "data", "import", "methodology"}:
    view_key = "dashboard"
render_nav_tabs(view_key)


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
            st.caption("'Pobrano dziś' oznacza, że co najmniej jedna próba tego źródła zakończyła się dziś sukcesem. Późniejszy błąd nie unieważnia już pobranych danych.")

        period_map = {
            "1 tydz.": 7,
            "2 tyg.": 14,
            "4 tyg.": 28,
            "2 mies.": 61,
            "4 mies.": 122,
            "6 mies.": 183,
            "Całość": 0,
        }
        period_label = st.radio(
            "Okres obliczeń wskaźników",
            list(period_map),
            horizontal=True,
            index=len(period_map) - 1,
            help="Familiarity, Momentum i Format Fit są liczone ponownie tylko z obserwacji z wybranego okresu. W widokach okresowych nie używamy lifetime weeks/peak raportowanych przez źródła.",
        )
        lookback = int(period_map[period_label])
        period_df = df if lookback == 0 else with_notes(cached_scores(REVISION, lookback_days=lookback))
        if period_df.empty:
            st.info("Brak danych w wybranym okresie.")
        else:
            scope = st.radio(
                "Zakres Dashboardu",
                ["Wszystkie aktywne", "Polskie aktywne", "Zagraniczne aktywne", "Cała historia"],
                horizontal=True,
                index=0,
                help="Aktywne = utwór obecny w najnowszym notowaniu przynajmniej jednego wybranego źródła w tym okresie.",
            )
            base = period_df.copy()
            core_pos = [c for c in ["OLIA_pos", "RMF_pos", "ZET_pos", "OLIS_pos", "ESKA_pos"] if c in base.columns]
            foreign_pos = [c for c in ["UK_pos", "BILLBOARD_pos"] if c in base.columns]
            all_pos = core_pos + foreign_pos
            if scope == "Polskie aktywne" and core_pos:
                base = base[base[core_pos].notna().any(axis=1)]
            elif scope == "Zagraniczne aktywne" and foreign_pos:
                base = base[base[foreign_pos].notna().any(axis=1)]
            elif scope == "Wszystkie aktywne" and all_pos:
                base = base[base[all_pos].notna().any(axis=1)]

            colf1, colf2, colf3 = st.columns(3)
            min_fam = colf1.slider("Min. Familiarity", 0, 100, 0, format="%d%%")
            min_mom = colf2.slider("Min. Momentum", 0, 100, 0, format="%d%%")
            only_unheard = colf3.checkbox("Tylko nieprzesłuchane")
            view = base[(base.familiarity >= min_fam) & (base.momentum >= min_mom)].copy()
            if only_unheard:
                view = view[~view.heard]
            view = view.reset_index(drop=True)

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Utwory (filtr / okres)", f"{len(view)} / {len(period_df)}")
            c2.metric("Current Familiar ≥70%", f"{int((view.familiarity >= 70).sum())} / {int((period_df.familiarity >= 70).sum())}")
            c3.metric("Rising ≥65%", f"{int((view.momentum >= 65).sum())} / {int((period_df.momentum >= 65).sum())}")
            c4.metric("Pokrycie źródeł", f"{period_df.coverage.max():.0f}%")
            st.caption(f"Okres wskaźników: {period_label}. Cała baza zawiera obecnie {len(df)} utworów. Rising nie ma już osobnej tabeli — wystarczy sortować Momentum albo ustawić jego minimum.")

            view["details"] = [song_link(sid) for sid in view.song_id]
            view["spotify"] = [spotify_search_url(a, t) for a, t in zip(view.artist, view.title)]
            view["preview"] = "▶"
            view["heard"] = view["heard"].fillna(False).astype(bool)
            view["status"] = view["status"].fillna("Nie słuchałem").astype(str)

            cols = [
                "song_id", "artist", "title", "details", "preview", "spotify", "heard", "status",
                "familiarity", "momentum", "format_fit", "recommendation",
                "RMF_pos", "RMF_weeks", "ZET_pos", "ZET_weeks", "OLIA_pos", "OLIA_weeks",
                "OLIS_pos", "OLIS_weeks", "ESKA_pos", "ESKA_weeks",
                "UK_pos", "UK_weeks", "BILLBOARD_pos", "BILLBOARD_weeks",
            ]
            show = view[[c for c in cols if c in view.columns]].copy()
            pos_cols = [c for c in show.columns if c.endswith("_pos")]
            for col in pos_cols:
                show[col] = show[col].map(position_sort_value).astype(int)
            show = show.rename(columns={c: c.replace("_pos", "") for c in pos_cols})
            render_song_grid(show, key=f"dashboard_grid_{lookback}_{scope}", height=660, editable_state=True)
            st.caption("Kliknięcie zwykłej komórki zaznacza cały wiersz. Szczegóły otwierają nową kartę. Odsłuch = 30-sekundowy podgląd Apple/iTunes; Spotify pozostaje pełnym linkiem do wyszukania utworu.")

elif view_key == "song":
    if df.empty:
        st.info("Najpierw dodaj dane.")
    else:
        ordered = df.sort_values(["artist", "title"], key=lambda s: s.astype(str).str.casefold()).reset_index(drop=True)
        ids = [int(r.song_id) for r in ordered.itertuples()]
        requested = st.query_params.get("song")
        try:
            selected_id = int(requested) if requested is not None else ids[0]
        except (TypeError, ValueError):
            selected_id = ids[0]
        if selected_id not in ids:
            selected_id = ids[0]

        render_live_song_search(ordered)

        song_id = selected_id
        row = df[df.song_id == song_id].iloc[0]

        head1, head2 = st.columns([4, 1])
        with head1:
            st.subheader(f"{row.artist} — {row.title}")
        with head2:
            st.link_button("▶ Otwórz w Spotify", spotify_search_url(row.artist, row.title), use_container_width=True)

        a, b, c = st.columns(3)
        a.metric("Familiarity", f"{row.familiarity:.0f}%")
        b.metric("Momentum", f"{row.momentum:.0f}%")
        c.metric("Format Fit", f"{row.format_fit:.0f}%")
        st.write(f"**Rekomendacja:** {row.recommendation}")

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

        st.markdown("**Polska / źródła Familiarity**")
        st.dataframe(_source_frame(["OLIA", "RMF", "ZET", "OLIS", "ESKA"]), hide_index=True, use_container_width=True, height=215)
        st.markdown("**Sygnały międzynarodowe**")
        st.dataframe(_source_frame(["UK", "BILLBOARD"]), hide_index=True, use_container_width=True, height=120)
        st.caption("UK/Billboard są sygnałami pomocniczymi i nie zmieniają wag Familiarity. W 0.2.1 stare błędnie przypisane metadane Billboardu są jednorazowo czyszczone i odbudowywane z poprawionego parsera.")

        h = song_history(song_id)
        if not h.empty:
            available_sources = list(dict.fromkeys(h["source"].tolist()))
            default_sources = [x for x in ["RMF", "ZET", "OLIA", "OLIS", "ESKA"] if x in available_sources]
            if not default_sources:
                default_sources = available_sources[:4]
            selected_sources = st.multiselect("Źródła na wykresie", available_sources, default=default_sources, key=f"history_sources_{song_id}")
            hp = h[h["source"].isin(selected_sources)] if selected_sources else h.iloc[0:0]
            if not hp.empty:
                scale_mode = st.radio(
                    "Skala pozycji",
                    ["Nieliniowa — więcej miejsca dla Top 20", "Liniowa"],
                    horizontal=True,
                    index=0,
                    key=f"history_scale_{song_id}",
                )
                plot_df = hp.copy()
                maxpos = max(20, int(plot_df.position.max()))
                if scale_mode.startswith("Nieliniowa"):
                    plot_df["position_plot"] = plot_df["position"].astype(float).map(math.sqrt)
                    fig = px.line(plot_df, x="chart_date", y="position_plot", color="source", markers=True, title="Historia pozycji")
                    ticks = [x for x in [1, 2, 3, 5, 10, 20, 40, 60, 80, 100, 150, 200] if x <= maxpos]
                    if maxpos not in ticks:
                        ticks.append(maxpos)
                    fig.update_yaxes(
                        autorange="reversed",
                        range=[math.sqrt(maxpos + 3), 1],
                        tickmode="array",
                        tickvals=[math.sqrt(x) for x in ticks],
                        ticktext=[str(x) for x in ticks],
                        title="Pozycja (skala nieliniowa)",
                    )
                    fig.update_traces(customdata=plot_df[["position"]], hovertemplate="%{x|%Y-%m-%d}<br>Pozycja #%{customdata[0]}<extra></extra>")
                else:
                    fig = px.line(plot_df, x="chart_date", y="position", color="source", markers=True, title="Historia pozycji")
                    fig.update_yaxes(autorange="reversed", range=[maxpos + 3, 1], dtick=5, title="Pozycja")
                fig.update_layout(height=690, legend=dict(orientation="h", yanchor="top", y=-0.12, x=0), margin=dict(t=55,b=90))
                st.plotly_chart(fig, use_container_width=True)

        with st.form("note_form"):
            heard = st.checkbox("Przesłuchany", value=bool(row.heard))
            idx = STATUSES.index(row.status) if row.status in STATUSES else 0
            status = st.selectbox("Mój status", STATUSES, index=idx)
            note = st.text_area("Notatka", value=row.note or "")
            if st.form_submit_button("Zapisz"):
                update_note(song_id, heard, status, note)
                st.success("Zapisano")
                st.rerun()


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
                score_cols = ["song_id", "familiarity", "momentum", "format_fit", "recommendation"]
                entries = entries.drop(columns=[c for c in ["heard", "status"] if c in entries.columns]).merge(
                    historical_scores[score_cols + ["heard", "status"]],
                    on="song_id", how="left",
                )
            entries["heard"] = entries.get("heard", False).fillna(False).astype(bool)
            entries["status"] = entries.get("status", "Nie słuchałem").fillna("Nie słuchałem").astype(str)
            entries["spotify"] = [spotify_search_url(a, t) for a, t in zip(entries.artist, entries.title)]
            entries["details"] = [song_link(sid) for sid in entries.song_id]
            entries["preview"] = "▶"
            for c in ["position", "previous_position", "reported_peak"]:
                if c in entries:
                    entries[c] = entries[c].map(position_sort_value).astype(int)

            archive_cols = [
                "song_id", "position", "artist", "title", "details", "preview", "spotify",
                "previous_position", "reported_weeks", "reported_peak",
                "familiarity", "momentum", "format_fit", "status", "heard",
            ]
            archive_show = entries[[c for c in archive_cols if c in entries.columns]].copy()
            render_song_grid(
                archive_show,
                key=f"issue_grid_{int(issue_id)}",
                height=770,
                editable_state=True,
            )
            st.caption("Poprzednio/Tygodnie/Peak są uzupełniane z danych źródła, a gdy ich brakuje — z naszej zapisanej historii. Trzy wskaźniki są liczone historycznie: tylko z danych dostępnych do daty tego notowania. Status i ✓ są Twoim obecnym stanem i można je edytować.")

elif view_key == "data":
    st.subheader("⬇️ Dane i procesy")
    st.caption("Pobieranie działa w tle i można je zatrzymać. OLiA/OLiS wróciły do starszego, sprawdzonego mechanizmu renderowania/eksportu; UI pozostaje responsywne.")
    running = active_job() is not None

    st.markdown("### Bieżące notowania")
    if st.button("Pobierz wszystkie automatyczne źródła", disabled=running, type="primary", use_container_width=True):
        start_job("collect-all")
        st.rerun()

    auto_sources = ["RMF", "ZET", "OLIA", "OLIS", "ESKA", "UK", "BILLBOARD"]
    cols = st.columns(3)
    for idx, src in enumerate(auto_sources):
        if cols[idx % 3].button(f"Pobierz {src}", disabled=running, use_container_width=True, key=f"fetch_{src}"):
            start_job("collect-source", source=src)
            st.rerun()

    render_job_status_fragment("collect", "collect")

    with st.expander("Radio ZET — ręczny fallback", expanded=False):
        st.caption("ZET pobiera się teraz automatycznie. To pole zostaje jako awaryjny ręczny import, gdyby collector zawiódł.")
        st.link_button("Otwórz bieżącą Listę Radia ZET", "https://player.radiozet.pl/Lista-przebojow", use_container_width=True)
        zet_quick = st.text_area("Wklej tekst bieżącej listy ZET", height=150, key="zet_quick_paste")
        if st.button("Zapisz bieżący ZET", disabled=running, use_container_width=True, key="zet_quick_save"):
            try:
                issue = parse_zet_text(zet_quick, fallback_date=date.today())
                upsert_issue(issue["source"], issue["chart_date"], issue["issue_key"], issue["chart_size"], issue["entries"], issue.get("source_url"))
                st.success(f"Zaimportowano ZET: {len(issue['entries'])} pozycji z {issue['chart_date']}.")
                st.rerun()
            except Exception as exc:
                st.error(f"ZET: {type(exc).__name__}: {exc}")

    st.divider()
    st.markdown("### Backfille")
    st.caption("Wszystkie kontrolki są razem, a przebieg procesu jest bezpośrednio pod nimi i odświeża się automatycznie. Limity bezpieczeństwa odpowiadają maksymalnie ok. 5 lat historii (RMF 1300, ZET 1825, listy tygodniowe 260).")

    b1, b2, b3, b4 = st.columns(4)
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

    o1, o2 = st.columns(2)
    olia_count = o1.number_input("OLiA · tygodnie", min_value=2, max_value=260, value=12, step=1)
    olis_count = o2.number_input("OLiS · tygodnie", min_value=2, max_value=260, value=12, step=1)
    if o1.button("Backfill OLiA", disabled=running, use_container_width=True):
        start_job("backfill", source="OLIA", count=int(olia_count)); st.rerun()
    if o2.button("Backfill OLiS", disabled=running, use_container_width=True):
        start_job("backfill", source="OLIS", count=int(olis_count)); st.rerun()

    a1, a2, a3 = st.columns(3)
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

    with st.expander("Diagnostyka źródeł", expanded=False):
        diag_source = st.selectbox("Źródło", ["RMF", "ZET", "OLIA", "OLIS", "ESKA", "UK", "BILLBOARD"], key="diag_source")
        if st.button("Sprawdź odpowiedź", use_container_width=True):
            try:
                with st.spinner(f"Sprawdzam {diag_source}…"):
                    if diag_source == "RMF": diag = probe_rmf()
                    elif diag_source == "ZET": diag = probe_zet()
                    elif diag_source in ("OLIA", "OLIS"): diag = probe_olis(diag_source)
                    elif diag_source == "ESKA": diag = probe_eska()
                    elif diag_source == "UK": diag = probe_uk()
                    else: diag = probe_billboard()
                st.session_state["source_diag"] = diag
            except Exception as exc:
                st.session_state["source_diag"] = {"source": diag_source, "error": f"{type(exc).__name__}: {exc}"}
        if "source_diag" in st.session_state:
            copyable_json(st.session_state["source_diag"], "source")

    with st.expander("Ostatnie zapisane notowania", expanded=False):
        for item in latest_issues():
            st.caption(f"**{item['source']}** · {item['chart_date']} · {item['entries']} pozycji")

elif view_key == "import":
    st.subheader("Import notowania")
    st.write("Format minimalny: `position, artist, title`. Może też zawierać `release_date`.")
    source = st.selectbox("Źródło", ["ZET", "OLIA", "OLIS", "ESKA", "RMF", "UK", "BILLBOARD"])
    chart_date = st.date_input("Data notowania", value=date.today())
    issue_key = st.text_input("Id/notowanie (opcjonalne)", value="")
    chart_size = st.number_input("Rozmiar listy", min_value=1, max_value=500, value=100 if source in ("OLIA", "OLIS", "UK", "BILLBOARD") else 20)
    uploaded = st.file_uploader("CSV / JSON / XLSX", type=["csv", "json", "xlsx", "xls"])
    if uploaded:
        try:
            imp = parse_tabular(uploaded.getvalue(), uploaded.name)
            st.dataframe(imp.head(20), hide_index=True, use_container_width=True)
            if st.button("Importuj to notowanie"):
                issue = dataframe_to_issue(imp, source, chart_date.isoformat(), issue_key or None, int(chart_size))
                upsert_issue(issue["source"], issue["chart_date"], issue["issue_key"], issue["chart_size"], issue["entries"], f"manual:{uploaded.name}")
                st.success(f"Zaimportowano {len(issue['entries'])} pozycji.")
                st.rerun()
        except Exception as exc:
            st.error(str(exc))
    st.download_button(
        "Pobierz szablon CSV",
        "position,artist,title,release_date\n1,Artist,Song,2026-01-01\n",
        "chart_template.csv",
        "text/csv",
    )

    st.divider()
    st.subheader("Radio ZET — ręczne wklejenie")
    st.info("ZET pobiera się automatycznie; ręczne wklejenie zostaje jako fallback/import historyczny.")
    st.link_button("Otwórz Listę Przebojów Radia ZET", "https://player.radiozet.pl/Lista-przebojow")
    st.caption("Skopiuj tekst notowania ze strony ZET i wklej poniżej; parser wyciągnie Top 20 lokalnie.")
    zet_text = st.text_area("Tekst strony/listy ZET", height=180, key="zet_paste")
    if st.button("Parsuj i zapisz ZET", use_container_width=True):
        try:
            issue = parse_zet_text(zet_text, fallback_date=chart_date)
            upsert_issue(issue["source"], issue["chart_date"], issue["issue_key"], issue["chart_size"], issue["entries"], issue.get("source_url"))
            st.success(f"Zaimportowano ZET: {len(issue['entries'])} pozycji z {issue['chart_date']}.")
            st.rerun()
        except Exception as exc:
            st.error(f"ZET: {type(exc).__name__}: {exc}")


else:
    st.markdown(
        """
### Wskaźniki
**Familiarity** łączy bieżącą siłę pozycji, peak, liczbę tygodni na liście i liczbę tygodni w Top 10. Źródła: OLiA 30% / RMF 25% / ZET 20% / OLiS 15% / ESKA 10%.

**Momentum** patrzy na zmianę znormalizowanej siły pozycji w ostatnich czterech tygodniach. 50% ≈ stabilnie, >65% = wyraźny wzrost, <40% = spadek.

**Format Fit** ma większy nacisk na RMF i ZET (40/35), bo odpowiada raczej na pytanie „czy ten hit przypomina nasz format?” niż „czy jest popularny wszędzie?”.

### Bieżąca pozycja a historia
Kolumny `*_pos` pokazują wyłącznie najnowsze **poprawnie zapisane** notowanie danego źródła. Jeżeli utworu w nim nie ma, widzisz `—`. Dashboard osobno pokazuje, czy każde źródło zostało faktycznie sprawdzone dzisiaj; nieudane pobranie nie podmienia ostatnich dobrych danych. Starsze notowania pozostają w bazie i nadal są używane do obliczania tygodni, peaków, momentum i Familiarity.

### Automatyczne pobieranie
Worker sprawdza automatyczne źródła dwa razy dziennie, o 07:30 i 20:30 czasu Europe/Warsaw. Każda próba — także nieudana — jest zapisywana w stanie źródeł, więc widać czy dane były dzisiaj weryfikowane.

### Backfill
RMF ma pełny backfill po numerach notowań. UK Official Singles Chart i Billboard Hot 100 mają tygodniowy backfill po stabilnych adresach archiwalnych. `weeks/peak` dla UK i Billboard bierzemy z oficjalnych bieżących notowań, a backfill buduje przede wszystkim historię pozycji do Momentum. OLiA/OLiS mają eksperymentalny backfill przez przycisk poprzedniego tygodnia i oficjalny eksport CSV; nieudane tygodnie są pomijane. ZET ma automatyczny bieżący collector oraz eksperymentalny backfill po publicznych adresach archiwalnych. ESKA nadal wymaga osobnego mechanizmu archiwum.

### Wydajność
SQLite zostaje. Przy tej skali danych nie jest wąskim gardłem; dashboard cache'uje kosztowne agregacje do czasu zmiany bazy, a tabele nie używają już Pandas Styler.

### Spotify
MVP tworzy link do wyszukiwania `wykonawca + tytuł` w Spotify. Nie wymaga to konta deweloperskiego ani klucza API. Później możemy opcjonalnie dodać Spotify Web API i zapisywać bezpośredni `track_id`/ISRC.

### Ważne
Progi są celowo konfigurowalne. Po zebraniu historii skalibrujemy je na utworach, które sam oznaczysz jako Current / Current Familiar / Recurrent.
        """
    )
