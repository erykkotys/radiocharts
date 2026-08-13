from datetime import date

import radiocharts.collector as collector


def _issue(day: date, archive_id=None):
    return {
        "source": "ZET",
        "chart_date": day.isoformat(),
        "issue_key": day.isoformat(),
        "chart_size": 20,
        "source_url": str(archive_id or "current"),
        "entries": [
            {"position": i, "artist": f"Artist {i}", "title": f"Song {i}"}
            for i in range(1, 21)
        ],
    }


def test_zet_backfill_skips_weekends_and_counts_chart_issues(tmp_path, monkeypatch):
    # Wed 12 Aug -> Tue 11 -> Mon 10 -> Fri 7 -> Thu 6. Weekend 8/9 is skipped.
    known = {
        date(2026, 8, 11): 23845,
        date(2026, 8, 10): 23840,
        date(2026, 8, 7): 23825,
        date(2026, 8, 6): 23820,
    }
    reverse = {v: k for k, v in known.items()}

    def fake_fetch(archive_id=None, timeout=10):
        if archive_id is None:
            return _issue(date(2026, 8, 12))
        if archive_id in reverse:
            return _issue(reverse[archive_id], archive_id)
        raise ValueError("missing")

    monkeypatch.setattr(collector, "fetch_zet", fake_fetch)
    monkeypatch.setattr(collector, "store", lambda data: 1)
    monkeypatch.setattr(collector, "LOCK_PATH", tmp_path / "collector.lock")
    monkeypatch.setattr(collector, "_zet_predicted_archive_id", lambda d: known.get(d, 23800))

    msgs = collector.backfill_zet(5, pause_seconds=0)
    assert len(msgs) == 5
    assert any("2026-08-07: OK" in m for m in msgs)
    assert not any("2026-08-09" in m or "2026-08-08" in m for m in msgs)
