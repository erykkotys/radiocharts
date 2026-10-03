from __future__ import annotations

from pathlib import Path

import radiocharts.db as db
from radiocharts.local_station import (
    compare_hour,
    events_for_day,
    import_zetta2go_snapshot,
    parse_zetta2go_log,
)

ROOT = Path(__file__).resolve().parents[1]


def _use_db(monkeypatch, path):
    monkeypatch.setattr(db, "DB_PATH", path)
    monkeypatch.setattr(db, "_INITIALIZED_DB_PATH", None)
    monkeypatch.setenv("RADIOCHARTS_AUTO_LIBRARY_SEED", "0")


def _asset_row(
    *,
    seq: int,
    at: str,
    uid: str,
    asset_id: str,
    title: str,
    artist: str = "Artist",
    status: int = 1,
    edit: int = 0,
    asset_type: int = 1,
    runtime_ms: int = 180_000,
):
    asset = {
        "AssetID": asset_id,
        "AssetTypeID": asset_type,
        "Artist": artist if asset_type == 1 else None,
        "Sponsor": None,
        "UniversalIdentifier": uid,
        "LogEventTypeID": 106,
        "Title": title,
        "Runtime": "03:00",
        "DurationRuntime": "03:00",
        "ChainType": 1,
    }
    return {
        "id": uid,
        "cell": [
            "106", seq, str(edit), True, "", at, "", asset, "", str(status), "1",
            False, False, 1, "", runtime_ms,
            {"AirTime": at, "NextETM": "7:00:00 AM", "GapToETM": 0},
            "group", runtime_ms, "", 0, None, True, False,
        ],
    }


def _etm_row(*, seq: int, at: str, uid: str, etm_type: str = "Hard", status: int = 1, gap: int | None = 0):
    return {
        "id": uid,
        "cell": [
            "15", seq, "0", True, "", at, "", {"ETMType": etm_type, "time": "6:30:00 AM", "gap": gap, "ogap": None},
            "", str(status), "1", False, False, 1, "", 0,
            {"AirTime": at, "NextETM": "7:00:00 AM", "GapToETM": 0},
            "group", 0, "", 0, None, True, False,
        ],
    }


def _payload(*rows):
    return {"total": 1, "page": 1, "records": len(rows), "rows": list(rows)}


def _toh_row(*, at: str, uid: str):
    return {
        "id": uid,
        "cell": [
            "3", 0, "0", True, "", at, "", f"Top of Hour - {at}", "", "1", "1",
            False, False, 1, "", 0, {}, "group", 0, "", 0, None, True, False,
        ],
    }


def test_zetta_schedule_keeps_ready_rows_and_stable_log_event_id():
    payload = _payload(
        _asset_row(seq=1, at="2026-10-04T06:00:00.0000000", uid="evt-song", asset_id="asset-a", title="Song A", status=1),
        _etm_row(seq=2, at="2026-10-04T06:30:00.0000000+02:00", uid="evt-etm", gap=93000),
    )
    rows = parse_zetta2go_log(payload, "2026-10-04", kind="schedule")
    assert len(rows) == 2
    assert rows[0]["play_status_code"] == 1
    assert rows[0]["external_id"] == "evt-song"
    assert rows[1]["event_type"] == "etm"
    assert rows[1]["payload"]["zetta_gap_ms"] == 93000


def test_zetta_cutoff_vs_live_uses_event_guid_and_status_reason(tmp_path, monkeypatch):
    _use_db(monkeypatch, tmp_path / "zetta.db")
    schedule = _payload(
        _asset_row(seq=1, at="2026-10-04T06:00:00.0000000", uid="evt-1", asset_id="asset-a", title="Song A", status=1),
        _asset_row(seq=2, at="2026-10-04T06:04:00.0000000", uid="evt-2", asset_id="asset-b", title="Song B", status=1),
    )
    live = _payload(
        _asset_row(seq=1, at="2026-10-04T06:00:05.0000000", uid="evt-1", asset_id="asset-a", title="Song A", status=3),
        _asset_row(seq=2, at="2026-10-04T06:04:00.0000000", uid="evt-2", asset_id="asset-b", title="Song B", status=4, edit=302),
    )
    import_zetta2go_snapshot(schedule, service_date="2026-10-04", kind="schedule", source="zetta2go-cutoff")
    import_zetta2go_snapshot(live, service_date="2026-10-04", kind="played", replace_live=True)
    result = compare_hour("2026-10-04", 6)
    by_title = {r["title"]: r for r in result["rows"]}
    assert by_title["Song A"]["status"] == "OK"
    assert by_title["Song B"]["status"] == "Niezagrane"
    assert "future ETM" in by_title["Song B"]["note"]
    assert result["missed"] == 1


def test_zetta_live_ready_is_waiting_and_asset_replacement_is_intervention(tmp_path, monkeypatch):
    _use_db(monkeypatch, tmp_path / "zetta-live.db")
    schedule = _payload(
        _asset_row(seq=1, at="2026-10-04T12:00:00.0000000", uid="evt-1", asset_id="asset-a", title="Old", status=1),
        _asset_row(seq=2, at="2026-10-04T12:03:00.0000000", uid="evt-2", asset_id="asset-b", title="Waiting", status=1),
    )
    live = _payload(
        _asset_row(seq=1, at="2026-10-04T12:00:00.0000000", uid="evt-1", asset_id="asset-new", title="New", status=1, edit=216),
        _asset_row(seq=2, at="2026-10-04T12:03:00.0000000", uid="evt-2", asset_id="asset-b", title="Waiting", status=1),
    )
    import_zetta2go_snapshot(schedule, service_date="2026-10-04", kind="schedule", source="zetta2go-cutoff")
    first = import_zetta2go_snapshot(live, service_date="2026-10-04", kind="played", replace_live=True)
    second = import_zetta2go_snapshot(live, service_date="2026-10-04", kind="played", replace_live=True)
    assert first["import_id"] == second["import_id"]
    assert second["unchanged"] is True
    result = compare_hour("2026-10-04", 12)
    statuses = {r["title"]: r["status"] for r in result["rows"]}
    assert statuses["Old"] == "Zmieniony"
    assert statuses["Waiting"] == "Oczekuje"
    assert result["changed"] == 1
    assert result["waiting"] == 1
    with db.connect() as con:
        count = con.execute("SELECT COUNT(*) FROM local_station_imports WHERE kind='played'").fetchone()[0]
    assert count == 1


def test_played_timeline_hides_ready_but_reconciliation_storage_keeps_it(tmp_path, monkeypatch):
    _use_db(monkeypatch, tmp_path / "zetta-filter.db")
    live = _payload(
        _asset_row(seq=1, at="2026-10-04T10:00:00.0000000", uid="played", asset_id="a", title="Played", status=3),
        _asset_row(seq=2, at="2026-10-04T10:03:00.0000000", uid="ready", asset_id="b", title="Future", status=1),
    )
    import_zetta2go_snapshot(live, service_date="2026-10-04", kind="played", replace_live=True)
    assert [r["title"] for r in events_for_day("played", "2026-10-04")] == ["Played"]
    all_rows = events_for_day("played", "2026-10-04", include_nonplayed=True)
    assert {r["title"] for r in all_rows} == {"Played", "Future"}


def test_129_scheduler_and_login_contract():
    scheduler = (ROOT / "radiocharts/scheduler.py").read_text(encoding="utf-8")
    client = (ROOT / "radiocharts/zetta2go.py").read_text(encoding="utf-8")
    assert 'CronTrigger(hour=23, minute=59, second=20' in scheduler
    assert 'CronTrigger(minute="*", second=5' in scheduler
    assert 'zetta_schedule_job(mark_cutoff=False)' in scheduler
    assert '"userName": self.cfg.username' in client
    assert '"pwText": ""' in client
    assert '"password": self.cfg.password' in client
    assert '"isSmallFormFactor": "0"' in client


def test_zetta_full_day_merged_hours_reset_toh_grouping():
    payload = _payload(
        _toh_row(at="2026-10-04T00:00:00.0000000", uid="toh-00"),
        _asset_row(seq=1, at="2026-10-04T00:58:00.0000000", uid="evt-0058", asset_id="a0", title="Late 00"),
        # Legitimate overtime before the next hourly response's TOH row.
        _asset_row(seq=2, at="2026-10-04T01:00:10.0000000", uid="evt-0060", asset_id="a1", title="Overrun 00"),
        _toh_row(at="2026-10-04T01:00:00.0000000", uid="toh-01"),
        _asset_row(seq=3, at="2026-10-04T01:08:40.2000000", uid="evt-0108", asset_id="a2", title="Normal 01"),
    )
    rows = parse_zetta2go_log(payload, "2026-10-04", kind="schedule")
    by_title = {r["title"]: r for r in rows}
    assert by_title["Late 00"]["air_time_raw"] == "00:58:00.0"
    assert by_title["Overrun 00"]["air_time_raw"] == "00:60:10.0"
    assert by_title["Overrun 00"]["schedule_hour"] == 0
    assert by_title["Normal 01"]["air_time_raw"] == "01:08:40.2"
    assert by_title["Normal 01"]["schedule_hour"] == 1


def test_zetta_client_get_log_fetches_24_hour_windows(monkeypatch):
    from datetime import date as dt_date
    from radiocharts.zetta2go import Zetta2GoClient, Zetta2GoSettings

    cfg = Zetta2GoSettings(
        base_url="https://example.invalid/Zetta2GO", station_id="station",
        username="u", password="p", verify_tls=False, timeout=1,
        schedule_horizon_days=14, live_enabled=True, schedule_enabled=True,
    )
    client = Zetta2GoClient(cfg)
    calls = []

    def fake_range(start, end):
        calls.append((start, end))
        hour = start.hour
        return _payload(
            _toh_row(at=f"2026-10-04T{hour:02d}:00:00.0000000", uid=f"toh-{hour:02d}"),
            _asset_row(
                seq=1, at=f"2026-10-04T{hour:02d}:05:00.0000000",
                uid=f"evt-{hour:02d}", asset_id=f"asset-{hour:02d}", title=f"Hour {hour:02d}",
            ),
        )

    monkeypatch.setattr(client, "get_log_range", fake_range)
    payload = client.get_log(dt_date(2026, 10, 4))
    assert len(calls) == 24
    assert calls[0][0].hour == 0 and calls[0][1].hour == 0
    assert calls[-1][0].hour == 23 and calls[-1][1].hour == 23
    assert payload["records"] == 48
    parsed = parse_zetta2go_log(payload, "2026-10-04", kind="schedule")
    assert len(parsed) == 24
    assert {r["schedule_hour"] for r in parsed} == set(range(24))
    assert next(r for r in parsed if r["title"] == "Hour 01")["air_time_raw"] == "01:05:00.0"
