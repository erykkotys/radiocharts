from __future__ import annotations

import os
import json
from datetime import date
from pathlib import Path
import pandas as pd
import plotly.express as px
import streamlit as st

from radiocharts.collector import collect_current
from radiocharts.build_info import VERSION, GIT_SHA, BUILD_DATE, display_version
from radiocharts.sources.rmf import probe_rmf
from radiocharts.db import init_db, upsert_issue, update_note, DB_PATH
from radiocharts.metrics import compute_scores, song_history
from radiocharts.sources.imports import parse_tabular, dataframe_to_issue
from radiocharts.seed_demo import seed

st.set_page_config(page_title="RadioCharts Research", page_icon="📻", layout="wide")

# Delikatnie większa typografia niż domyślna w Streamlit.
# Używamy rem, więc powiększenie zachowuje proporcje nagłówków i widgetów.
st.markdown(
    """
    <style>
      html { font-size: 18px; }
      [data-testid="stSidebar"] { font-size: 1rem; }
      [data-testid="stMetricValue"] { font-size: 2rem; }
      div[data-testid="stDataFrame"] { font-size: 1rem; }
      .stButton button, .stDownloadButton button { font-size: 1rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

init_db()

st.title("📻 RadioCharts Research")
st.caption("MVP: familiarity, momentum i format fit. Wynik wspiera odsłuch i ręczną decyzję — nie zastępuje jej.")

with st.sidebar:
    st.caption(f"Build: **{display_version()}**")
    if BUILD_DATE != "unknown":
        st.caption(f"Zbudowano: {BUILD_DATE}")
    st.subheader("Dane")
    st.caption(f"DB: {DB_PATH}")
    if st.button("↻ Pobierz RMF teraz", use_container_width=True):
        try:
            with st.spinner("Pobieram..."):
                msgs = collect_current()
            st.success("\n".join(msgs) or "Brak zmian")
            st.rerun()
        except Exception as e:
            st.error(f"Błąd: {e}")
    with st.expander("Diagnostyka RMF"):
        st.caption("Pokazuje, co kontener faktycznie otrzymuje z rmf.fm. Nie zapisuje danych.")
        if st.button("Sprawdź odpowiedź RMF", use_container_width=True):
            try:
                with st.spinner("Sprawdzam RMF..."):
                    st.session_state["rmf_diag"] = probe_rmf()
            except Exception as e:
                st.error(f"Diagnostyka RMF: {type(e).__name__}: {e}")
        if "rmf_diag" in st.session_state:
            diag_text = json.dumps(st.session_state["rmf_diag"], ensure_ascii=False, indent=2)
            st.code(diag_text, language="json")
            st.caption("Kliknij ikonę kopiowania w prawym górnym rogu bloku diagnostyki.")
    if st.button("Załaduj dane demonstracyjne RMF+ZET", use_container_width=True):
        seed(); st.success("Załadowano."); st.rerun()
    st.divider()
    st.markdown("**Wagi Familiarity**")
    st.text("OLiA 30%\nRMF 25%\nZET 20%\nOLiS 15%\nESKA 10%")

df = compute_scores()

tab_dash, tab_song, tab_import, tab_about = st.tabs(["Dashboard", "Utwór", "Import", "Metodologia"])

with tab_dash:
    if df.empty:
        st.info("Baza jest pusta. Kliknij po lewej „Pobierz RMF teraz” albo załaduj dane demonstracyjne.")
    else:
        c1,c2,c3,c4 = st.columns(4)
        c1.metric("Utwory", len(df))
        c2.metric("Current Familiar ≥70", int((df.familiarity>=70).sum()))
        c3.metric("Rising ≥65", int((df.momentum>=65).sum()))
        c4.metric("Pokrycie źródeł", f"{df.coverage.max():.0f}%")
        st.caption("Pokrycie oznacza sumę wag źródeł, dla których w bazie istnieje przynajmniej jedno notowanie. Wyniki są normalizowane do aktualnie dostępnych źródeł.")

        colf1,colf2,colf3 = st.columns(3)
        min_fam = colf1.slider("Min. Familiarity",0,100,0)
        min_mom = colf2.slider("Min. Momentum",0,100,0)
        only_unheard = colf3.checkbox("Tylko nieprzesłuchane")
        view = df[(df.familiarity>=min_fam)&(df.momentum>=min_mom)]
        if only_unheard: view=view[~view.heard]
        cols = ["artist","title","familiarity","momentum","format_fit","recommendation","RMF_pos","RMF_weeks","ZET_pos","ZET_weeks","OLIA_pos","OLIS_pos","ESKA_pos","status"]
        score_columns = {
            "familiarity": st.column_config.ProgressColumn(
                "Familiarity", help="Score 0–100, nie procent.", format="%.0f / 100", min_value=0.0, max_value=100.0
            ),
            "momentum": st.column_config.ProgressColumn(
                "Momentum", help="Score 0–100; 50 ≈ stabilnie.", format="%.0f / 100", min_value=0.0, max_value=100.0
            ),
            "format_fit": st.column_config.ProgressColumn(
                "Format Fit", help="Score 0–100 dopasowania do profilu RMF/ZET.", format="%.0f / 100", min_value=0.0, max_value=100.0
            ),
        }
        st.dataframe(
            view[[c for c in cols if c in view.columns]],
            hide_index=True,
            use_container_width=True,
            column_config=score_columns,
        )
        st.caption("Familiarity, Momentum i Format Fit są punktami w skali 0–100, a nie wartościami procentowymi.")

        st.subheader("🔥 Rising / do przesłuchania")
        rising = df.sort_values("momentum",ascending=False).head(12)
        st.dataframe(
            rising[["artist","title","familiarity","momentum","format_fit","recommendation"]],
            hide_index=True,
            use_container_width=True,
            column_config=score_columns,
        )

with tab_song:
    if df.empty:
        st.info("Najpierw dodaj dane.")
    else:
        labels = {f"{r.artist} — {r.title}": int(r.song_id) for r in df.itertuples()}
        label = st.selectbox("Utwór", list(labels.keys()))
        song_id = labels[label]
        row = df[df.song_id==song_id].iloc[0]
        a,b,c = st.columns(3)
        a.metric("Familiarity", f"{row.familiarity:.0f}/100")
        b.metric("Momentum", f"{row.momentum:.0f}/100")
        c.metric("Format Fit", f"{row.format_fit:.0f}/100")
        st.write(f"**Rekomendacja:** {row.recommendation}")
        h = song_history(song_id)
        if not h.empty:
            fig = px.line(h, x="chart_date", y="position", color="source", markers=True, title="Historia pozycji (niżej na wykresie = gorsza pozycja)")
            maxpos = max(20, int(h.position.max()))
            fig.update_yaxes(autorange="reversed", range=[maxpos+3, 1], dtick=5)
            st.plotly_chart(fig, use_container_width=True)
        with st.form("note_form"):
            heard = st.checkbox("Przesłuchany", value=bool(row.heard))
            statuses = ["Nie słuchałem","Ignore","Watch","Candidate","Current","Current Familiar","Recurrent"]
            idx = statuses.index(row.status) if row.status in statuses else 0
            status = st.selectbox("Mój status", statuses, index=idx)
            note = st.text_area("Notatka", value=row.note or "")
            if st.form_submit_button("Zapisz"):
                update_note(song_id,heard,status,note); st.success("Zapisano"); st.rerun()

with tab_import:
    st.subheader("Import notowania")
    st.write("Format minimalny: `position, artist, title`. Może też zawierać `release_date`.")
    source = st.selectbox("Źródło", ["ZET","OLIA","OLIS","ESKA","RMF"])
    chart_date = st.date_input("Data notowania", value=date.today())
    issue_key = st.text_input("Id/notowanie (opcjonalne)", value="")
    chart_size = st.number_input("Rozmiar listy", min_value=1, max_value=500, value=100 if source in ("OLIA","OLIS") else 20)
    uploaded = st.file_uploader("CSV / JSON / XLSX", type=["csv","json","xlsx","xls"])
    if uploaded:
        try:
            imp = parse_tabular(uploaded.getvalue(), uploaded.name)
            st.dataframe(imp.head(20), hide_index=True, use_container_width=True)
            if st.button("Importuj to notowanie"):
                issue = dataframe_to_issue(imp,source,chart_date.isoformat(),issue_key or None,int(chart_size))
                upsert_issue(issue["source"],issue["chart_date"],issue["issue_key"],issue["chart_size"],issue["entries"],f"manual:{uploaded.name}")
                st.success(f"Zaimportowano {len(issue['entries'])} pozycji."); st.rerun()
        except Exception as e:
            st.error(str(e))
    st.download_button("Pobierz szablon CSV", "position,artist,title,release_date\n1,Artist,Song,2026-01-01\n", "chart_template.csv", "text/csv")

with tab_about:
    st.markdown("""
### Wskaźniki
**Familiarity** łączy bieżącą siłę pozycji, peak, liczbę tygodni na liście i liczbę tygodni w Top 10. Źródła są ważone: OLiA 30 / RMF 25 / ZET 20 / OLiS 15 / ESKA 10.

**Momentum** patrzy na zmianę znormalizowanej siły pozycji w ostatnich czterech tygodniach. 50 ≈ stabilnie, >65 = wyraźny wzrost, <40 = spadek.

**Format Fit** jest osobnym wskaźnikiem z większym naciskiem na RMF i ZET (40/35), bo ma mówić raczej „czy to przypomina nasz format?” niż „czy to jest popularne wszędzie?”.

### Ważne
To wersja 0.1. Progi są celowo konfigurowalne. Po zebraniu 2–3 miesięcy danych sensownie będzie je skalibrować na utworach, które sam oznaczysz jako Current / Current Familiar / Recurrent.
""")
