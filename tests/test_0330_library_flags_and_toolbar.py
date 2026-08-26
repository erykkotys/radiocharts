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


def test_0330_v3_repairs_state_even_when_v2_marker_already_exists(tmp_path, monkeypatch):
    _db(monkeypatch, tmp_path)
    with db.connect() as con:
        sid = db.get_or_create_song(con, "Tina Turner", "The Best")
        con.execute("DROP TRIGGER IF EXISTS trg_song_notes_base_flags_insert")
        con.execute("DROP TRIGGER IF EXISTS trg_song_notes_base_flags_update")
        con.execute(
            "INSERT OR REPLACE INTO song_notes(song_id,heard,status,downloaded,note,updated_at) VALUES(?,?,?,?,?,?)",
            (sid, 0, "Baza G1", 0, "", "2026-08-26T00:00:00Z"),
        )
        # Reproduce the production state visible in 0.3.29: v2 is already marked done,
        # while the row itself is stale. Remove only the new v3 marker.
        con.execute("INSERT OR REPLACE INTO app_meta(key,value) VALUES('radio_library_heard_downloaded_v2','updated=0')")
        con.execute("DELETE FROM app_meta WHERE key='radio_library_heard_downloaded_v3'")
    monkeypatch.setattr(db, "_INITIALIZED_DB_PATH", None)
    db.init_db()
    with db.connect() as con:
        row = con.execute("SELECT heard,downloaded,status FROM song_notes WHERE song_id=?", (sid,)).fetchone()
        marker = con.execute("SELECT value FROM app_meta WHERE key='radio_library_heard_downloaded_v3'").fetchone()
    assert tuple(row) == (1, 1, "Baza G1")
    assert marker is not None


def test_0330_db_trigger_prevents_stale_base_flags(tmp_path, monkeypatch):
    _db(monkeypatch, tmp_path)
    with db.connect() as con:
        sid = db.get_or_create_song(con, "Artist", "Base Track")
        con.execute(
            "INSERT OR REPLACE INTO song_notes(song_id,heard,status,downloaded,note,updated_at) VALUES(?,?,?,?,?,?)",
            (sid, 0, "Baza R2", 0, "", "2026-08-26T00:00:00Z"),
        )
        row = con.execute("SELECT heard,downloaded FROM song_notes WHERE song_id=?", (sid,)).fetchone()
    assert tuple(row) == (1, 1)


def test_0330_catalog_safety_coerces_real_base_flags(tmp_path, monkeypatch):
    _db(monkeypatch, tmp_path)
    with db.connect() as con:
        sid = db.get_or_create_song(con, "Artist", "Base Track")
        # Drop triggers to emulate a damaged legacy DB and write impossible state.
        con.execute("DROP TRIGGER IF EXISTS trg_song_notes_base_flags_insert")
        con.execute("DROP TRIGGER IF EXISTS trg_song_notes_base_flags_update")
        con.execute(
            "INSERT OR REPLACE INTO song_notes(song_id,heard,status,downloaded,note,updated_at) VALUES(?,?,?,?,?,?)",
            (sid, 0, "Baza CF1", 0, "", "2026-08-26T00:00:00Z"),
        )
    rows = db.radio_library_catalog()
    row = next(r for r in rows if int(r["song_id"]) == sid)
    assert int(row["heard"]) == 1
    assert int(row["downloaded"]) == 1


def test_0330_dashboard_toolbar_uses_native_count_control():
    assert 'ctl_count.text_input(' in APP
    assert '"Utwory (filtr / okres)"' in APP
    assert 'dashboard_count_slot' not in APP
    assert 'height:2.1rem !important' in APP
    assert 'radio_library_heard_downloaded_v3' in DBSRC
    assert 'trg_song_notes_base_flags_update' in DBSRC
    assert 'lib[state_col] = lib[state_col].fillna(0).astype(bool)' in APP
    assert 'field_label: str = "Status"' in APP
    assert 'vertical_alignment="bottom"' in APP
