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
    station_info = {r[1]: r for r in con.execute("PRAGMA table_info(airplay_stations)")}
    indexes = {r[1] for r in con.execute("PRAGMA index_list(airplay_plays)")}
    marker_v3 = con.execute("SELECT value FROM app_meta WHERE key='airplay_schema_v3'").fetchone()
    fk_errors = con.execute("PRAGMA foreign_key_check").fetchall()
    con.close()

    assert station_info["station_id"][5] == 1  # real PRIMARY KEY, not merely an index
    assert {"played_at", "artist", "title", "artist_key", "title_key", "retrieved_at"} <= cols_plays
    assert {"start_hour", "end_hour", "fetched_at", "play_count", "success"} <= cols_windows
    assert "idx_airplay_plays_time_station" in indexes
    assert marker_v3 == ("done",)
    assert fk_errors == []

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


def test_rebuild_repairs_real_foreign_key_mismatch(monkeypatch, tmp_path):
    """Reproduce the user's DB: FK targets a non-UNIQUE station_id column."""
    path = tmp_path / "fk-mismatch.db"
    con = sqlite3.connect(path)
    con.executescript(
        """
        PRAGMA foreign_keys=OFF;
        CREATE TABLE airplay_stations (
            id INTEGER PRIMARY KEY,
            name TEXT,
            station_id INTEGER,
            slug TEXT,
            source_url TEXT,
            active INTEGER,
            discovered_at TEXT,
            updated_at TEXT
        );
        CREATE INDEX idx_airplay_stations_station_id ON airplay_stations(station_id);
        CREATE TABLE airplay_plays (
            id INTEGER PRIMARY KEY,
            station_id INTEGER REFERENCES airplay_stations(station_id),
            played_at TEXT, artist TEXT, title TEXT, artist_key TEXT, title_key TEXT,
            song_id INTEGER, source_url TEXT, retrieved_at TEXT
        );
        CREATE TABLE airplay_windows (
            station_id INTEGER REFERENCES airplay_stations(station_id),
            play_date TEXT, start_hour INTEGER, end_hour INTEGER, fetched_at TEXT,
            play_count INTEGER, source_url TEXT, success INTEGER, message TEXT
        );
        INSERT INTO airplay_stations(id,name,station_id,active,discovered_at,updated_at)
        VALUES(1,'Radio Kalisz',48,1,'','');
        """
    )
    con.commit()
    con.close()

    _use_db(monkeypatch, path)
    db.init_db()
    stored = db.store_airplay_window(
        48,
        "Radio Kalisz",
        "2026-08-19",
        12,
        [{"played_at": "2026-08-19T12:05", "artist": "Męskie Granie Orkiestra 2026", "title": "Nareszcie"}],
    )
    assert stored == 1
    assert db.airplay_window_exists(48, "2026-08-19", 12)

    with db.connect() as con:
        assert con.execute("PRAGMA foreign_key_check").fetchall() == []
        parent = con.execute("SELECT station_id,name FROM airplay_stations WHERE station_id=48").fetchone()
        assert tuple(parent) == (48, "Radio Kalisz")


def test_airplay_link_migration_restores_shared_song_links(monkeypatch, tmp_path):
    path = tmp_path / "link.db"
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
        chart_song_id = con.execute("SELECT song_id FROM chart_entries LIMIT 1").fetchone()[0]
        con.execute("UPDATE airplay_plays SET song_id=NULL")
        con.execute("DELETE FROM app_meta WHERE key='airplay_link_songs_v1'")

    monkeypatch.setattr(db, "_INITIALIZED_DB_PATH", None)
    db.init_db()
    with db.connect() as con:
        linked_id = con.execute("SELECT song_id FROM airplay_plays LIMIT 1").fetchone()[0]
        marker = con.execute("SELECT value FROM app_meta WHERE key='airplay_link_songs_v1'").fetchone()[0]
    assert linked_id == chart_song_id
    assert marker.isdigit()


def test_init_quarantines_legacy_airplay_daily_fk_to_old_station_id(monkeypatch, tmp_path):
    """Reproduce 0.3.14 startup crash caused by legacy airplay_daily -> stations(id)."""
    path = tmp_path / "legacy-daily.db"
    con = sqlite3.connect(path)
    con.executescript(
        """
        PRAGMA foreign_keys=OFF;
        CREATE TABLE songs (
            id INTEGER PRIMARY KEY, artist TEXT NOT NULL, title TEXT NOT NULL,
            artist_key TEXT NOT NULL, title_key TEXT NOT NULL, release_date TEXT,
            isrc TEXT, created_at TEXT NOT NULL, UNIQUE(artist_key,title_key)
        );
        CREATE TABLE airplay_stations (
            id INTEGER PRIMARY KEY,
            name TEXT,
            station_id INTEGER,
            slug TEXT,
            source_url TEXT,
            active INTEGER,
            discovered_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE airplay_plays (
            id INTEGER PRIMARY KEY,
            station_id INTEGER REFERENCES airplay_stations(station_id),
            played_at TEXT, artist TEXT, title TEXT, artist_key TEXT, title_key TEXT,
            song_id INTEGER REFERENCES songs(id) ON DELETE SET NULL,
            source_url TEXT, retrieved_at TEXT
        );
        CREATE TABLE airplay_windows (
            station_id INTEGER REFERENCES airplay_stations(station_id),
            play_date TEXT, start_hour INTEGER, end_hour INTEGER, fetched_at TEXT,
            play_count INTEGER, source_url TEXT, success INTEGER, message TEXT
        );
        CREATE TABLE airplay_daily (
            station_id INTEGER REFERENCES airplay_stations(id),
            song_id INTEGER REFERENCES songs(id) ON DELETE CASCADE,
            play_date TEXT,
            play_count INTEGER
        );
        INSERT INTO songs(id,artist,title,artist_key,title_key,created_at)
        VALUES(7,'Legacy','Track','legacy','track','2026-01-01T00:00:00Z');
        INSERT INTO airplay_stations(id,name,station_id,active,discovered_at,updated_at)
        VALUES(1,'Radio Kalisz',48,1,'','');
        INSERT INTO airplay_daily(station_id,song_id,play_date,play_count)
        VALUES(1,7,'2026-08-19',3);
        """
    )
    con.commit()
    con.close()

    _use_db(monkeypatch, path)
    db.init_db()

    con = sqlite3.connect(path)
    names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "airplay_daily" not in names
    assert "airplay_daily_legacy_0315" in names
    assert con.execute("SELECT station_id,song_id,play_date,play_count FROM airplay_daily_legacy_0315").fetchall() == [
        (1, 7, "2026-08-19", 3)
    ]
    assert con.execute("PRAGMA foreign_key_check").fetchall() == []
    marker = con.execute("SELECT value FROM app_meta WHERE key='airplay_daily_legacy_v1'").fetchone()
    con.close()
    assert marker == ("1",)


def test_init_relinks_aliases_only_once_when_both_markers_missing(monkeypatch, tmp_path):
    path = tmp_path / "one-relink.db"
    _use_db(monkeypatch, path)
    calls = []
    original = db._relink_airplay_unique_chart_titles

    def counted(con):
        calls.append(1)
        return original(con)

    monkeypatch.setattr(db, "_relink_airplay_unique_chart_titles", counted)
    db.init_db()

    assert len(calls) == 1
    con = sqlite3.connect(path)
    assert con.execute("SELECT value FROM app_meta WHERE key='airplay_chart_title_relink_v1'").fetchone() is not None
    assert con.execute("SELECT value FROM app_meta WHERE key='airplay_chart_title_relink_v2'").fetchone() is not None
    con.close()
