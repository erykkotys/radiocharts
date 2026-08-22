from datetime import date

import radiocharts.db as db
import radiocharts.metrics as metrics


def _use_db(monkeypatch, path):
    monkeypatch.setattr(db, "DB_PATH", path)
    monkeypatch.setattr(db, "_INITIALIZED_DB_PATH", None)


def test_0320_status_migration_and_dead_airplay_stations(tmp_path, monkeypatch):
    path = tmp_path / "workflow.db"
    _use_db(monkeypatch, path)
    db.init_db()

    legacy = [
        (1, "Ignore", "Poza formatem"),
        (2, "Candidate", "CF Candidate"),
        (3, "Current", "Baza CF2"),
        (4, "Current Familiar", "Baza CF1"),
        (5, "Recurrent", "Baza R1"),
        (6, "Poza bazą", "Baza Hold"),
    ]
    dead_names = ["Brak nazwy #7", "Freee", "RDN Małopolska", "Radiofonia", "Łódź Extra"]

    with db.connect() as con:
        # Re-run only the new migrations against a legacy-shaped state.
        con.execute("DELETE FROM app_meta WHERE key IN ('status_taxonomy_v2','airplay_dead_station_cleanup_v1')")
        for sid, old, _ in legacy:
            con.execute(
                "INSERT OR REPLACE INTO songs(id,artist,title,artist_key,title_key,release_date,created_at) VALUES(?,?,?,?,?,?,?)",
                (sid, f"Artist {sid}", f"Song {sid}", f"artist {sid}", f"song {sid}", None, "2026-01-01T00:00:00Z"),
            )
            con.execute(
                "INSERT OR REPLACE INTO song_notes(song_id,heard,status,note,updated_at) VALUES(?,?,?,?,?)",
                (sid, 0, old, "", "2026-01-01T00:00:00Z"),
            )
        for i, name in enumerate(dead_names, start=100):
            con.execute(
                "INSERT OR REPLACE INTO airplay_stations(station_id,name,active,discovered_at,updated_at) VALUES(?,?,?,?,?)",
                (i, name, 1, "", ""),
            )
        con.execute(
            "INSERT OR REPLACE INTO airplay_stations(station_id,name,active,discovered_at,updated_at) VALUES(?,?,?,?,?)",
            (999, "RMF FM", 1, "", ""),
        )

    monkeypatch.setattr(db, "_INITIALIZED_DB_PATH", None)
    db.init_db()

    with db.connect() as con:
        got = {int(r[0]): str(r[1]) for r in con.execute("SELECT song_id,status FROM song_notes")}
        for sid, _, expected in legacy:
            assert got[sid] == expected
        inactive = {str(r[0]) for r in con.execute("SELECT name FROM airplay_stations WHERE active=0")}
        assert set(dead_names) <= inactive
        assert con.execute("SELECT active FROM airplay_stations WHERE name='RMF FM'").fetchone()[0] == 1


def test_0320_airplay_summary_exposes_release_or_first_chart_month_source(tmp_path, monkeypatch):
    _use_db(monkeypatch, tmp_path / "release.db")
    db.init_db()
    db.upsert_issue("RMF", "2026-06-12", "issue", 20, [
        {"position": 7, "artist": "Artist", "title": "Track"},
    ])
    db.upsert_airplay_stations([{"station_id": 2, "name": "RMF FM"}])
    db.store_airplay_window(2, "RMF FM", "2026-08-20", 10, [
        {"played_at": "2026-08-20T10:05", "artist": "Artist", "title": "Track"},
    ])

    row = db.airplay_summary([2], date(2026, 8, 20), date(2026, 8, 20))[0]
    assert row["release_date"] is None
    assert row["first_chart_date"] == "2026-06-12"


def test_0320_scores_keep_earliest_chart_date_for_release_month_fallback(tmp_path, monkeypatch):
    _use_db(monkeypatch, tmp_path / "first-chart.db")
    db.init_db()
    db.upsert_issue("RMF", "2026-06-05", "old", 20, [
        {"position": 12, "artist": "Artist", "title": "Track"},
    ])
    db.upsert_issue("RMF", "2026-08-21", "new", 20, [
        {"position": 4, "artist": "Artist", "title": "Track"},
    ])

    row = metrics.compute_scores(as_of="2026-08-21").iloc[0]
    assert row["first_chart_date"] == "2026-06-05"
