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


def test_source_check_day_summary_keeps_day_green_after_later_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "checks_day.db")
    monkeypatch.setattr(db, "_INITIALIZED_DB_PATH", None)
    db.init_db()
    stamps = iter([
        "2026-08-13T05:31:00.000000+00:00",  # 07:31 Poland summer time
        "2026-08-13T18:31:00.000000+00:00",  # 20:31 Poland summer time
    ])
    monkeypatch.setattr(db, "_utcnow", lambda: next(stamps))
    db.record_source_check("OLIA", True, "morning ok", "2026-08-07", "week32")
    db.record_source_check("OLIA", False, "evening timeout")

    rows = db.source_check_day_summary(day=db.date(2026, 8, 13))
    assert len(rows) == 1
    row = rows[0]
    assert row["source"] == "OLIA"
    assert row["success_today"] is True
    assert row["attempts_today"] == 2
    assert row["successes_today"] == 1
    assert row["latest_attempt_success"] is False
    assert row["latest_success_message"] == "morning ok"
