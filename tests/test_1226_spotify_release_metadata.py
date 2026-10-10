from pathlib import Path

import radiocharts.db as db
import radiocharts.music_metadata as mm

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "radiocharts" / "app.py").read_text(encoding="utf-8")
API = (ROOT / "radiocharts" / "api.py").read_text(encoding="utf-8")
MUSIC_METADATA = (ROOT / "radiocharts" / "music_metadata.py").read_text(encoding="utf-8")


def _use_db(monkeypatch, path):
    monkeypatch.setattr(db, "DB_PATH", path)
    monkeypatch.setattr(db, "_INITIALIZED_DB_PATH", None)


def test_release_contract_and_spotify_share_no_songlink():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "1.2.28"
    gradle = (ROOT / "android" / "RadioChartsAndroid" / "app" / "build.gradle.kts").read_text(encoding="utf-8")
    assert 'versionCode = 51' in gradle
    assert 'versionName = "1.2.28"' in gradle
    assert "https://song.link/i/" not in APP
    assert "https://open.spotify.com/track/" in APP
    assert "spotify-id-from-metadata/json" in MUSIC_METADATA
    assert "/api/v1/resolve/spotify" in API


def test_external_metadata_schema_updates_catalog_revision(monkeypatch, tmp_path):
    path = tmp_path / "meta.db"
    _use_db(monkeypatch, path)
    db.init_db()
    db.upsert_issue("RMF", "2026-10-01", "x", 20, [
        {"position": 1, "artist": "Artist", "title": "Song"},
    ])
    with db.connect() as con:
        song_id = int(con.execute("SELECT id FROM songs WHERE artist='Artist' AND title='Song'").fetchone()[0])
        cols = {r[1] for r in con.execute("PRAGMA table_info(song_external_metadata)")}
    assert {"spotify_url", "musicbrainz_recording_mbid", "release_checked_at"} <= cols

    before = db.catalog_revision()
    db.save_external_song_metadata(
        song_id,
        musicbrainz_recording_mbid="12345678-1234-1234-1234-123456789abc",
        spotify_track_id="1234567890123456789012",
        spotify_url="https://open.spotify.com/track/1234567890123456789012",
        release_date="2024-03-15",
        release_date_source="MusicBrainz",
        release_date_precision="day",
        release_checked=True,
        spotify_checked=True,
    )
    after = db.catalog_revision()
    assert before != after
    assert db.get_song(song_id)["release_date"] == "2024-03-15"
    assert db.external_metadata_for_song_ids([song_id])[song_id]["spotify_url"].startswith("https://open.spotify.com/track/")


def test_musicbrainz_uses_isrc_and_first_release_date(monkeypatch):
    seen = {}

    class Resp:
        def raise_for_status(self):
            pass
        def json(self):
            return {"recordings": [{
                "id": "12345678-1234-1234-1234-123456789abc",
                "score": 100,
                "title": "Example Song",
                "artist-credit": [{"name": "Example Artist"}],
                "first-release-date": "2025-04-03",
            }]}

    def fake_get(url, params, headers, timeout):
        seen.update(params)
        return Resp()

    monkeypatch.setattr(mm.requests, "get", fake_get)
    match = mm.lookup_musicbrainz_recording("Example Artist", "Example Song", isrc="PL-ABC-25-00001")
    assert seen["query"] == "isrc:PLABC2500001"
    assert match is not None
    assert match.release_date == "2025-04-03"
    assert match.release_precision == "day"


def test_listenbrainz_metadata_returns_direct_spotify_url(monkeypatch):
    class Resp:
        def raise_for_status(self):
            pass
        def json(self):
            return [{"spotify_track_ids": ["4uLU6hMCjMI75M1A2tKUQC"]}]

    monkeypatch.setattr(mm.requests, "post", lambda *a, **kw: Resp())
    assert mm.resolve_spotify_url("Rick Astley", "Never Gonna Give You Up") == \
        "https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC"
