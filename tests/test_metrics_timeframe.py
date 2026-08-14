import radiocharts.db as db
import radiocharts.metrics as metrics


def test_compute_scores_lookback_excludes_old_only_songs(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "timeframe.db")
    monkeypatch.setattr(db, "_INITIALIZED_DB_PATH", None)
    db.init_db()
    db.upsert_issue("RMF", "2026-07-01", "old", 20, [
        {"position": 1, "artist": "Old", "title": "Only"},
        {"position": 2, "artist": "Still", "title": "Here"},
    ])
    db.upsert_issue("RMF", "2026-08-14", "new", 20, [
        {"position": 10, "artist": "Still", "title": "Here"},
    ])

    all_scores = metrics.compute_scores(as_of="2026-08-14")
    recent = metrics.compute_scores(as_of="2026-08-14", lookback_days=7)
    assert set(all_scores["title"]) == {"Only", "Here"}
    assert set(recent["title"]) == {"Here"}
    assert int(recent.iloc[0]["lookback_days"]) == 7
