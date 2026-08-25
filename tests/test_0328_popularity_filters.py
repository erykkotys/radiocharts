from pathlib import Path

import radiocharts.db as db

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "radiocharts" / "app.py").read_text(encoding="utf-8")


def test_0328_radio_library_sync_marks_heard_and_downloaded(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "sync.db")
    monkeypatch.setattr(db, "_INITIALIZED_DB_PATH", None)
    monkeypatch.setenv("RADIOCHARTS_AUTO_LIBRARY_SEED", "0")
    db.init_db()
    with db.connect() as con:
        sid = db.get_or_create_song(con, "Tina Turner", "The Best")
    db.update_note(sid, False, "Nie słuchałem", "keep", downloaded=False)
    txt = "Active\tCat\tPack\tVer\tTitle\tArtist\tAlbum\tRuntime\nChecked\tG1\t\t\tTHE BEST\tTina Turner\t\t04:05\n"
    result = db.sync_radio_library_tsv(txt)
    assert result["heard_marked"] == 1
    assert result["downloaded_marked"] == 1
    with db.connect() as con:
        row = con.execute("SELECT heard,status,downloaded,note FROM song_notes WHERE song_id=?", (sid,)).fetchone()
    assert tuple(row) == (1, "Baza G1", 1, "keep")


def test_0328_upgrade_marks_existing_base_rows_heard_and_downloaded(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "upgrade.db")
    monkeypatch.setattr(db, "_INITIALIZED_DB_PATH", None)
    monkeypatch.setenv("RADIOCHARTS_AUTO_LIBRARY_SEED", "0")
    db.init_db()
    with db.connect() as con:
        sid = db.get_or_create_song(con, "A", "B")
    db.update_note(sid, False, "Baza R2", "", downloaded=False)
    with db.connect() as con:
        con.execute("DELETE FROM app_meta WHERE key='radio_library_heard_downloaded_v1'")
    monkeypatch.setattr(db, "_INITIALIZED_DB_PATH", None)
    db.init_db()
    with db.connect() as con:
        row = con.execute("SELECT heard,downloaded FROM song_notes WHERE song_id=?", (sid,)).fetchone()
    assert tuple(row) == (1, 1)


def test_0328_ui_download_filters_and_status_checkboxes():
    assert 'DOWNLOAD_FILTER_OPTIONS = ["Any", "Yes", "No"]' in APP
    assert 'key="dashboard_downloaded_filter"' in APP
    assert 'key="airplay_downloaded_filter"' in APP
    assert 'key="library_downloaded_filter"' in APP
    assert 'def render_status_checkbox_filter' in APP
    assert 'g1.checkbox("Baza — wszystkie"' in APP
    assert 'g2.checkbox("Candidate — wszystkie"' in APP


def test_0328_compact_is_default_and_hold_is_in_library():
    assert '["Auto", "Pełny", "Kompaktowy"],\n                index=2' in APP
    assert 'return ["Baza Hold", *BASE_STATUSES]' in APP


def test_0328_popularity_and_7d_spins_are_standard_columns():
    assert 'POPULARITY_CHART_WEIGHTS = {"OLIA": 35.0, "OLIS": 25.0, "RMF": 20.0, "ZET": 12.0, "ESKA": 8.0}' in APP
    assert '0.80 * out["airplay_volume_index"] + 0.20 * out["chart_popularity_bonus"]' in APP
    assert 'gb.configure_column("airplay_spins_7d", "Emisje 7d"' in APP
    assert '("familiarity", "Chart Score"' in APP
    assert '("popularity", "Popularity"' in APP
