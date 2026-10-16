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


def _unscheduled_row(*, seq: int, at: str, uid: str, label: str, entry_type: int = 19, status: int = 1):
    return {
        "id": uid,
        "cell": [
            str(entry_type), seq, "0", True, "", at, "", label, "", str(status), "1",
            False, False, 1, "", 0,
            {"AirTime": at, "NextETM": "7:00:00 AM", "GapToETM": 0},
            "group", 0, "", 0, None, True, False,
        ],
    }


def _asset_row(*, seq: int, at: str, uid: str, title: str, status: int = 1):
    asset = {
        "AssetID": f"asset-{uid}",
        "AssetTypeID": 1,
        "Artist": "Artist",
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
            "106", seq, "0", True, "", at, "", asset, "", str(status), "1",
            False, False, 1, "", 180000,
            {"AirTime": at, "NextETM": "7:00:00 AM", "GapToETM": 0},
            "group", 180000, "", 0, None, True, False,
        ],
    }


def _payload(*rows):
    return {"total": 1, "page": 1, "records": len(rows), "rows": list(rows)}


def test_1240_parser_keeps_native_unscheduled_song_and_link_airtimes():
    rows = parse_zetta2go_log(
        _payload(
            _unscheduled_row(seq=1, at="2026-10-15T08:17:42.6300000", uid="u-link", label="Unscheduled Link", entry_type=19),
            _unscheduled_row(seq=2, at="2026-10-15T11:36:05.1000000", uid="u-song", label="Unscheduled Song", entry_type=18),
        ),
        "2026-10-15",
        kind="schedule",
    )
    assert [row["event_type"] for row in rows] == ["unscheduled", "unscheduled"]
    assert [row["air_time_raw"] for row in rows] == ["08:17:42.6", "11:36:05.1"]
    assert [row["payload"]["unscheduled_kind"] for row in rows] == ["link", "song"]
    assert [row["payload"]["unscheduled_label"] for row in rows] == ["Unscheduled Link", "Unscheduled Song"]


def test_1240_unscheduled_is_persisted_for_etm_table_but_ignored_by_comparison(tmp_path, monkeypatch):
    _use_db(monkeypatch, tmp_path / "unscheduled.db")
    scheduled = _payload(
        _asset_row(seq=1, at="2026-10-15T08:00:00.0000000", uid="song-a", title="Song A"),
        _unscheduled_row(seq=2, at="2026-10-15T08:17:42.6300000", uid="u-link", label="Unscheduled Link"),
    )
    played = _payload(
        _asset_row(seq=1, at="2026-10-15T08:00:00.0000000", uid="song-a", title="Song A", status=3),
        _unscheduled_row(seq=2, at="2026-10-15T08:17:42.6300000", uid="u-link", label="Unscheduled Link", status=3),
    )
    import_zetta2go_snapshot(scheduled, service_date="2026-10-15", kind="schedule", source="zetta2go-cutoff")
    import_zetta2go_snapshot(played, service_date="2026-10-15", kind="played", replace_live=True)

    stored = events_for_day("played", "2026-10-15", include_nonplayed=True)
    unscheduled = [row for row in stored if row["event_type"] == "unscheduled"]
    assert len(unscheduled) == 1
    assert unscheduled[0]["air_time_raw"] == "08:17:42.6"
    assert unscheduled[0]["payload"]["unscheduled_kind"] == "link"

    comparison = compare_hour("2026-10-15", 8)
    assert comparison["differences"] == 0
    assert all(row.get("event_type") != "unscheduled" for row in comparison["scheduled_rows"])
    assert all(row.get("event_type") != "unscheduled" for row in comparison["played_rows"])


def test_1240_etm_page_renders_compact_unscheduled_table_from_native_rows():
    app = (ROOT / "radiocharts/app.py").read_text(encoding="utf-8")
    assert "def _render_local_unscheduled_summary" in app
    assert 'st.markdown("#### Unscheduled")' in app
    assert '"Czas": str(row.get("air_time_raw") or "")[:8]' in app
    assert '_render_local_unscheduled_summary(rows)' in app
