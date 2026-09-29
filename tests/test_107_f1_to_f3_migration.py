from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]


def test_current_taxonomy_uses_f3_not_f1():
    app = (ROOT / "radiocharts/app.py").read_text(encoding="utf-8")
    api = (ROOT / "radiocharts/api.py").read_text(encoding="utf-8")
    db = (ROOT / "radiocharts/db.py").read_text(encoding="utf-8")
    assert '"NB", "F3"' in app
    assert '"NB", "F3"' in api
    assert 'RADIO_LIBRARY_CATEGORIES = ("R2", "R1", "CF2", "CF1", "F3"' in db
    assert '"F1 Candidate": "F3 Candidate"' in db
    assert '"Baza F1": "Baza F3"' in db
    assert '"status_taxonomy_v4"' in db


def test_seed_uses_f3_category():
    seed = (ROOT / "radiocharts/data/radio_library_seed_20260825.tsv").read_text(encoding="utf-8")
    rows = [line.split("\t") for line in seed.splitlines()[1:] if line.strip()]
    categories = {row[1] for row in rows if len(row) > 1}
    assert "F3" in categories
    assert "F1" not in categories


def test_existing_f1_rows_migrate_to_f3(tmp_path, monkeypatch):
    import radiocharts.db as db

    db_path = tmp_path / "radiocharts.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setattr(db, "_INITIALIZED_DB_PATH", None)
    db.init_db()

    with db.connect() as con:
        song1 = db.get_or_create_song(con, "Artist One", "Song One")
        song2 = db.get_or_create_song(con, "Artist Two", "Song Two")
        now = db._utcnow()
        con.execute(
            "INSERT OR REPLACE INTO song_notes(song_id,heard,status,downloaded,note,updated_at) VALUES(?,?,?,?,?,?)",
            (song1, 1, "Baza F1", 1, "", now),
        )
        con.execute(
            "INSERT OR REPLACE INTO song_notes(song_id,heard,status,downloaded,note,updated_at) VALUES(?,?,?,?,?,?)",
            (song2, 1, "F1 Candidate", 0, "", now),
        )
        con.execute("DELETE FROM app_meta WHERE key='status_taxonomy_v4'")

    monkeypatch.setattr(db, "_INITIALIZED_DB_PATH", None)
    db.init_db()
    with db.connect() as con:
        statuses = {r[0] for r in con.execute("SELECT status FROM song_notes").fetchall()}
        assert "Baza F3" in statuses
        assert "F3 Candidate" in statuses
        assert "Baza F1" not in statuses
        assert "F1 Candidate" not in statuses
