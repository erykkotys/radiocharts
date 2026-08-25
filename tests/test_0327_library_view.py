from pathlib import Path

import radiocharts.db as db

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "radiocharts" / "app.py").read_text(encoding="utf-8")


def test_0327_v2_seed_runs_on_preexisting_db_that_missed_0326_seed(tmp_path, monkeypatch):
    db_path = tmp_path / "upgrade.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setattr(db, "_INITIALIZED_DB_PATH", None)
    monkeypatch.setenv("RADIOCHARTS_AUTO_LIBRARY_SEED", "0")
    db.init_db()
    with db.connect() as con:
        con.execute("DELETE FROM app_meta WHERE key='radio_library_seed_20260825_v2'")
        assert con.execute("SELECT COUNT(*) FROM songs").fetchone()[0] == 0

    monkeypatch.setenv("RADIOCHARTS_AUTO_LIBRARY_SEED", "1")
    monkeypatch.setattr(db, "_INITIALIZED_DB_PATH", None)
    db.init_db()
    with db.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM song_notes WHERE status LIKE 'Baza %' AND status<>'Baza Hold'").fetchone()[0] == 928
        row = con.execute(
            """SELECT n.status,n.downloaded,n.heard FROM songs s JOIN song_notes n ON n.song_id=s.id
               WHERE s.artist_key=? AND s.title_key=?""",
            (db.normalize("CELINE DION"), db.normalize("A NEW DAY HAS COME")),
        ).fetchone()
        assert tuple(row) == ("Baza R2", 1, 1)
        marker = con.execute("SELECT value FROM app_meta WHERE key='radio_library_seed_20260825_v2'").fetchone()[0]
        assert "rows=928" in marker


def test_0327_library_catalog_includes_hold(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "catalog.db")
    monkeypatch.setattr(db, "_INITIALIZED_DB_PATH", None)
    monkeypatch.setenv("RADIOCHARTS_AUTO_LIBRARY_SEED", "0")
    db.init_db()
    with db.connect() as con:
        a = db.get_or_create_song(con, "A", "One")
        b = db.get_or_create_song(con, "B", "Two")
    db.update_note(a, True, "Baza CF1", "", downloaded=True)
    db.update_note(b, True, "Baza Hold", "", downloaded=True)
    rows = db.radio_library_catalog()
    assert [r["song_id"] for r in rows] == [a, b]


def test_0327_ui_has_library_tab_status_filters_and_paste_sync():
    assert '("library", "Baza")' in APP
    assert 'elif view_key == "library":' in APP
    assert '"Szukaj w Bazie"' in APP
    assert 'key="dashboard_status_filter"' in APP
    assert 'key="airplay_status_filter"' in APP
    assert 'STATUS_FILTER_BASE = "Baza — wszystkie"' in APP
    assert '"Wklej eksport bazy radia"' in APP
    assert 'st.text_area(' in APP
    assert 'st.file_uploader(' not in APP


def test_0327_library_view_keeps_zero_airplay_songs_and_period_metrics():
    assert 'lib = library_rows.copy()' in APP
    assert 'lib = lib.merge(air[[c for c in air_keep if c in air.columns]], on="song_id", how="left")' in APP
    assert 'lib[col] = pd.to_numeric(lib[col], errors="coerce").fillna(0).astype(int)' in APP
    assert '"Tylko niegrane"' in APP
    assert '"radio_presence_period"' in APP
    assert 'station_total=reporting_station_count' in APP


def test_0327_status_order_bottom_up_contract():
    assert 'RADIO_STATUS_BOTTOM_UP = ["CF1", "CF2", "R1", "R2", "G1", "G2", "SP1", "SP2", "NB", "F1"]' in APP
