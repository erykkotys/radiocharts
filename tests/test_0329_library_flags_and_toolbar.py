from pathlib import Path

import radiocharts.db as db

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "radiocharts" / "app.py").read_text(encoding="utf-8")
DBSRC = (ROOT / "radiocharts" / "db.py").read_text(encoding="utf-8")


def _db(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(db, "_INITIALIZED_DB_PATH", None)
    monkeypatch.setenv("RADIOCHARTS_AUTO_LIBRARY_SEED", "0")
    db.init_db()


def test_0329_second_repair_runs_even_when_v1_marker_exists(tmp_path, monkeypatch):
    _db(monkeypatch, tmp_path)
    with db.connect() as con:
        sid = db.get_or_create_song(con, "Tina Turner", "The Best")
    db.update_note(sid, False, "Nie słuchałem", "", downloaded=False)
    # Simulate the broken production state: Baza status, old v1 marker already done,
    # but flags still false and new v2 marker absent.
    with db.connect() as con:
        con.execute("UPDATE song_notes SET status='Baza G1',heard=0,downloaded=0 WHERE song_id=?", (sid,))
        con.execute("INSERT OR REPLACE INTO app_meta(key,value) VALUES('radio_library_heard_downloaded_v1','updated=0')")
        con.execute("DELETE FROM app_meta WHERE key='radio_library_heard_downloaded_v2'")
    monkeypatch.setattr(db, "_INITIALIZED_DB_PATH", None)
    db.init_db()
    with db.connect() as con:
        row = con.execute("SELECT heard,downloaded,status FROM song_notes WHERE song_id=?", (sid,)).fetchone()
        marker = con.execute("SELECT value FROM app_meta WHERE key='radio_library_heard_downloaded_v2'").fetchone()
    assert tuple(row) == (1, 1, "Baza G1")
    assert marker is not None


def test_0329_manual_base_status_enforces_heard_and_downloaded(tmp_path, monkeypatch):
    _db(monkeypatch, tmp_path)
    with db.connect() as con:
        sid = db.get_or_create_song(con, "Artist", "Track")
    db.update_note(sid, False, "Baza R2", "note", downloaded=False)
    with db.connect() as con:
        row = con.execute("SELECT heard,downloaded,status,note FROM song_notes WHERE song_id=?", (sid,)).fetchone()
    assert tuple(row) == (1, 1, "Baza R2", "note")


def test_0329_hold_remains_neutral(tmp_path, monkeypatch):
    _db(monkeypatch, tmp_path)
    with db.connect() as con:
        sid = db.get_or_create_song(con, "Artist", "Hold")
    db.update_note(sid, False, "Baza Hold", "", downloaded=False)
    with db.connect() as con:
        row = con.execute("SELECT heard,downloaded FROM song_notes WHERE song_id=?", (sid,)).fetchone()
    assert tuple(row) == (0, 0)


def test_0329_dashboard_toolbar_is_bottom_aligned_and_status_has_label():
    assert 'vertical_alignment="bottom"' in APP
    assert "rc-control-label" in APP
    assert 'field_label: str = "Status"' in APP
    assert '"radio_library_heard_downloaded_v2"' in DBSRC
