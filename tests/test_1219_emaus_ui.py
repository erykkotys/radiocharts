from __future__ import annotations

from pathlib import Path

import radiocharts.db as db
from radiocharts.local_station import import_zetta2go_snapshot, events_for_day, parse_zetta2go_log

ROOT = Path(__file__).resolve().parents[1]


def _use_db(monkeypatch, path):
    monkeypatch.setattr(db, "DB_PATH", path)
    monkeypatch.setattr(db, "_INITIALIZED_DB_PATH", None)
    monkeypatch.setenv("RADIOCHARTS_AUTO_LIBRARY_SEED", "0")


def _asset(seq: int, at: str, uid: str, title: str, *, status: int = 3, runtime_ms: int = 180_000):
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
            False, False, 1, "", runtime_ms,
            {"AirTime": at, "NextETM": "7:00:00 AM", "GapToETM": 0},
            "group", runtime_ms, "", 0, None, True, False,
        ],
    }


def test_zetta_asset_metadata_and_toh_are_preserved():
    row = _asset(1, "2026-10-04T06:05:00.0000000", "evt-a", "Song A", status=1)
    row["cell"][7].update({
        "CategoryCode": "G1",
        "Mood": "4",
        "Opener": "YES",
        "TextureOpen": "2",
        "TextureClose": "5",
    })
    toh = {
        "id": "toh-06",
        "cell": ["3", 0, "0", True, "", "2026-10-04T06:00:00.0000000", "", "Top of Hour", "", "1", "1", False, False, 1, "", 0, {}, "group", 0, "", 0, None, True, False],
    }
    rows = parse_zetta2go_log({"rows": [toh, row]}, "2026-10-04", kind="schedule")
    assert rows[0]["event_type"] == "toh"
    song = rows[1]
    assert song["category"] == "G1"
    assert song["payload"]["category_code"] == "G1"
    assert song["payload"]["mood"] == "4"
    assert song["payload"]["opener"] == "YES"
    assert song["payload"]["texture_open"] == "2"
    assert song["payload"]["texture_close"] == "5"


def test_played_duration_ignores_normal_crossfade_but_keeps_large_stop(tmp_path, monkeypatch):
    _use_db(monkeypatch, tmp_path / "1219.db")
    payload = {
        "rows": [
            _asset(1, "2026-10-04T06:00:00.0000000", "cut", "Cut", status=8, runtime_ms=180_000),
            _asset(2, "2026-10-04T06:01:00.0000000", "normal", "Normal", status=3, runtime_ms=180_000),
            _asset(3, "2026-10-04T06:03:55.0000000", "next", "Next", status=3, runtime_ms=180_000),
        ]
    }
    import_zetta2go_snapshot(payload, service_date="2026-10-04", kind="played", replace_live=True)
    rows = {row["title"]: row for row in events_for_day("played", "2026-10-04")}
    assert rows["Cut"]["played_raw"] == "01:00"
    # Five seconds before the nominal runtime is a normal segue, not a 2:55 play.
    assert rows["Normal"]["played_raw"] == "03:00"


def test_1219_emaus_ui_contract():
    app = (ROOT / "radiocharts/app.py").read_text(encoding="utf-8")
    local = (ROOT / "radiocharts/local_station.py").read_text(encoding="utf-8")
    android = (ROOT / "android/RadioChartsAndroid/app/src/main/java/pl/radiocharts/mobile/MainActivity.kt").read_text(encoding="utf-8")
    models = (ROOT / "android/RadioChartsAndroid/app/src/main/java/pl/radiocharts/mobile/Models.kt").read_text(encoding="utf-8")

    assert "grid-auto-flow:column" in app
    assert "min(3, max(1, math.ceil(len(cards) / 12)))" in app
    assert '"Ignoruj resety",\n        value=True' in app
    assert "def _render_local_etm_page" in app and "_render_local_etm_gap_summary(filtered, ignore_resets=ignore_resets)" in app
    assert "Top of the hour" in app and "#ff79c6" in app
    assert "def _render_local_timeline_cards(rows: list[dict], kind: str, *, anchor_prefix: str)" in app
    assert "Mood" in app and "Opener" in app and "T.Open" in app and "T.Close" in app
    assert "ondblclick" in app and "?view=song&song=" in app
    assert "@st.fragment(run_every=5.0)" in app
    assert "played_seconds" in local and "cut_ratio" in local

    assert "detectTapGestures(onDoubleTap" in android
    assert "delay(15_000)" in android
    assert "Top of the hour" in android
    for field in ("category_code", "played_raw", "mood", "opener", "texture_open", "texture_close", "song_id"):
        assert f"val {field}" in models
