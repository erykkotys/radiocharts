from __future__ import annotations

from pathlib import Path
import json

import radiocharts.db as db
from radiocharts.local_station import (
    compare_hour,
    events_for_day,
    import_gselector_export,
    import_zetta2go_snapshot,
    parse_zetta2go_log,
)

ROOT = Path(__file__).resolve().parents[1]


def _use_db(monkeypatch, path):
    monkeypatch.setattr(db, "DB_PATH", path)
    monkeypatch.setattr(db, "_INITIALIZED_DB_PATH", None)
    monkeypatch.setenv("RADIOCHARTS_AUTO_LIBRARY_SEED", "0")


def _gselector_song(at: str, artist: str, title: str, ext: str, runtime: str = "03:00.0") -> str:
    cols = [
        at, "CF1/FAMILIAR CURRENT", "3", "5", artist, title, "Stretch", "YES", "", "5", "2", "0",
        at, "", runtime, "Male", ext, "0", "0", "False", at,
    ]
    return "\t".join(f'"{value}"' for value in cols)


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


def _etm_row(
    *,
    seq: int,
    at: str,
    uid: str,
    etm_type: str = "Hard",
    status: int = 1,
    gap: int | float | str | None = 0,
    hit_gap: int | float | str | None = None,
    original_gap: int | float | str | None = None,
    calculated: dict | None = None,
    asset_gap: int | float | None = None,
):
    calculated_times = calculated if calculated is not None else {
        "AirTime": at,
        "NextETM": "7:00:00 AM",
        "HitETMGap": hit_gap,
        "GapToETM": gap,
        "OriginalGap": original_gap,
    }
    return {
        "id": uid,
        "cell": [
            "15", seq, "0", True, "", at, "",
            {"ETMType": etm_type, "time": "6:30:00 AM", "gap": asset_gap, "ogap": None},
            "", str(status), "1", False, False, 1, "", 0,
            calculated_times,
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
    assert result["played_actual"] == 0
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



def test_zetta_hour_boundary_uses_only_calculated_times_and_never_carries_previous_hour():
    previous = _payload(
        _toh_row(at="2026-10-03T23:00:00.0000000", uid="toh-prev"),
        _etm_row(seq=90, at="2026-10-03T23:59:59.0000000", uid="reset-prev", etm_type="Reset", gap=14000),
    )
    payload = _payload(
        _toh_row(at="2026-10-04T00:00:00.0000000", uid="toh-00"),
        _etm_row(seq=1, at="2026-10-04T00:00:00.0000000", uid="soft-00", etm_type="Soft", gap=0),
        _toh_row(at="2026-10-04T05:00:00.0000000", uid="toh-05"),
        _etm_row(seq=2, at="2026-10-04T05:59:59.0000000", uid="reset-0559", etm_type="Reset", gap=-10000),
        _toh_row(at="2026-10-04T06:00:00.0000000", uid="toh-06"),
        _etm_row(seq=3, at="2026-10-04T06:00:00.0000000", uid="hard-06", etm_type="Hard", gap=0),
        _toh_row(at="2026-10-04T07:00:00.0000000", uid="toh-07"),
        _etm_row(seq=4, at="2026-10-04T07:00:00.0000000", uid="hard-07", etm_type="Hard", gap=4200),
        _etm_row(seq=5, at="2026-10-04T07:30:00.0000000", uid="hard-0730", etm_type="Hard", gap=0),
        _asset_row(seq=6, at="2026-10-04T07:58:00.0000000", uid="tail-07", asset_id="tail-a", title="Tail", runtime_ms=134000),
        _toh_row(at="2026-10-04T08:00:00.0000000", uid="toh-08"),
        _etm_row(seq=7, at="2026-10-04T08:00:00.0000000", uid="hard-08", etm_type="Hard", gap=0),
    )
    payload["radiocharts_previous_hour_rows"] = previous["rows"]
    rows = parse_zetta2go_log(payload, "2026-10-04", kind="schedule")
    by_id = {r["external_id"]: r for r in rows}

    # No carry from 23:59 RESET, no reconstruction from 07:58 runtime.
    assert by_id["soft-00"]["etm_delta_raw"] == "+00:00"
    assert by_id["hard-06"]["etm_delta_raw"] == "+00:00"
    assert by_id["hard-08"]["etm_delta_raw"] == "+00:00"
    # A native CalculatedTimes value is shown exactly as supplied.
    assert by_id["hard-07"]["etm_delta_raw"] == "+00:04.2"
    assert by_id["hard-07"]["payload"]["zetta_gap_source"] == "CalculatedTimes.GapToETM"


def test_1230_legacy_stored_guess_is_overridden_by_native_calculated_times(tmp_path, monkeypatch):
    _use_db(monkeypatch, tmp_path / "zetta-native-read.db")
    payload = _payload(
        _etm_row(
            seq=1, at="2026-10-04T06:30:00.0000000+02:00", uid="legacy-etm",
            etm_type="Hard", gap=1234,
        )
    )
    import_zetta2go_snapshot(payload, service_date="2026-10-04", kind="schedule")

    # Simulate an older RadioCharts snapshot: CalculatedTimes was already stored,
    # but the cached/display gap was later replaced by a guessed carry value.
    with db.connect() as con:
        row = con.execute(
            "SELECT id,payload_json FROM local_station_events WHERE external_id=?",
            ("legacy-etm",),
        ).fetchone()
        stored = json.loads(row["payload_json"])
        stored["zetta_gap_ms"] = 999999
        stored["zetta_gap_native_ms"] = 999999
        stored["zetta_gap_source"] = "previous_hour_tail"
        con.execute(
            "UPDATE local_station_events SET payload_json=? WHERE id=?",
            (json.dumps(stored), row["id"]),
        )

    rows = events_for_day("schedule", "2026-10-04")
    assert len(rows) == 1
    etm = rows[0]
    assert etm["zetta_gap_ms"] == 1234
    assert etm["zetta_gap_native_ms"] == 1234
    assert etm["zetta_gap_source"] == "CalculatedTimes.GapToETM"
    assert etm["etm_delta_raw"] == "+00:01.2"


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
        day = start.date().isoformat()
        if day == "2026-10-03":
            return _payload(
                _toh_row(at="2026-10-03T23:00:00.0000000", uid="prev-toh"),
                _etm_row(seq=1, at="2026-10-03T23:59:59.0000000", uid="prev-reset", etm_type="Reset", gap=5000),
            )
        return _payload(
            _toh_row(at=f"2026-10-04T{hour:02d}:00:00.0000000", uid=f"toh-{hour:02d}"),
            _asset_row(
                seq=1, at=f"2026-10-04T{hour:02d}:05:00.0000000",
                uid=f"evt-{hour:02d}", asset_id=f"asset-{hour:02d}", title=f"Hour {hour:02d}",
            ),
        )

    monkeypatch.setattr(client, "get_log_range", fake_range)
    payload = client.get_log(dt_date(2026, 10, 4))
    assert len(calls) == 25
    assert calls[0][0].date().isoformat() == "2026-10-03" and calls[0][0].hour == 23
    assert calls[1][0].hour == 0 and calls[1][1].hour == 0
    assert calls[-1][0].hour == 23 and calls[-1][1].hour == 23
    assert payload["records"] == 48
    assert len(payload["radiocharts_previous_hour_rows"]) == 2
    parsed = parse_zetta2go_log(payload, "2026-10-04", kind="schedule")
    assert len(parsed) == 48
    assert sum(1 for r in parsed if r["event_type"] == "toh") == 24
    assert sum(1 for r in parsed if r["event_type"] == "song") == 24
    assert {r["schedule_hour"] for r in parsed} == set(range(24))
    assert next(r for r in parsed if r["title"] == "Hour 01")["air_time_raw"] == "01:05:00.0"


def test_zetta_etm_calculated_times_field_priority_and_fallbacks():
    payload = _payload(
        _etm_row(
            seq=1, at="2026-10-04T20:59:00.0000000+02:00", uid="hit-both", etm_type="Hit",
            gap=2_547_688, hit_gap=2_581_609,
        ),
        _etm_row(
            seq=2, at="2026-10-04T21:05:00.0000000+02:00", uid="hit-fallback", etm_type="Hit",
            gap=-114, hit_gap=None,
        ),
        _etm_row(
            seq=3, at="2026-10-04T21:10:00.0000000+02:00", uid="hard-gap", etm_type="Hard",
            gap=-114, hit_gap=999999,
        ),
        _etm_row(
            seq=4, at="2026-10-04T21:15:00.0000000+02:00", uid="soft-original", etm_type="Soft",
            calculated={"AirTime": "x", "GapToETM": None, "OriginalGap": 12_345},
        ),
        _etm_row(
            seq=5, at="2026-10-04T21:20:00.0000000+02:00", uid="reset-generic", etm_type="Reset",
            calculated={"gap_time": "-00:01.500"},
        ),
    )
    rows = parse_zetta2go_log(payload, "2026-10-04", kind="schedule")
    by_id = {r["external_id"]: r for r in rows}

    assert by_id["hit-both"]["payload"]["zetta_gap_ms"] == 2_581_609
    assert by_id["hit-both"]["payload"]["zetta_gap_source"] == "CalculatedTimes.HitETMGap"
    assert by_id["hit-fallback"]["payload"]["zetta_gap_ms"] == -114
    assert by_id["hit-fallback"]["payload"]["zetta_gap_source"] == "CalculatedTimes.GapToETM"
    assert by_id["hard-gap"]["payload"]["zetta_gap_ms"] == -114
    assert by_id["hard-gap"]["payload"]["zetta_gap_source"] == "CalculatedTimes.GapToETM"
    assert by_id["soft-original"]["payload"]["zetta_gap_ms"] == 12_345
    assert by_id["soft-original"]["payload"]["zetta_gap_source"] == "CalculatedTimes.OriginalGap"
    assert by_id["reset-generic"]["payload"]["zetta_gap_ms"] == -1_500
    assert by_id["reset-generic"]["payload"]["zetta_gap_source"] == "CalculatedTimes.gap_time"


def test_zetta_etm_missing_calculated_gap_is_not_guessed_from_asset_or_timeline():
    payload = _payload(
        _toh_row(at="2026-10-04T15:00:00.0000000", uid="toh-15"),
        _asset_row(
            seq=1, at="2026-10-04T15:59:56.0000000", uid="crossing",
            asset_id="asset-crossing", title="Crossing item", runtime_ms=20_000,
        ),
        _toh_row(at="2026-10-04T16:00:00.0000000", uid="toh-16"),
        _etm_row(
            seq=2, at="2026-10-04T16:00:00.0000000", uid="hard-missing", etm_type="Hard",
            calculated={"AirTime": "2026-10-04T16:00:00", "GapToETM": None, "OriginalGap": None},
            asset_gap=16_000,
        ),
    )
    rows = parse_zetta2go_log(payload, "2026-10-04", kind="schedule")
    hard = next(r for r in rows if r["external_id"] == "hard-missing")
    assert hard["payload"]["zetta_gap_ms"] is None
    assert hard["payload"]["zetta_gap_source"] == ""
    assert hard["payload"]["zetta_asset_gap_ms"] == 16_000
    assert hard["etm_delta_raw"] == ""


def test_zetta_etm_gap_timespan_and_numeric_string_are_normalized_without_derivation():
    payload = _payload(
        _etm_row(
            seq=1, at="2026-10-04T10:00:00.0000000", uid="timespan", etm_type="Hard",
            calculated={"GapTime": "+00:00:03.250"},
        ),
        _etm_row(
            seq=2, at="2026-10-04T10:30:00.0000000", uid="numeric", etm_type="Soft",
            calculated={"Gap": "-2500"},
        ),
    )
    rows = parse_zetta2go_log(payload, "2026-10-04", kind="schedule")
    by_id = {r["external_id"]: r for r in rows}
    assert by_id["timespan"]["payload"]["zetta_gap_ms"] == 3250
    assert by_id["timespan"]["etm_delta_raw"] == "+00:03.2"
    assert by_id["numeric"]["payload"]["zetta_gap_ms"] == -2500
    assert by_id["numeric"]["etm_delta_raw"] == "-00:02.5"


def test_cross_system_gselector_cutoff_matches_zetta_played_by_text(tmp_path, monkeypatch):
    _use_db(monkeypatch, tmp_path / "mixed-source.db")
    import_gselector_export(
        _gselector_song("04:00:00.0", "Artist", "Same Song", "GSEL-123"),
        filename="03.10_schedule.txt",
        kind="schedule",
        start_date="2026-10-03",
    )
    live = _payload(
        _toh_row(at="2026-10-03T04:00:00.0000000", uid="toh-04"),
        _asset_row(
            seq=1,
            at="2026-10-03T04:00:12.0000000",
            uid="zetta-guid-unrelated-to-gselector",
            asset_id="asset-z",
            title="Same Song",
            artist="Artist",
            status=3,
        ),
    )
    import_zetta2go_snapshot(live, service_date="2026-10-03", kind="played", replace_live=True)
    result = compare_hour("2026-10-03", 4)
    assert result["matched"] == 1
    assert result["missed"] == 0
    assert result["added"] == 0
    assert result["differences"] == 0
    assert result["rows"][0]["status"] == "OK"


def test_future_waiting_rows_have_pending_ui_contract():
    app = (ROOT / "radiocharts/app.py").read_text(encoding="utf-8")
    assert "jeszcze nie zagrano — oczekuje w Zetta" in app
    assert '("Zagrane / w trakcie",totals["played_actual"])' in app


def test_1230_ui_uses_native_calculated_times_without_reset_or_hour_reconstruction():
    app = (ROOT / "radiocharts/app.py").read_text(encoding="utf-8")
    local = (ROOT / "radiocharts/local_station.py").read_text(encoding="utf-8")
    assert 'key="our_radio_etm_ignore_resets"' not in app
    assert "_local_apply_hour_boundary_gaps" not in app
    assert "_local_apply_ignore_reset_gaps" not in app
    assert "GetLog → cell[16]" in app
    assert "CalculatedTimes.HitETMGap" in local or "HitETMGap" in local
    assert "GapToETM" in local
    assert "OriginalGap" in local
