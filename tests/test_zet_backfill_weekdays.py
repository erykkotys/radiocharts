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


def test_zet_backfill_walks_real_ids_and_does_not_skip_weekends(tmp_path, monkeypatch):
    # Deliberately irregular IDs and dates.  Sunday exists; Saturday does not.
    known = {
        23845: date(2026, 8, 11),
        23840: date(2026, 8, 10),
        23825: date(2026, 8, 9),   # Sunday must NOT be skipped.
        23810: date(2026, 8, 7),
    }

    def fake_fetch(archive_id=None, timeout=10):
        if archive_id is None:
            return _issue(date(2026, 8, 12))
        if archive_id in known:
            return _issue(known[archive_id], archive_id)
        raise ValueError("missing")

    monkeypatch.setattr(collector, "fetch_zet", fake_fetch)
    monkeypatch.setattr(collector, "store", lambda data: 1)
    monkeypatch.setattr(collector, "LOCK_PATH", tmp_path / "collector.lock")
    monkeypatch.setattr(collector, "_zet_predicted_archive_id", lambda d: 23845)

    msgs = collector.backfill_zet(5, pause_seconds=0)
    assert sum(": OK" in m for m in msgs) == 5
    assert any("2026-08-09: OK" in m for m in msgs)
    assert any("2026-08-07: OK" in m for m in msgs)
    assert not any("2026-08-08" in m for m in msgs)


def test_zet_backfill_stops_cleanly_when_id_gap_is_too_large(tmp_path, monkeypatch):
    known = {23845: date(2026, 8, 11)}

    def fake_fetch(archive_id=None, timeout=10):
        if archive_id is None:
            return _issue(date(2026, 8, 12))
        if archive_id in known:
            return _issue(known[archive_id], archive_id)
        raise ValueError("missing")

    monkeypatch.setattr(collector, "fetch_zet", fake_fetch)
    monkeypatch.setattr(collector, "store", lambda data: 1)
    monkeypatch.setattr(collector, "LOCK_PATH", tmp_path / "collector.lock")
    monkeypatch.setattr(collector, "_zet_predicted_archive_id", lambda d: 23845)

    msgs = collector.backfill_zet(4, pause_seconds=0)
    assert sum(": OK" in m for m in msgs) == 2
    assert any("przerwano po 2/4" in m for m in msgs)
