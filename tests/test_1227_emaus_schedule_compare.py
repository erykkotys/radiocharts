from __future__ import annotations

from pathlib import Path

import radiocharts.db as db
from radiocharts.local_station import (
    _schedule_hour,
    compare_day,
    compare_hour,
    events_for_day,
    import_gselector_export,
    import_zetta2go_snapshot,
)

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "radiocharts/app.py").read_text(encoding="utf-8")


def _use_db(monkeypatch, path):
    monkeypatch.setattr(db, "DB_PATH", path)
    monkeypatch.setattr(db, "_INITIALIZED_DB_PATH", None)
    monkeypatch.setenv("RADIOCHARTS_AUTO_LIBRARY_SEED", "0")


def _song(time: str, artist: str, title: str, ext: str) -> str:
    cols = [
        time, "G1", "3", "5", artist, title, "Stretch", "YES", "", "5", "2", "0",
        time, "", "04:00.0", "Male", ext, "0", "0", "False", time,
    ]
    return "\t".join(f'"{x}"' for x in cols)


def _zetta_asset(seq: int, at: str, uid: str, title: str, *, status: int, edit: int, skip: bool):
    asset = {
        "AssetID": f"asset-{uid}", "AssetTypeID": 1, "Artist": "Artist",
        "UniversalIdentifier": uid, "Title": title, "Runtime": "04:00", "DurationRuntime": "04:00",
        "CategoryCode": "G1",
    }
    return {
        "id": uid,
        "cell": [
            "106", seq, str(edit), True, "", at, "", asset, "", str(status), "1",
            skip, False, 1, "", 240_000, {"AirTime": at}, "group", 240_000, "", 0, None, True, False,
        ],
    }


def test_1229_schedule_has_calendar_arrows_today_and_etm_threshold_colors():
    assert "def _local_schedule_date_nav" in APP
    assert '"Dzisiaj", key=f"{key_prefix}_date_today"' in APP
    assert '"←", key=f"{key_prefix}_date_prev"' in APP
    assert '"→", key=f"{key_prefix}_date_next"' in APP
    assert 'format="DD.MM.YYYY"' in APP
    assert 'value <= -60.0' in APP and 'rc-etm-under' in APP
    assert 'value >= 180.0' in APP and 'rc-etm-over' in APP
    assert '.rc-etm-zero { opacity:1; }' in APP


def test_1229_boundary_seconds_normalize_but_60plus_minutes_keep_original_hour():
    assert _schedule_hour("00:59:60.0") == 1
    assert _schedule_hour("08:62:47.3") == 8


def test_1229_compare_day_counts_boundary_alias_once(tmp_path, monkeypatch):
    _use_db(monkeypatch, tmp_path / "boundary.db")
    import_gselector_export(
        _song("01:00:00.0", "Michael Jackson", "BILLIE JEAN", "ID-MJ"),
        filename="12.10_schedule.txt", kind="schedule", start_date="2026-10-12",
    )
    # Same logical event represented as previous-hour 60+ boundary in Played.
    import_gselector_export(
        _song("00:60:00.0", "Michael Jackson", "BILLIE JEAN", "ID-MJ"),
        filename="12.10_played.txt", kind="played", start_date="2026-10-12",
    )
    result = compare_day("2026-10-12", include_hour_details=True)
    assert result["missed"] == 0
    assert result["added"] == 0
    assert sum(h["differences"] for h in result["hours"]) == 0
    hour1 = result["hour_details"][1]
    assert len(hour1["display_pairs"]) == 1
    assert hour1["display_pairs"][0]["scheduled_row"]["title"] == "BILLIE JEAN"
    assert hour1["display_pairs"][0]["played_row"]["title"] == "BILLIE JEAN"


def test_1229_reorder_view_preserves_real_order_on_both_sides(tmp_path, monkeypatch):
    _use_db(monkeypatch, tmp_path / "order.db")
    scheduled = "\n".join([
        _song("10:04:30.0", "Miley Cyrus", "Flowers", "MILEY"),
        _song("10:07:45.9", "sanah", "Marcepan", "SANAH"),
        _song("10:07:54.7", "Robbie Williams", "ROCK DJ", "ROBBIE"),
    ])
    played = "\n".join([
        _song("10:06:14.1", "Robbie Williams", "ROCK DJ", "ROBBIE"),
        _song("10:10:14.6", "sanah", "Marcepan", "SANAH"),
        _song("10:10:23.4", "Miley Cyrus", "Flowers", "MILEY"),
    ])
    import_gselector_export(scheduled, filename="12.10_schedule.txt", kind="schedule", start_date="2026-10-12")
    import_gselector_export(played, filename="12.10_played.txt", kind="played", start_date="2026-10-12")
    result = compare_hour("2026-10-12", 10)
    pairs = result["display_pairs"]
    assert [p["scheduled_row"]["title"] for p in pairs] == ["Flowers", "Marcepan", "ROCK DJ"]
    assert [p["played_row"]["title"] for p in pairs] == ["ROCK DJ", "Marcepan", "Flowers"]
    assert any("Kolejność" in p["scheduled_status"] for p in pairs)
    assert any("Kolejność" in p["played_status"] for p in pairs)


def test_1229_skipped_and_nonplayed_are_retained_and_named(tmp_path, monkeypatch):
    _use_db(monkeypatch, tmp_path / "skip.db")
    day = "2026-10-12"
    schedule_payload = {"rows": [_zetta_asset(1, f"{day}T10:00:00.0000000", "evt-skip", "Skipped Song", status=1, edit=102, skip=True)]}
    played_payload = {"rows": [_zetta_asset(1, f"{day}T10:00:00.0000000", "evt-skip", "Skipped Song", status=4, edit=202, skip=True)]}
    import_zetta2go_snapshot(schedule_payload, service_date=day, kind="schedule", replace_live=False)
    import_zetta2go_snapshot(played_payload, service_date=day, kind="played", replace_live=True)

    assert events_for_day("played", day) == []
    retained = events_for_day("played", day, include_nonplayed=True)
    assert len(retained) == 1 and retained[0]["zetta_skip"] is True

    cmp = compare_hour(day, 10)
    assert cmp["rows"][0]["status"] == "Wyskipowane"
    assert cmp["missed"] == 1
    assert cmp["differences"] == 1
    pair = cmp["display_pairs"][0]
    assert pair["scheduled_status"] == "Wyskipowane"
    assert pair["played_status"] == "Wyskipowane"


def test_1229_fade_runtime_delta_is_rendered_under_total_time():
    assert 'runtime_delta=runtime_cut' in APP
    assert 'rc-log-runtime-delta' in APP
    assert 'runtime_override=planned_runtime if runtime_cut else ""' in APP
    assert 'cached_local_day_events(revision: str, kind: str, service_date: str)' in APP
    assert 'include_nonplayed=(kind == "played")' in APP
