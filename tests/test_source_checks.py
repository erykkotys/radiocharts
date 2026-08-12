import radiocharts.db as db


def test_source_checks_keep_latest_attempt(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "checks.db")
    db.init_db()
    db.record_source_check("RMF", True, "ok", "2026-08-11", "6183")
    db.record_source_check("RMF", False, "timeout")
    rows = db.latest_source_checks()
    assert len(rows) == 1
    assert rows[0]["source"] == "RMF"
    assert rows[0]["success"] == 0
    assert rows[0]["message"] == "timeout"
