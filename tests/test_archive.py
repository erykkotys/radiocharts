import radiocharts.db as db


def test_archive_lists_issues_and_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "archive.db")
    db.init_db()
    issue_id = db.upsert_issue("TEST", "2026-08-11", "i1", 2, [
        {"position": 1, "artist": "A", "title": "One"},
        {"position": 2, "artist": "B", "title": "Two"},
    ])
    issues = db.list_issues("TEST")
    assert len(issues) == 1
    assert issues[0]["entries"] == 2
    rows = db.issue_entries(issue_id)
    assert [r["position"] for r in rows] == [1, 2]
