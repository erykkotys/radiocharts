from pathlib import Path

import radiocharts.db as db


def test_cross_source_artist_credit_aliases_share_song(tmp_path: Path):
    old = db.DB_PATH
    db.DB_PATH = tmp_path / "aliases.db"
    try:
        db.init_db()
        db.upsert_issue(
            "RMF", "2026-08-11", "6183", 20,
            [{"position": 1, "artist": "Męskie Granie Orkiestra 2026", "title": "Nareszcie"}],
        )
        db.upsert_issue(
            "OLIA", "2026-08-07", "2026-08-01_2026-08-07", 100,
            [{"position": 1, "artist": "Męskie Granie Orkiestra, Igor Herbut, Zalia, Vito Bambino", "title": "Nareszcie"}],
        )
        with db.connect() as con:
            songs = con.execute("SELECT id,artist,title FROM songs").fetchall()
            entries = con.execute("SELECT song_id FROM chart_entries").fetchall()
        assert len(songs) == 1
        assert len({int(x["song_id"]) for x in entries}) == 1
    finally:
        db.DB_PATH = old


def test_existing_alias_rows_are_merged_by_migration(tmp_path: Path):
    old = db.DB_PATH
    db.DB_PATH = tmp_path / "merge.db"
    try:
        db.init_db()
        with db.connect() as con:
            con.execute("DELETE FROM app_meta WHERE key='song_alias_merge_v1'")
            # Insert historical duplicate aliases directly, simulating pre-0.2.1 data.
            now = db._utcnow()
            con.execute(
                "INSERT INTO songs(artist,title,artist_key,title_key,created_at) VALUES(?,?,?,?,?)",
                ("Męskie Granie Orkiestra 2026", "Nareszcie", db.normalize("Męskie Granie Orkiestra 2026"), db.normalize("Nareszcie"), now),
            )
            a = con.execute("SELECT last_insert_rowid() id").fetchone()["id"]
            con.execute(
                "INSERT INTO songs(artist,title,artist_key,title_key,created_at) VALUES(?,?,?,?,?)",
                ("Męskie Granie Orkiestra, Igor Herbut, Zalia, Vito Bambino", "Nareszcie", db.normalize("Męskie Granie Orkiestra, Igor Herbut, Zalia, Vito Bambino"), db.normalize("Nareszcie"), now),
            )
            b = con.execute("SELECT last_insert_rowid() id").fetchone()["id"]
            con.execute("INSERT INTO chart_issues(source,chart_date,issue_key,chart_size,retrieved_at) VALUES('RMF','2026-08-11','x',20,?)", (now,))
            i1 = con.execute("SELECT last_insert_rowid() id").fetchone()["id"]
            con.execute("INSERT INTO chart_issues(source,chart_date,issue_key,chart_size,retrieved_at) VALUES('OLIA','2026-08-07','y',100,?)", (now,))
            i2 = con.execute("SELECT last_insert_rowid() id").fetchone()["id"]
            con.execute("INSERT INTO chart_entries(issue_id,song_id,position) VALUES(?,?,1)", (i1, a))
            con.execute("INSERT INTO chart_entries(issue_id,song_id,position) VALUES(?,?,1)", (i2, b))
        # init_db migrations are intentionally cached per process; force a new
        # startup cycle after manually deleting a marker in this migration test.
        db._INITIALIZED_DB_PATH = None
        db.init_db()
        with db.connect() as con:
            songs = con.execute("SELECT id FROM songs WHERE title_key=?", (db.normalize("Nareszcie"),)).fetchall()
            entries = con.execute("SELECT song_id FROM chart_entries").fetchall()
        assert len(songs) == 1
        assert len({int(x["song_id"]) for x in entries}) == 1
    finally:
        db.DB_PATH = old
