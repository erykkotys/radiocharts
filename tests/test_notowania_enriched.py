import radiocharts.db as db


def test_issue_entries_enriched_derives_previous_weeks_peak(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "enriched.db")
    monkeypatch.setattr(db, "_INITIALIZED_DB_PATH", None)
    db.init_db()
    db.upsert_issue("RMF", "2026-08-03", "1", 20, [
        {"position": 10, "artist": "Artist", "title": "Song"},
    ])
    issue2 = db.upsert_issue("RMF", "2026-08-10", "2", 20, [
        {"position": 5, "artist": "Artist", "title": "Song"},
    ])
    row = db.issue_entries_enriched(issue2)[0]
    assert row["previous_position"] == 10
    assert row["reported_weeks"] == 2
    assert row["reported_peak"] == 5
