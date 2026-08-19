import sqlite3
from datetime import date

import radiocharts.db as db


def _use_db(monkeypatch, path):
    monkeypatch.setattr(db, "DB_PATH", path)
    monkeypatch.setattr(db, "_INITIALIZED_DB_PATH", None)


def test_init_upgrades_partial_airplay_tables(monkeypatch, tmp_path):
    path = tmp_path / "legacy.db"
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE airplay_stations (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE airplay_plays (id INTEGER PRIMARY KEY, station_id INTEGER);
        CREATE TABLE airplay_windows (station_id INTEGER, play_date TEXT);
        """
    )
    con.commit()
    con.close()

    _use_db(monkeypatch, path)
    db.init_db()

    con = sqlite3.connect(path)
    cols_plays = {r[1] for r in con.execute("PRAGMA table_info(airplay_plays)")}
    cols_windows = {r[1] for r in con.execute("PRAGMA table_info(airplay_windows)")}
    indexes = {r[1] for r in con.execute("PRAGMA index_list(airplay_plays)")}
    marker = con.execute("SELECT value FROM app_meta WHERE key='airplay_schema_v2'").fetchone()
    con.close()

    assert {"played_at", "artist", "title", "artist_key", "title_key", "retrieved_at"} <= cols_plays
    assert {"start_hour", "end_hour", "fetched_at", "play_count", "success"} <= cols_windows
    assert "idx_airplay_plays_time_station" in indexes
    assert marker == ("done",)

    db.upsert_airplay_stations([
        {"station_id": 2, "name": "RMF FM", "slug": "rmf-fm", "source_url": "https://example/rmf"}
    ])
    stored = db.store_airplay_window(
        2,
        "RMF FM",
        date(2026, 8, 19),
        10,
        [{"played_at": "2026-08-19T10:15", "artist": "Artist", "title": "Song"}],
        "https://example/window",
    )
    assert stored == 1
    assert db.airplay_window_exists(2, date(2026, 8, 19), 10)


def test_airplay_detach_migration_clears_legacy_song_links(monkeypatch, tmp_path):
    path = tmp_path / "detach.db"
    _use_db(monkeypatch, path)
    db.init_db()
    db.upsert_issue("RMF", "2026-08-18", "x", 20, [
        {"position": 1, "artist": "Dua Lipa", "title": "Houdini"},
    ])
    db.upsert_airplay_stations([{"station_id": 2, "name": "RMF FM"}])
    db.store_airplay_window(
        2,
        "RMF FM",
        "2026-08-18",
        18,
        [{"played_at": "2026-08-18T18:05", "artist": "Dua Lipa", "title": "Houdini"}],
    )
    with db.connect() as con:
        song_id = con.execute("SELECT id FROM songs LIMIT 1").fetchone()[0]
        con.execute("UPDATE airplay_plays SET song_id=?", (song_id,))
        con.execute("DELETE FROM app_meta WHERE key='airplay_detach_chart_v1'")

    monkeypatch.setattr(db, "_INITIALIZED_DB_PATH", None)
    db.init_db()
    with db.connect() as con:
        linked = con.execute("SELECT COUNT(*) FROM airplay_plays WHERE song_id IS NOT NULL").fetchone()[0]
        marker = con.execute("SELECT value FROM app_meta WHERE key='airplay_detach_chart_v1'").fetchone()[0]
    assert linked == 0
    assert marker == "done"
