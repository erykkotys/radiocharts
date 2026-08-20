from datetime import date

import radiocharts.db as db


def _play(ts, artist, title):
    return {"played_at": ts, "artist": artist, "title": title}


def test_radio_presence_is_share_of_reporting_stations(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "presence.db")
    monkeypatch.setattr(db, "_INITIALIZED_DB_PATH", None)
    db.init_db()
    db.upsert_airplay_stations([
        {"station_id": 1, "name": "One"},
        {"station_id": 2, "name": "Two"},
        {"station_id": 3, "name": "Silent"},
    ])
    db.store_airplay_window(1, "One", "2026-08-20", 10, [
        _play("2026-08-20T10:05", "A", "Hit"),
        _play("2026-08-20T10:25", "B", "Half"),
    ])
    db.store_airplay_window(2, "Two", "2026-08-20", 10, [
        _play("2026-08-20T10:10", "A", "Hit"),
    ])
    db.store_airplay_window(3, "Silent", "2026-08-20", 10, [])

    snap = db.airplay_presence_summary(days=1, end_date=date(2026, 8, 20))
    assert snap["reporting_stations"] == 2
    by_title = {r["title"]: r for r in snap["rows"]}
    assert by_title["Hit"]["radio_presence"] == 100.0
    assert by_title["Half"]["radio_presence"] == 50.0
    assert by_title["Hit"]["airplay_spins_per_day"] == 2.0
    assert by_title["Hit"]["airplay_spins_per_station_day"] == 1.0


def test_station_coverage_distinguishes_missing_from_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "coverage.db")
    monkeypatch.setattr(db, "_INITIALIZED_DB_PATH", None)
    db.init_db()
    db.upsert_airplay_stations([
        {"station_id": 10, "name": "Empty"},
        {"station_id": 11, "name": "Missing"},
    ])
    db.store_airplay_window(10, "Empty", "2026-08-19", 0, [])
    rows = db.airplay_station_coverage([10, 11], date(2026, 8, 19), date(2026, 8, 19))
    by_id = {r["station_id"]: r for r in rows}
    assert by_id[10]["ok_windows"] == 1
    assert by_id[10]["zero_windows"] == 1
    assert by_id[10]["plays"] == 0
    assert by_id[11]["ok_windows"] == 0
    assert by_id[11]["zero_windows"] == 0


def test_discovery_refresh_preserves_manual_inactive_state(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "active.db")
    monkeypatch.setattr(db, "_INITIALIZED_DB_PATH", None)
    db.init_db()
    db.upsert_airplay_stations([{"station_id": 20, "name": "Dead", "active": True}])
    assert db.set_airplay_station_active([20], False) == 1

    # A later directory refresh still says active=True, but must not undo the
    # user's manual exclusion.
    db.upsert_airplay_stations([{"station_id": 20, "name": "Dead renamed", "active": True}])
    rows = db.list_airplay_stations(active_only=False)
    assert len(rows) == 1
    assert rows[0]["name"] == "Dead renamed"
    assert rows[0]["active"] == 0
