from __future__ import annotations

import html
import json
from datetime import date

import pandas as pd
import plotly.express as px
import streamlit as st
import streamlit.components.v1 as components

from radiocharts.build_info import BUILD_DATE, display_version
from radiocharts.collector import backfill_rmf, collect_current
from radiocharts.db import DB_PATH, init_db, latest_issues, update_note, upsert_issue
from radiocharts.metrics import compute_scores, song_history
from radiocharts.seed_demo import seed
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


def sortable_positions(frame: pd.DataFrame, cols: list[str]):
    """Keep missing positions below #1 when the user sorts ascending.

    Streamlit's native grid sorts nulls before integers in this case. We keep a
    large numeric sentinel underneath and format it as an em dash. The numeric
    backing value preserves sensible ascending rank sorting (#1, #2, ... , —).
    """
    out = frame.copy()
    formats = {}
    for col in cols:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce").fillna(9999).astype(int)
            formats[col] = lambda v: "—" if int(v) >= 9999 else str(int(v))
    return out.style.format(formats) if formats else out


st.title("📻 RadioCharts Research")
st.caption("Familiarity, momentum i format fit. Narzędzie wspiera odsłuch i ręczną decyzję — nie zastępuje jej.")

with st.sidebar:
    st.caption(f"Build: **{display_version()}**")
    if BUILD_DATE != "unknown":
        st.caption(f"Zbudowano: {BUILD_DATE}")

    st.subheader("Dane")
    st.caption(f"DB: {DB_PATH}")

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

    if st.button("Załaduj dane demonstracyjne RMF+ZET", use_container_width=True):
        seed()
        st.success("Załadowano.")
        st.rerun()

    st.divider()
    st.markdown("**Wagi Familiarity**")
    st.text("OLiA 30%\nRMF 25%\nZET 20%\nOLiS 15%\nESKA 10%")


df = compute_scores()
tab_dash, tab_song, tab_import, tab_about = st.tabs(["Dashboard", "Utwór", "Import", "Metodologia"])

with tab_dash:
    if df.empty:
        st.info("Baza jest pusta. Kliknij po lewej „Pobierz dane teraz” albo załaduj dane demonstracyjne.")
    else:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Utwory", len(df))
        c2.metric("Current Familiar ≥70%", int((df.familiarity >= 70).sum()))
        c3.metric("Rising ≥65%", int((df.momentum >= 65).sum()))
        c4.metric("Pokrycie źródeł", f"{df.coverage.max():.0f}%")
        st.caption("Pokrycie to suma wag źródeł, które mają już dane. Score jest normalizowany do dostępnych źródeł.")

        colf1, colf2, colf3 = st.columns(3)
        min_fam = colf1.slider("Min. Familiarity", 0, 100, 0, format="%d%%")
        min_mom = colf2.slider("Min. Momentum", 0, 100, 0, format="%d%%")
        only_unheard = colf3.checkbox("Tylko nieprzesłuchane")
        view = df[(df.familiarity >= min_fam) & (df.momentum >= min_mom)]
        if only_unheard:
            view = view[~view.heard]

        cols = [
            "artist", "title", "familiarity", "momentum", "format_fit", "recommendation",
            "RMF_pos", "RMF_weeks", "ZET_pos", "ZET_weeks", "OLIA_pos", "OLIA_weeks",
            "OLIS_pos", "OLIS_weeks", "ESKA_pos", "ESKA_weeks",
            "UK_pos", "UK_weeks", "BILLBOARD_pos", "BILLBOARD_weeks", "status",
        ]
        show = view[[c for c in cols if c in view.columns]]
        pos_cols = [c for c in show.columns if c.endswith("_pos")]
        st.dataframe(
            sortable_positions(show, pos_cols),
            hide_index=True,
            use_container_width=True,
            column_config=score_columns(),
        )

        st.subheader("🔥 Rising / do przesłuchania")
        rising = df.sort_values("momentum", ascending=False).head(12)
        rcols = ["artist", "title", "familiarity", "momentum", "format_fit", "recommendation"]
        st.dataframe(
            rising[rcols],
            hide_index=True,
            use_container_width=True,
            column_config=score_columns(),
        )

with tab_song:
    if df.empty:
        st.info("Najpierw dodaj dane.")
    else:
        labels = {f"{r.artist} — {r.title}": int(r.song_id) for r in df.itertuples()}
        label = st.selectbox("Utwór", list(labels.keys()))
        song_id = labels[label]
        row = df[df.song_id == song_id].iloc[0]
        a, b, c = st.columns(3)
        a.metric("Familiarity", f"{row.familiarity:.0f}%")
        b.metric("Momentum", f"{row.momentum:.0f}%")
        c.metric("Format Fit", f"{row.format_fit:.0f}%")
        st.write(f"**Rekomendacja:** {row.recommendation}")

        source_rows = []
        for src in ["OLIA", "RMF", "ZET", "OLIS", "ESKA", "UK", "BILLBOARD"]:
            source_rows.append({
                "Źródło": src,
                "Pozycja": row.get(f"{src}_pos"),
                "Tygodnie": row.get(f"{src}_weeks", 0),
                "Peak": row.get(f"{src}_peak"),
            })
        src_df = pd.DataFrame(source_rows)
        st.dataframe(sortable_positions(src_df, ["Pozycja", "Peak"]), hide_index=True, use_container_width=True)

        h = song_history(song_id)
        if not h.empty:
            fig = px.line(h, x="chart_date", y="position", color="source", markers=True, title="Historia pozycji")
            maxpos = max(20, int(h.position.max()))
            fig.update_yaxes(autorange="reversed", range=[maxpos + 3, 1], dtick=5)
            st.plotly_chart(fig, use_container_width=True)

        with st.form("note_form"):
            heard = st.checkbox("Przesłuchany", value=bool(row.heard))
            statuses = ["Nie słuchałem", "Ignore", "Watch", "Candidate", "Current", "Current Familiar", "Recurrent"]
            idx = statuses.index(row.status) if row.status in statuses else 0
            status = st.selectbox("Mój status", statuses, index=idx)
            note = st.text_area("Notatka", value=row.note or "")
            if st.form_submit_button("Zapisz"):
                update_note(song_id, heard, status, note)
                st.success("Zapisano")
                st.rerun()

with tab_import:
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
    st.caption("Automatyczny crawler ZET pozostaje wyłączony. Skopiuj tekst bieżącej listy ze strony Radia ZET i wklej poniżej; parser wyciągnie Top 20 lokalnie.")
    zet_text = st.text_area("Tekst strony/listy ZET", height=180, key="zet_paste")
    if st.button("Parsuj i zapisz ZET", use_container_width=True):
        try:
            issue = parse_zet_text(zet_text, fallback_date=chart_date)
            upsert_issue(issue["source"], issue["chart_date"], issue["issue_key"], issue["chart_size"], issue["entries"], issue.get("source_url"))
            st.success(f"Zaimportowano ZET: {len(issue['entries'])} pozycji z {issue['chart_date']}.")
            st.rerun()
        except Exception as exc:
            st.error(f"ZET: {type(exc).__name__}: {exc}")

with tab_about:
    st.markdown(
        """
### Wskaźniki
**Familiarity** łączy bieżącą siłę pozycji, peak, liczbę tygodni na liście i liczbę tygodni w Top 10. Źródła: OLiA 30% / RMF 25% / ZET 20% / OLiS 15% / ESKA 10%.

**Momentum** patrzy na zmianę znormalizowanej siły pozycji w ostatnich czterech tygodniach. 50% ≈ stabilnie, >65% = wyraźny wzrost, <40% = spadek.

**Format Fit** ma większy nacisk na RMF i ZET (40/35), bo odpowiada raczej na pytanie „czy ten hit przypomina nasz format?” niż „czy jest popularny wszędzie?”.

### Źródła w MVP
RMF jest pobierany automatycznie i ma backfill archiwalnych notowań. OLiA i OLiS są rozwijane po kliknięciu „zobacz pełną listę”, ESKA ma fallback przez Chromium. UK Official Singles Chart i Billboard Hot 100 są pobierane automatycznie jako dodatkowe sygnały trendu — nie wchodzą do wag Familiarity. ZET pozostaje importem ręcznym; w zakładce Import można wkleić tekst listy bezpośrednio.

### Ważne
Progi są celowo konfigurowalne. Po zebraniu historii skalibrujemy je na utworach, które sam oznaczysz jako Current / Current Familiar / Recurrent.
        """
    )
