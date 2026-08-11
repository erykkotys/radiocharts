from __future__ import annotations

import html
import json
from datetime import date
from urllib.parse import quote

import pandas as pd
import plotly.express as px
import streamlit as st
import streamlit.components.v1 as components

from radiocharts.build_info import BUILD_DATE, display_version
from radiocharts.collector import backfill_rmf, backfill_weekly_source, collect_current
from radiocharts.db import DB_PATH, db_revision, init_db, issue_entries, latest_issues, list_issues, update_note, upsert_issue
from radiocharts.metrics import compute_scores, song_history
from radiocharts.sources.eska import probe_eska
from radiocharts.sources.uk import probe_uk
from radiocharts.sources.billboard import probe_billboard
from radiocharts.sources.zet import parse_zet_text
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
    """Sortable display rank: #001..#100, missing values as ASCII hyphen so ascending sort puts them last."""
    try:
        if value is None or pd.isna(value):
            return "-"
        return f"#{int(value):03d}"
    except Exception:
        return "-"


def song_link(song_id: int, title: str | None = None) -> str:
    """Relative URL to the song detail view (compatible with LinkColumn)."""
    return f"?view=song&song={int(song_id)}"


@st.cache_data(show_spinner=False, max_entries=8)
def cached_scores(revision: str) -> pd.DataFrame:
    # revision is intentionally unused inside the function; it invalidates the
    # cache whenever chart data or user notes change.
    return compute_scores()


def clear_score_cache() -> None:
    cached_scores.clear()


def render_nav_tabs(current: str) -> None:
    tabs = [
        ("dashboard", "Dashboard"),
        ("song", "Utwór"),
        ("archive", "Archiwum"),
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

    st.subheader("Dane")
    st.caption(f"DB: {DB_PATH}")

    with st.expander("Aktualizacja danych", expanded=False):
        if st.button("↻ Pobierz dane teraz", use_container_width=True):
            try:
                with st.spinner("Pobieram RMF/ESKĘ/UK/Billboard i renderuję OLiA/OLiS w Chromium (to może potrwać kilkadziesiąt sekund)..."):
                    st.session_state["collect_result"] = collect_current()
                st.rerun()
            except Exception as exc:
                st.error(f"Błąd collectora: {exc}")

        if "collect_result" in st.session_state:
            for msg in st.session_state["collect_result"]:
                if msg.startswith("✅"):
                    st.success(msg)
                elif msg.startswith("⚠️"):
                    st.warning(msg)
                else:
                    st.info(msg)

    with st.expander("Backfill RMF"):
        st.caption("Pobiera historyczne notowania przez formularz archiwum RMF. Najpierw przetestuj 5; jeśli przejdzie, uruchom 130.")
        backfill_count = st.number_input("Liczba notowań", min_value=5, max_value=750, value=130, step=5)
        if st.button("Pobierz historię RMF", use_container_width=True):
            bar = st.progress(0.0, text="Startuję backfill...")
            last = st.empty()

            def _progress(done: int, total: int, message: str):
                bar.progress(done / total, text=f"RMF {done}/{total}")
                last.caption(message)

            try:
                msgs = backfill_rmf(int(backfill_count), progress_callback=_progress)
                st.session_state["backfill_result"] = {
                    "requested": int(backfill_count),
                    "ok": sum(": OK" in x for x in msgs),
                    "errors": [x for x in msgs if ": OK" not in x],
                    "last_messages": msgs[-20:],
                }
                st.success("Backfill zakończony.")
                st.rerun()
            except Exception as exc:
                st.error(f"Backfill RMF: {type(exc).__name__}: {exc}")
        if "backfill_result" in st.session_state:
            copyable_json(st.session_state["backfill_result"], "backfill")

    with st.expander("Backfill UK / Billboard"):
        st.caption("UK i Billboard zapisują oficjalne weeks/peak z bieżących notowań; backfill jest potrzebny głównie do pełnej historii pozycji i Momentum.")
        weekly_sources = st.multiselect("Źródła", ["UK", "BILLBOARD"], default=["UK", "BILLBOARD"], key="weekly_backfill_sources")
        weekly_count = st.number_input("Liczba tygodni", min_value=2, max_value=104, value=26, step=1, key="weekly_backfill_count")
        if st.button("Pobierz historię UK/Billboard", use_container_width=True):
            results = {}
            for src in weekly_sources:
                bar = st.progress(0.0, text=f"{src}: start...")
                last = st.empty()
                def _weekly_progress(done: int, total: int, message: str, _src=src):
                    bar.progress(done / total, text=f"{_src} {done}/{total}")
                    last.caption(message)
                try:
                    msgs = backfill_weekly_source(src, int(weekly_count), progress_callback=_weekly_progress)
                    results[src] = {
                        "requested": int(weekly_count),
                        "ok": sum(": OK" in x for x in msgs),
                        "errors": [x for x in msgs if ": OK" not in x],
                        "last_messages": msgs[-12:],
                    }
                except Exception as exc:
                    results[src] = {"error": f"{type(exc).__name__}: {exc}"}
            st.session_state["weekly_backfill_result"] = results
            st.rerun()
        if "weekly_backfill_result" in st.session_state:
            copyable_json(st.session_state["weekly_backfill_result"], "weekly-backfill")

    with st.expander("Diagnostyka źródeł"):
        diag_source = st.selectbox("Źródło", ["RMF", "OLIA", "OLIS", "ESKA", "UK", "BILLBOARD"], key="diag_source")
        if st.button("Sprawdź odpowiedź", use_container_width=True):
            try:
                with st.spinner(f"Sprawdzam {diag_source}..."):
                    if diag_source == "RMF":
                        diag = probe_rmf()
                    elif diag_source in ("OLIA", "OLIS"):
                        diag = probe_olis(diag_source)
                    elif diag_source == "ESKA":
                        diag = probe_eska()
                    elif diag_source == "UK":
                        diag = probe_uk()
                    else:
                        diag = probe_billboard()
                    st.session_state["source_diag"] = diag
            except Exception as exc:
                st.session_state["source_diag"] = {
                    "source": diag_source,
                    "error": f"{type(exc).__name__}: {exc}",
                }
        if "source_diag" in st.session_state:
            copyable_json(st.session_state["source_diag"], "source")

    with st.expander("Ostatnie zapisane notowania"):
        issues = latest_issues()
        if not issues:
            st.caption("Brak danych.")
        else:
            for item in issues:
                st.caption(f"**{item['source']}** · {item['chart_date']} · {item['entries']} pozycji")

    st.divider()
    st.markdown("**Wagi Familiarity**")
    st.text("OLiA 30%\nRMF 25%\nZET 20%\nOLiS 15%\nESKA 10%")



df = cached_scores(db_revision())
STATUSES = ["Nie słuchałem", "Ignore", "Watch", "Candidate", "Current", "Current Familiar", "Recurrent"]


def spotify_search_url(artist: str, title: str) -> str:
    query = quote(f"{artist} {title}", safe="")
    return f"https://open.spotify.com/search/{query}"


view_key = str(st.query_params.get("view", "dashboard"))
if view_key not in {"dashboard", "song", "archive", "import", "methodology"}:
    view_key = "dashboard"
render_nav_tabs(view_key)


if view_key == "dashboard":
    if df.empty:
        st.info("Baza jest pusta. Kliknij po lewej „Pobierz dane teraz”.")
    else:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Utwory", len(df))
        c2.metric("Current Familiar ≥70%", int((df.familiarity >= 70).sum()))
        c3.metric("Rising ≥65%", int((df.momentum >= 65).sum()))
        c4.metric("Pokrycie źródeł", f"{df.coverage.max():.0f}%")
        st.caption("Pozycja źródła pokazuje tylko najnowsze notowanie. Historia nadal liczy tygodnie, peak, momentum i familiarity.")

        colf1, colf2, colf3 = st.columns(3)
        min_fam = colf1.slider("Min. Familiarity", 0, 100, 0, format="%d%%")
        min_mom = colf2.slider("Min. Momentum", 0, 100, 0, format="%d%%")
        only_unheard = colf3.checkbox("Tylko nieprzesłuchane")
        view = df[(df.familiarity >= min_fam) & (df.momentum >= min_mom)].copy()
        if only_unheard:
            view = view[~view.heard]
        view = view.reset_index(drop=True)
        view["spotify"] = [spotify_search_url(a, t) for a, t in zip(view.artist, view.title)]
        view["details"] = [song_link(sid) for sid in view.song_id]
        view["heard"] = view["heard"].fillna(False).astype(bool)
        view["status"] = view["status"].fillna("Nie słuchałem").astype(str)

        cols = [
            "song_id", "artist", "title", "details", "spotify", "heard", "status",
            "familiarity", "momentum", "format_fit", "recommendation",
            "RMF_pos", "RMF_weeks", "ZET_pos", "ZET_weeks", "OLIA_pos", "OLIA_weeks",
            "OLIS_pos", "OLIS_weeks", "ESKA_pos", "ESKA_weeks",
            "UK_pos", "UK_weeks", "BILLBOARD_pos", "BILLBOARD_weeks",
        ]
        show = view[[c for c in cols if c in view.columns]].copy()
        pos_cols = [c for c in show.columns if c.endswith("_pos")]
        for col in pos_cols:
            show[col] = show[col].map(position_display)

        column_cfg = score_columns()
        column_cfg.update({
            "song_id": None,
            "artist": st.column_config.TextColumn("Wykonawca", width="medium"),
            "title": st.column_config.TextColumn("Tytuł", width="large"),
            "details": st.column_config.LinkColumn("Szczegóły", display_text="Otwórz", width="small", help="Otwórz kartę utworu."),
            "spotify": st.column_config.LinkColumn("Spotify", display_text="▶", width="small"),
            "heard": st.column_config.CheckboxColumn("✓", help="Przesłuchany", width="small"),
            "status": st.column_config.SelectboxColumn("Status", options=STATUSES, required=True, width="medium"),
            "recommendation": st.column_config.TextColumn("Rekomendacja", width="medium"),
        })
        for col in pos_cols:
            column_cfg[col] = st.column_config.TextColumn(col.replace("_pos", ""), width="small")

        editable = {"heard", "status"}
        disabled_cols = [c for c in show.columns if c not in editable]
        original = show[["song_id", "heard", "status"]].copy().set_index("song_id")
        edited = st.data_editor(
            show,
            hide_index=True,
            use_container_width=True,
            disabled=disabled_cols,
            column_config=column_cfg,
            key="dashboard_editor",
            height=640,
        )

        # Save status/heard immediately after an edit; no separate Save button.
        changed = 0
        notes_by_id = df.set_index("song_id")["note"].to_dict()
        for r in edited[["song_id", "heard", "status"]].itertuples(index=False):
            sid = int(r.song_id)
            if sid not in original.index:
                continue
            before = original.loc[sid]
            if bool(r.heard) != bool(before.heard) or str(r.status) != str(before.status):
                update_note(sid, bool(r.heard), str(r.status), str(notes_by_id.get(sid, "") or ""))
                changed += 1
        if changed:
            clear_score_cache()
            st.toast(f"Zapisano status dla {changed} utworów.")
            st.rerun()

        st.caption("Kolumna Szczegóły otwiera kartę utworu. Status i ✓ zapisują się od razu. Pozycje są z najnowszych notowań; historia służy do tygodni, peaków i trendu.")

        st.subheader("🔥 Rising / do przesłuchania")
        rising = df.sort_values("momentum", ascending=False).head(12).copy()
        rising["spotify"] = [spotify_search_url(a, t) for a, t in zip(rising.artist, rising.title)]
        rising["details"] = [song_link(sid) for sid in rising.song_id]
        rcols = ["artist", "title", "details", "spotify", "familiarity", "momentum", "format_fit", "recommendation"]
        st.dataframe(
            rising[rcols],
            hide_index=True,
            use_container_width=True,
            column_config={
                **score_columns(),
                "title": st.column_config.TextColumn("Tytuł", width="large"),
                "details": st.column_config.LinkColumn("Szczegóły", display_text="Otwórz", width="small"),
                "spotify": st.column_config.LinkColumn("Spotify", display_text="▶", width="small"),
            },
        )


elif view_key == "song":
    if df.empty:
        st.info("Najpierw dodaj dane.")
    else:
        ordered = df.sort_values(["artist", "title"], key=lambda s: s.astype(str).str.casefold()).reset_index(drop=True)
        labels = [f"{r.artist} — {r.title}" for r in ordered.itertuples()]
        ids = [int(r.song_id) for r in ordered.itertuples()]
        requested = st.query_params.get("song")
        try:
            selected_id = int(requested) if requested is not None else ids[0]
        except (TypeError, ValueError):
            selected_id = ids[0]
        index = ids.index(selected_id) if selected_id in ids else 0
        label = st.selectbox("Utwór", labels, index=index, key="song_picker")
        song_id = ids[labels.index(label)]
        if str(st.query_params.get("song", "")) != str(song_id):
            st.query_params["view"] = "song"
            st.query_params["song"] = str(song_id)
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
                fig = px.line(hp, x="chart_date", y="position", color="source", markers=True, title="Historia pozycji")
                maxpos = max(20, int(hp.position.max()))
                fig.update_yaxes(autorange="reversed", range=[maxpos + 3, 1], dtick=5)
                fig.update_layout(height=520, legend=dict(orientation="h", yanchor="top", y=-0.16, x=0))
                st.plotly_chart(fig, use_container_width=True)

        with st.form("note_form"):
            heard = st.checkbox("Przesłuchany", value=bool(row.heard))
            idx = STATUSES.index(row.status) if row.status in STATUSES else 0
            status = st.selectbox("Mój status", STATUSES, index=idx)
            note = st.text_area("Notatka", value=row.note or "")
            if st.form_submit_button("Zapisz"):
                update_note(song_id, heard, status, note)
                clear_score_cache()
                st.success("Zapisano")
                st.rerun()


elif view_key == "archive":
    st.subheader("📚 Archiwum notowań")
    all_issues = list_issues(limit=5000)
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
        archive_limit = st.selectbox("Pokaż pozycji", [20, 40, 100], index=0, key="archive_limit")
        st.caption(f"{meta['source']} · {meta['chart_date']} · zapisano {meta['entries']} pozycji")
        entries = pd.DataFrame(issue_entries(int(issue_id)))
        if not entries.empty:
            total_entries = len(entries)
            entries = entries.head(int(archive_limit)).copy()
            if total_entries > len(entries):
                st.caption(f"Pokazuję pierwsze {len(entries)} z {total_entries} pozycji.")
            entries["spotify"] = [spotify_search_url(a, t) for a, t in zip(entries.artist, entries.title)]
            entries["details"] = [song_link(sid) for sid in entries.song_id]
            for c in ["position", "previous_position", "reported_peak"]:
                if c in entries:
                    entries[c] = entries[c].map(position_display)
            archive_cols = ["position", "artist", "title", "details", "spotify", "previous_position", "reported_weeks", "reported_peak"]
            archive_show = entries[archive_cols]
            st.dataframe(
                archive_show,
                hide_index=True,
                use_container_width=True,
                column_config={
                    "position": st.column_config.TextColumn("Pozycja", width="small"),
                    "title": st.column_config.TextColumn("Tytuł", width="large"),
                    "details": st.column_config.LinkColumn("Szczegóły", display_text="Otwórz", width="small"),
                    "spotify": st.column_config.LinkColumn("Spotify", display_text="▶", width="small"),
                    "previous_position": st.column_config.TextColumn("Poprzednio", width="small"),
                    "reported_weeks": st.column_config.NumberColumn("Tygodnie"),
                    "reported_peak": st.column_config.TextColumn("Peak", width="small"),
                },
            )
            if src == "BILLBOARD":
                st.caption("Starsze wpisy Billboard sprzed 0.2.1 mogą mieć puste LW/Weeks/Peak do czasu ponownego pobrania danego tygodnia; błędne wartości zostały celowo wyczyszczone.")


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
    st.warning("ZET nie pobiera się automatycznie. Po usunięciu danych demonstracyjnych baza ZET pozostaje pusta, dopóki nie wkleisz prawdziwego notowania tutaj.")
    st.link_button("Otwórz Listę Przebojów Radia ZET", "https://player.radiozet.pl/Lista-przebojow")
    st.caption("Skopiuj tekst bieżącego notowania ze strony ZET i wklej poniżej; parser wyciągnie Top 20 lokalnie. Automatyczny crawler pozostaje wyłączony.")
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
Kolumny `*_pos` pokazują wyłącznie najnowsze zapisane notowanie danego źródła. Jeżeli utworu w nim nie ma, widzisz `—`. Starsze notowania pozostają w bazie i nadal są używane do obliczania tygodni, peaków, momentum i Familiarity.

### Backfill
RMF ma pełny backfill po numerach notowań. UK Official Singles Chart i Billboard Hot 100 mają tygodniowy backfill po stabilnych adresach archiwalnych. `weeks/peak` dla UK i Billboard bierzemy z oficjalnych bieżących notowań, a backfill buduje przede wszystkim historię pozycji do Momentum. OLiA/OLiS oraz ESKA wymagają osobnego mechanizmu nawigacji po ich archiwach.

### Wydajność
SQLite zostaje. Przy tej skali danych nie jest wąskim gardłem; dashboard cache'uje kosztowne agregacje do czasu zmiany bazy, a tabele nie używają już Pandas Styler.

### Spotify
MVP tworzy link do wyszukiwania `wykonawca + tytuł` w Spotify. Nie wymaga to konta deweloperskiego ani klucza API. Później możemy opcjonalnie dodać Spotify Web API i zapisywać bezpośredni `track_id`/ISRC.

### Ważne
Progi są celowo konfigurowalne. Po zebraniu historii skalibrujemy je na utworach, które sam oznaczysz jako Current / Current Familiar / Recurrent.
        """
    )
