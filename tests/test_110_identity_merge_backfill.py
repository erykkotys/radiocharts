from datetime import date, datetime, timezone
from pathlib import Path

import radiocharts.db as db
from radiocharts import airplay


def _reset_db(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "radiocharts.db")
    monkeypatch.setattr(db, "_INITIALIZED_DB_PATH", None)
    db.init_db()


def test_auto_merge_v2_connects_meskie_granie_credit_variants(monkeypatch, tmp_path):
    _reset_db(monkeypatch, tmp_path)
    title = "To Bardzo Ziemskie"
    artists = [
        "Męskie Granie Orkiestra 2025",
        "Męskie Granie Orkiestra, Ralph Kaminski, Natalia Przybysz",
        "Natalia Przybysz, Ralph Kaminski",
        "N. Przybysz, Herb",
    ]
    with db.connect() as con:
        con.execute("DELETE FROM app_meta WHERE key='song_alias_merge_v2'")
        now = db._utcnow()
        ids = []
        for artist in artists:
            con.execute(
                "INSERT INTO songs(artist,title,artist_key,title_key,created_at) VALUES(?,?,?,?,?)",
                (artist, title, db.normalize(artist), db.normalize(title), now),
            )
            ids.append(int(con.execute("SELECT last_insert_rowid()").fetchone()[0]))
        # Make the first credit visibly canonical-worthy and give another one airplay.
        con.execute(
            "INSERT INTO song_notes(song_id,heard,status,downloaded,note,updated_at) VALUES(?,?,?,?,?,?)",
            (ids[0], 1, "Watch", 0, "keep me", now),
        )
        con.execute(
            "INSERT OR IGNORE INTO airplay_stations(station_id,name,slug,source_url,active,discovered_at,updated_at) VALUES(1,'Test','','',1,?,?)",
            (now, now),
        )
        con.execute(
            "INSERT INTO airplay_plays(station_id,played_at,artist,title,artist_key,title_key,song_id,retrieved_at) VALUES(?,?,?,?,?,?,?,?)",
            (1, "2026-09-01T10:00", artists[-1], title, db.artist_anchor(artists[-1]), db.normalize(title), ids[-1], now),
        )
    monkeypatch.setattr(db, "_INITIALIZED_DB_PATH", None)
    db.init_db()
    with db.connect() as con:
        songs = con.execute("SELECT id,artist FROM songs WHERE title_key=?", (db.normalize(title),)).fetchall()
        redirects = con.execute("SELECT old_song_id,canonical_song_id FROM song_id_redirects").fetchall()
        aliases = con.execute("SELECT artist_key,title_key,canonical_song_id FROM song_identity_aliases WHERE title_key=?", (db.normalize(title),)).fetchall()
        play_song = con.execute("SELECT song_id FROM airplay_plays LIMIT 1").fetchone()[0]
        note = con.execute("SELECT status,note FROM song_notes WHERE song_id=?", (songs[0]["id"],)).fetchone()
    assert len(songs) == 1
    canonical = int(songs[0]["id"])
    assert {int(r["old_song_id"]) for r in redirects}.issuperset(set(ids) - {canonical})
    assert {int(r["canonical_song_id"]) for r in aliases} == {canonical}
    assert int(play_song) == canonical
    assert note["status"] == "Watch"
    assert "keep me" in note["note"]


def test_manual_merge_preserves_history_notes_airplay_and_redirect(monkeypatch, tmp_path):
    _reset_db(monkeypatch, tmp_path)
    db.upsert_issue("RMF", "2026-09-01", "a", 20, [
        {"position": 3, "artist": "Main Artist", "title": "Very Specific Song"},
    ])
    with db.connect() as con:
        now = db._utcnow()
        con.execute(
            "INSERT INTO songs(artist,title,artist_key,title_key,created_at) VALUES(?,?,?,?,?)",
            ("Different Credit", "Very Specific Song", db.normalize("Different Credit"), db.normalize("Very Specific Song"), now),
        )
        dup = int(con.execute("SELECT last_insert_rowid()").fetchone()[0])
        master = int(con.execute("SELECT id FROM songs WHERE artist_key=?", (db.normalize("Main Artist"),)).fetchone()[0])
        con.execute(
            "INSERT INTO song_notes(song_id,heard,status,downloaded,note,updated_at) VALUES(?,?,?,?,?,?)",
            (dup, 1, "Watch", 1, "duplicate note", now),
        )
        con.execute(
            "INSERT OR IGNORE INTO airplay_stations(station_id,name,slug,source_url,active,discovered_at,updated_at) VALUES(2,'Test','','',1,?,?)",
            (now, now),
        )
        con.execute(
            "INSERT INTO airplay_plays(station_id,played_at,artist,title,artist_key,title_key,song_id,retrieved_at) VALUES(?,?,?,?,?,?,?,?)",
            (2, "2026-09-02T12:00", "Different Credit", "Very Specific Song", db.artist_anchor("Different Credit"), db.normalize("Very Specific Song"), dup, now),
        )
    result = db.merge_songs(master, [dup])
    assert result["merged"] == 1
    assert db.canonical_song_id(dup) == master
    with db.connect() as con:
        assert con.execute("SELECT 1 FROM songs WHERE id=?", (dup,)).fetchone() is None
        assert int(con.execute("SELECT song_id FROM airplay_plays LIMIT 1").fetchone()[0]) == master
        note = con.execute("SELECT status,downloaded,note FROM song_notes WHERE song_id=?", (master,)).fetchone()
    assert note["status"] == "Watch"
    assert note["downloaded"] == 1
    assert "duplicate note" in note["note"]


def test_get_or_create_remembers_related_credit_alias(monkeypatch, tmp_path):
    _reset_db(monkeypatch, tmp_path)
    with db.connect() as con:
        a = db.get_or_create_song(con, "Męskie Granie Orkiestra 2025", "To Bardzo Ziemskie")
        b = db.get_or_create_song(con, "Męskie Granie Orkiestra, Ralph Kaminski", "To Bardzo Ziemskie")
        assert a == b
        alias = con.execute(
            "SELECT canonical_song_id FROM song_identity_aliases WHERE artist_key=? AND title_key=?",
            (db.normalize("Męskie Granie Orkiestra, Ralph Kaminski"), db.normalize("To Bardzo Ziemskie")),
        ).fetchone()
    assert int(alias["canonical_song_id"]) == a


def test_existing_airplay_windows_bulk_check_is_resumable(monkeypatch, tmp_path):
    _reset_db(monkeypatch, tmp_path)
    db.upsert_airplay_stations([{"station_id": 11, "name": "Station 11"}])
    db.store_airplay_window(11, "Station 11", date(2026, 1, 1), 0, [
        {"played_at": "2026-01-01T00:15", "artist": "A", "title": "Song One"},
    ])
    existing = db.existing_airplay_windows([11], date(2026, 1, 1), date(2026, 1, 2))
    assert (11, "2026-01-01", 0) in existing


def test_backfill_uses_bulk_existing_set_and_skips_download(monkeypatch, tmp_path):
    _reset_db(monkeypatch, tmp_path)
    db.upsert_airplay_stations([{"station_id": 21, "name": "Station 21"}])
    monkeypatch.setattr(airplay, "_stations_or_discover", lambda progress_callback=None: db.list_airplay_stations(active_only=True))
    monkeypatch.setattr(
        airplay,
        "completed_windows_in_range",
        lambda *args, **kwargs: [(date(2026, 1, 1), 0), (date(2026, 1, 1), 2)],
    )
    monkeypatch.setattr(
        airplay,
        "existing_airplay_windows",
        lambda *args, **kwargs: {(21, "2026-01-01", 0)},
    )
    calls = []
    def fake_fetch(station, d, h, timeout=12):
        calls.append((int(station["station_id"]), d, h))
        return [], "test://url"
    monkeypatch.setattr(airplay, "fetch_window", fake_fetch)
    result = airplay.backfill_airplay([21], date(2026, 1, 1), date(2026, 1, 1), pause_seconds=0)
    assert result["skipped"] == 1
    assert result["ok"] == 1
    assert calls == [(21, date(2026, 1, 1), 2)]


def test_manual_is_current_for_merge_resumable_backfill_and_1d():
    app = Path("radiocharts/app.py").read_text(encoding="utf-8")
    assert "Duplikaty / scalanie utworu" in app
    assert "jednym zapytaniem wczytuje już poprawnie zapisane bloki" in app
    assert "Dzisiaj (1d)" in app
    assert "Domyślny pozostaje **ostatni tydzień (7d)**" in app
