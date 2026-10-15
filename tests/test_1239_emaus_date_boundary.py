from __future__ import annotations

from pathlib import Path

import radiocharts.db as db
from radiocharts.local_station import compare_day, import_gselector_export

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "radiocharts/app.py").read_text(encoding="utf-8")


def _use_db(monkeypatch, path):
    monkeypatch.setattr(db, "DB_PATH", path)
    monkeypatch.setattr(db, "_INITIALIZED_DB_PATH", None)
    monkeypatch.setenv("RADIOCHARTS_AUTO_LIBRARY_SEED", "0")


def _song(at: str, artist: str, title: str, ext: str) -> str:
    cols = [
        at, "G1", "3", "5", artist, title, "Stretch", "YES", "", "5", "2", "0",
        at, "", "04:00.0", "Male", ext, "0", "0", "False", at,
    ]
    return "\t".join(f'"{value}"' for value in cols)


def test_1239_date_picker_is_shared_and_refresh_is_available():
    assert 'LOCAL_SHARED_DATE_WIDGET_KEY = "our_radio_shared_date_picker"' in APP
    assert 'widget_key = LOCAL_SHARED_DATE_WIDGET_KEY' in APP
    assert 'refresh_col.button("Odśwież"' in APP
    assert 'local_sync_zetta2go_live(selected)' in APP


def test_1239_soft_boundary_uses_nearest_occurrence_even_if_title_repeats_in_previous_hour(tmp_path, monkeypatch):
    _use_db(monkeypatch, tmp_path / "soft-boundary.db")
    day = "2026-10-10"

    # Same song appears earlier in hour 01 and again as the first song of hour 02.
    # The live playout starts the second occurrence half a second before 02:00,
    # which is normal around a Soft ETM.  The old unique-hour heuristic kept it
    # in hour 01 because that identity also existed there and produced a false
    # Niezagrane + Dodane pair at the boundary.
    scheduled = "\n".join([
        _song("01:10:00.0", "sanah & ENKLAWA", "itepe itede", "sched-1"),
        _song("02:00:00.0", "sanah & ENKLAWA", "itepe itede", "sched-2"),
    ])
    played = "\n".join([
        _song("01:10:00.2", "sanah & ENKLAWA", "itepe itede", "play-1"),
        _song("01:59:59.5", "sanah & ENKLAWA", "itepe itede", "play-2"),
    ])
    import_gselector_export(scheduled, filename="schedule.txt", kind="schedule", start_date=day)
    import_gselector_export(played, filename="played.txt", kind="played", start_date=day)

    result = compare_day(day, include_hour_details=True)
    assert result["missed"] == 0
    assert result["added"] == 0
    assert sum(hour["differences"] for hour in result["hours"]) == 0

    hour2 = result["hour_details"][2]
    assert len(hour2["display_pairs"]) == 1
    pair = hour2["display_pairs"][0]
    assert pair["scheduled_row"]["air_time_raw"] == "02:00:00.0"
    assert pair["played_row"]["air_time_raw"] == "01:59:59.5"


def test_1239_changed_rows_have_clear_faded_red_background():
    assert 'linear-gradient(90deg,rgba(132,38,48,.46),rgba(92,29,37,.31))' in APP
    assert 'inset 4px 0 rgba(255,93,93,.72)' in APP
