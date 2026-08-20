import radiocharts.db as db


def test_latest_chart_positions_only_returns_latest_issue_per_source(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "latest.db")
    monkeypatch.setattr(db, "_INITIALIZED_DB_PATH", None)
    db.init_db()
    db.upsert_issue("RMF", "2026-08-19", "a", 20, [
        {"position": 1, "artist": "A", "title": "Old"},
    ])
    db.upsert_issue("RMF", "2026-08-20", "b", 20, [
        {"position": 2, "artist": "B", "title": "New"},
    ])
    rows = db.latest_chart_positions()
    assert len(rows) == 1
    assert rows[0]["source"] == "RMF"
    assert rows[0]["position"] == 2
