from __future__ import annotations

from datetime import date
from pathlib import Path

import radiocharts.db as db
from radiocharts.local_station import (
    available_dates,
    compare_day,
    events_for_day,
    import_gselector_export,
    parse_gselector_export,
    song_stats,
<<<<<<< HEAD
    song_activity,
    ensure_song_links_current,
=======
>>>>>>> a98c8593defab725ea67d3c33366c2c60006ed9f
)

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "radiocharts/app.py").read_text(encoding="utf-8")


def _use_db(monkeypatch, path):
    monkeypatch.setattr(db, "DB_PATH", path)
    monkeypatch.setattr(db, "_INITIALIZED_DB_PATH", None)
    monkeypatch.setenv("RADIOCHARTS_AUTO_LIBRARY_SEED", "0")


def _song(time: str, artist: str, title: str, ext: str) -> str:
    cols = [
        time, "CF1/FAMILIAR CURRENT", "3", "5", artist, title, "Stretch", "YES", "", "5", "2", "0",
        time, "", "03:00.0", "Male", ext, "0", "0", "False", time,
    ]
    return "\t".join(f'"{x}"' for x in cols)


def test_gselector_parser_splits_embedded_bom_days_and_keeps_full_event_mix():
    text = (
        '\ufeff"00:00:00.0"\t"ETM_00:00_Soft"\t"+00:00.0"\t"158"\n'
        + _song("00:00:01.0", "Artist A", "Song A", "100") + "\n"
        + '\ufeff"00:00:00.0"\t"ETM_00:00_Soft"\t"+00:00.0"\t"158"\n'
        + '"00:07:00.0"\t"JNW/Jingle NEW Krótkie"\t"EMAUS JINGLE 32"\t"4"\t"jingle_32"\n'
    )
    parsed = parse_gselector_export(text, "30.09-01.10_log.txt")
    assert len(parsed.days) == 2
    assert parsed.row_count == 4
    assert parsed.event_counts["song"] == 1
    assert parsed.event_counts["jingle"] == 1
    assert parsed.inferred_start == date(2026, 9, 30)
    assert parsed.inferred_end == date(2026, 10, 1)


def test_local_station_import_is_versioned_and_replaces_current_snapshot(tmp_path, monkeypatch):
    _use_db(monkeypatch, tmp_path / "local.db")
    first = _song("10:00:00.0", "Artist", "First", "A1")
    second = _song("10:01:00.0", "Artist", "Second", "A2")
    import_gselector_export(first, filename="30.09_log.txt", kind="schedule", start_date="2026-09-30")
    import_gselector_export(second, filename="30.09_log_v2.txt", kind="schedule", start_date="2026-09-30")

    assert available_dates("schedule") == ["2026-09-30"]
    rows = events_for_day("schedule", "2026-09-30")
    assert [r["title"] for r in rows] == ["Second"]
    with db.connect() as con:
        active, archived = con.execute(
            "SELECT SUM(active), SUM(CASE WHEN active=0 THEN 1 ELSE 0 END) FROM local_station_events"
        ).fetchone()
    assert active == 1
    assert archived == 1


def test_compare_day_matches_external_id_and_reports_shift_missing_and_added(tmp_path, monkeypatch):
    _use_db(monkeypatch, tmp_path / "compare.db")
    schedule = "\n".join([
        _song("10:00:00.0", "Artist", "A", "ID-A"),
        _song("10:05:00.0", "Artist", "B", "ID-B"),
    ])
    played = "\n".join([
        _song("10:00:12.0", "Artist", "A", "ID-A"),
        _song("10:08:00.0", "Artist", "C", "ID-C"),
    ])
    import_gselector_export(schedule, filename="30.09_schedule.txt", kind="schedule", start_date="2026-09-30")
    import_gselector_export(played, filename="30.09_played.txt", kind="played", start_date="2026-09-30")
    result = compare_day("2026-09-30")
    assert result["matched"] == 1
    assert result["on_time"] == 1
    assert result["missed"] == 1
    assert result["added"] == 1
    assert {r["status"] for r in result["rows"]} == {"OK", "Pominięte", "Dodane"}


def test_song_stats_and_our_radio_ui_contract(tmp_path, monkeypatch):
    _use_db(monkeypatch, tmp_path / "stats.db")
    text = "\n".join([
        _song("08:00:00.0", "Artist", "Hit", "ID-HIT"),
        _song("12:00:00.0", "Artist", "Hit", "ID-HIT"),
    ])
    import_gselector_export(text, filename="30.09_log.txt", kind="played", start_date="2026-09-30")
    rows = song_stats("played", "2026-09-30", "2026-09-30")
    assert rows[0]["plays"] == 2
    assert rows[0]["per_calendar_day"] == 2.0
<<<<<<< HEAD
    assert '("our_radio", "EMAUS")' in APP
=======
    assert '("our_radio", "Nasze radio")' in APP
>>>>>>> a98c8593defab725ea67d3c33366c2c60006ed9f
    assert '["Scheduled", "Played", "Porównanie", "Utwory", "Import"]' in APP
    assert 'st.file_uploader("Plik GSelector"' in APP


<<<<<<< HEAD

def test_60plus_air_time_is_overtime_not_anomaly(tmp_path, monkeypatch):
    _use_db(monkeypatch, tmp_path / "gap.db")
    text = _song("08:62:47.3", "Artist", "Overtime", "ID-OVER")
    parsed = parse_gselector_export(text, "30.09_log.txt")
    row = parsed.days[0][0]
    assert row["schedule_hour"] == 8
    assert row["gap_raw"] == "+02:47.3"
    assert row["time_anomaly"] is False
    import_gselector_export(text, filename="30.09_log.txt", kind="schedule", start_date="2026-09-30")
    rows = events_for_day("schedule", "2026-09-30", hour=8)
    assert len(rows) == 1
    assert rows[0]["gap_raw"] == "+02:47.3"


def test_song_raw_fields_and_emaus_song_activity(tmp_path, monkeypatch):
    _use_db(monkeypatch, tmp_path / "fields.db")
    db.init_db()
    with db.connect() as con:
        sid = db.get_or_create_song(con, "Artist", "Hit")
    text = _song("10:00:00.0", "Artist", "Hit", "ID-HIT")
    import_gselector_export(text, filename="30.09_schedule.txt", kind="schedule", start_date="2026-09-30")
    import_gselector_export(text, filename="30.09_played.txt", kind="played", start_date="2026-09-30")
    ensure_song_links_current()
    rows = events_for_day("schedule", "2026-09-30")
    assert rows[0]["mood"] == "3"
    assert rows[0]["opener"] == "5"
    assert rows[0]["timing"] == "Stretch"
    assert rows[0]["vocal"] == "Male"
    activity = song_activity(sid, "2026-09-30", "2026-09-30")
    assert activity["scheduled"] == 1
    assert activity["played"] == 1
    assert activity["daily"][0]["scheduled"] == 1
    assert activity["daily"][0]["played"] == 1


=======
>>>>>>> a98c8593defab725ea67d3c33366c2c60006ed9f
def test_release_contains_real_seed_exports():
    schedule = ROOT / "radiocharts/data/gselector_schedule_2026-09-30_2026-10-12.tsv"
    played = ROOT / "radiocharts/data/gselector_played_2026-09-28.tsv"
    assert schedule.is_file() and schedule.stat().st_size > 1_000_000
    assert played.is_file() and played.stat().st_size > 50_000
