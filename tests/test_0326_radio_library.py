from pathlib import Path

import radiocharts.db as db

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "radiocharts" / "app.py").read_text(encoding="utf-8")


def _use_db(monkeypatch, path):
    monkeypatch.setattr(db, "DB_PATH", path)
    monkeypatch.setattr(db, "_INITIALIZED_DB_PATH", None)
    monkeypatch.setenv("RADIOCHARTS_AUTO_LIBRARY_SEED", "0")


def test_0326_bundled_radio_library_contains_full_user_export():
    seed = ROOT / "radiocharts" / "data" / "radio_library_seed_20260825.tsv"
    rows, meta = db.parse_radio_library_tsv(seed.read_text(encoding="utf-8"))
    assert len(rows) == 928
    assert meta["categories"] == {
        "G2": 287, "R2": 189, "G1": 136, "R1": 117, "SP2": 63,
        "SP1": 41, "CF2": 40, "CF1": 29, "NB": 18, "F1": 8,
    }


def test_0326_radio_library_sync_adds_missing_and_updates_existing(tmp_path, monkeypatch):
    _use_db(monkeypatch, tmp_path / "sync.db")
    db.init_db()
    db.upsert_issue(
        "RMF", "2026-08-20", "rmf-x", 20,
        [{"position": 1, "artist": "James Blunt", "title": "1973"}],
    )
    with db.connect() as con:
        sid = con.execute("SELECT id FROM songs WHERE title_key='1973'").fetchone()[0]
    db.update_note(sid, True, "Watch", "zostaw notatkę", downloaded=False)

    text = (
        "Active\tCat\tPack\tVer\tTitle\tArtist\tAlbum\tRuntime\n"
        "Checked\tR2\t\t\t1973\tJAMES BLUNT\t\t03:55\n"
        "Checked\tF1\t\t\tNowy Test\tNowy Artysta\t\t03:00\n"
    )
    result = db.sync_radio_library_tsv(text)
    assert result["processed"] == 2
    assert result["matched"] == 1
    assert result["added"] == 1

    with db.connect() as con:
        existing = con.execute(
            "SELECT n.heard,n.status,n.downloaded,n.note FROM song_notes n WHERE n.song_id=?", (sid,)
        ).fetchone()
        assert tuple(existing) == (1, "Baza R2", 1, "zostaw notatkę")
        new = con.execute(
            """SELECT s.artist,s.title,n.status,n.downloaded
               FROM songs s JOIN song_notes n ON n.song_id=s.id
               WHERE s.artist_key=? AND s.title_key=?""",
            (db.normalize("Nowy Artysta"), db.normalize("Nowy Test")),
        ).fetchone()
        assert tuple(new) == ("Nowy Artysta", "Nowy Test", "Baza F1", 1)


def test_0326_status_taxonomy_covers_every_radio_category():
    for code in db.RADIO_LIBRARY_CATEGORIES:
        assert f'"{code} Candidate"' in APP
        assert f'"Baza {code}"' in APP


def test_0326_airplay_has_period_reach_compact_weeks_and_workflow_order():
    assert '"stations_count", "Zasięg"' in APP
    assert "return '#' + Math.round(v) + ' (' + weekLabel + ')'" in APP
    assert 'compact_initial = source_layout in {"compact", "airplay"}' in APP
    assert '"RMF", "RMF_weeks", "ZET", "ZET_weeks"' in APP
    assert '"details", "preview", "heard", "status", "downloaded", "spotify", "spotify_copy"' in APP


def test_0326_data_tab_exposes_radio_library_sync():
    assert 'st.file_uploader(' in APP
    assert '"🎵 Synchronizacja bazy radia"' in APP
    assert 'sync_radio_library_tsv(radio_text)' in APP


def test_0326_auto_seed_can_be_forced_for_deploy_migration(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "seed.db")
    monkeypatch.setattr(db, "_INITIALIZED_DB_PATH", None)
    monkeypatch.setenv("RADIOCHARTS_AUTO_LIBRARY_SEED", "1")
    db.init_db()
    with db.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM songs").fetchone()[0] == 928
        assert con.execute("SELECT COUNT(*) FROM song_notes WHERE downloaded=1").fetchone()[0] == 928
        assert con.execute("SELECT COUNT(*) FROM song_notes WHERE status='Baza F1'").fetchone()[0] == 8
        marker = con.execute("SELECT value FROM app_meta WHERE key='radio_library_seed_20260825_v1'").fetchone()[0]
        assert "rows=928" in marker
