from pathlib import Path

import radiocharts.db as db

APP = (Path(__file__).resolve().parents[1] / "radiocharts" / "app.py").read_text(encoding="utf-8")


def _use_db(monkeypatch, path):
    monkeypatch.setattr(db, "DB_PATH", path)
    monkeypatch.setattr(db, "_INITIALIZED_DB_PATH", None)


def test_0323_downloaded_flag_persists_and_old_update_preserves_it(tmp_path, monkeypatch):
    _use_db(monkeypatch, tmp_path / "downloaded.db")
    db.init_db()
    with db.connect() as con:
        sid = db.get_or_create_song(con, "Artist", "Track")

    db.update_note(sid, True, "CF1 Candidate", "note", downloaded=True)
    row = db.get_song(sid)
    assert row["downloaded"] == 1

    # Backward-compatible callers that still send 4 args must not clear DL.
    db.update_note(sid, True, "CF1 Candidate", "changed")
    row = db.get_song(sid)
    assert row["downloaded"] == 1
    assert row["note"] == "changed"


def test_0323_status_v3_migrates_old_cf_candidate(tmp_path, monkeypatch):
    _use_db(monkeypatch, tmp_path / "status-v3.db")
    db.init_db()
    with db.connect() as con:
        sid = db.get_or_create_song(con, "Artist", "Track")
        con.execute("DELETE FROM app_meta WHERE key='status_taxonomy_v3'")
        con.execute(
            "INSERT OR REPLACE INTO song_notes(song_id,heard,status,downloaded,note,updated_at) VALUES(?,?,?,?,?,?)",
            (sid, 0, "CF Candidate", 0, "", "2026-08-22T00:00:00Z"),
        )

    monkeypatch.setattr(db, "_INITIALIZED_DB_PATH", None)
    db.init_db()
    assert db.get_song(sid)["status"] == "CF1 Candidate"


def test_0323_dashboard_cleanup_and_status_order_contract():
    assert '"Poza formatem",\n    "Słabe",\n    "Watch",\n    "R2 Candidate",\n    "R1 Candidate",\n    "CF2 Candidate",\n    "CF1 Candidate"' in APP
    assert "Current Familiar ≥70%" not in APP[: APP.index('st.markdown("## 📘 Manual RadioCharts")')]
    assert "Rising ≥65%" not in APP[: APP.index('st.markdown("## 📘 Manual RadioCharts")')]
    assert "Pokrycie źródeł" not in APP[: APP.index('st.markdown("## 📘 Manual RadioCharts")')]
    assert "Radio 7d:" not in APP
    assert "Familiarity, momentum i radio presence · wsparcie odsłuchu i ręcznej decyzji" not in APP
    assert '"downloaded", "DL"' in APP


def test_0323_airplay_detail_uses_selected_dates_and_wide_tables_get_proxy_scrollbar():
    assert "detail_for_range = cached_airplay_track_detail(" in APP
    assert 'song_air_start.isoformat(),' in APP
    assert 'song_air_end.isoformat(),' in APP
    assert 'st.caption(f"Zakres szczegółów: {song_air_start} → {song_air_end}")' in APP
    assert "FLOATING_HSCROLL_INSTALLER" in APP
    assert "__rcFloatingGridHScroll" in APP
    assert APP.count("floating_hscroll=True") >= 2
