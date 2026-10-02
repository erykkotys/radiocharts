from __future__ import annotations

from datetime import date
from pathlib import Path

import radiocharts.db as db
import radiocharts.local_station as local_station
from radiocharts.local_station import (
    available_dates,
    compare_day,
    compare_hour,
    events_for_day,
    import_gselector_export,
    parse_gselector_export,
    song_stats,
    song_activity,
    ensure_song_links_current,
    delete_import,
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
    assert {r["status"] for r in result["rows"]} == {"OK", "Niezagrane", "Dodane"}


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
    assert '("our_radio", "EMAUS")' in APP
    assert '["Scheduled", "Played", "Porównanie", "Utwory", "Import"]' in APP
    assert 'st.file_uploader("Plik GSelector"' in APP



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


def test_release_contains_real_seed_exports():
    schedule = ROOT / "radiocharts/data/gselector_schedule_2026-09-30_2026-10-12.tsv"
    played = ROOT / "radiocharts/data/gselector_played_2026-09-28.tsv"
    assert schedule.is_file() and schedule.stat().st_size > 1_000_000
    assert played.is_file() and played.stat().st_size > 50_000


def test_compare_hour_ignores_seconds_but_detects_order_and_keeps_repeats_separate(tmp_path, monkeypatch):
    _use_db(monkeypatch, tmp_path / "hourly.db")
    schedule = "\n".join([
        _song("00:05:00.0", "Artist", "Repeat", "ID-R"),
        _song("00:10:00.0", "Artist", "A", "ID-A"),
        _song("00:15:00.0", "Artist", "B", "ID-B"),
        _song("06:00:00.0", "Artist", "Repeat", "ID-R"),
    ])
    played = "\n".join([
        _song("00:06:33.0", "Artist", "Repeat", "ID-R"),
        _song("00:15:30.0", "Artist", "B", "ID-B"),
        _song("00:18:00.0", "Artist", "A", "ID-A"),
        _song("06:38:00.0", "Artist", "Repeat", "ID-R"),
    ])
    import_gselector_export(schedule, filename="30.09_schedule.txt", kind="schedule", start_date="2026-09-30")
    import_gselector_export(played, filename="30.09_played.txt", kind="played", start_date="2026-09-30")

    midnight = compare_hour("2026-09-30", 0)
    repeat = next(r for r in midnight["rows"] if r["title"] == "Repeat")
    assert repeat["status"] == "OK"
    assert repeat["start_delta"] == "+1:33"
    moved = [r for r in midnight["rows"] if r["title"] in {"A", "B"}]
    assert {r["status"] for r in moved} == {"Kolejność"}

    six = compare_hour("2026-09-30", 6)
    assert six["missed"] == 0 and six["added"] == 0
    assert six["rows"][0]["title"] == "Repeat"
    assert six["rows"][0]["status"] == "OK"


def test_compare_hour_marks_runtime_cut_but_not_small_runtime_drift(tmp_path, monkeypatch):
    _use_db(monkeypatch, tmp_path / "fade.db")
    planned = _song("15:00:00.0", "Artist", "Long", "ID-L").replace('"03:00.0"\t"Male"', '"04:00.0"\t"Male"')
    played = _song("15:02:00.0", "Artist", "Long", "ID-L").replace('"03:00.0"\t"Male"', '"03:50.0"\t"Male"')
    import_gselector_export(planned, filename="30.09_schedule.txt", kind="schedule", start_date="2026-09-30")
    import_gselector_export(played, filename="30.09_played.txt", kind="played", start_date="2026-09-30")
    result = compare_hour("2026-09-30", 15)
    assert result["faded"] == 1
    assert result["rows"][0]["status"] == "Ścięty"
    assert result["rows"][0]["runtime_cut"] == "-0:10"


def test_delete_import_restores_previous_snapshot_and_allows_reimport(tmp_path, monkeypatch):
    _use_db(monkeypatch, tmp_path / "delete.db")
    first = import_gselector_export(
        _song("10:00:00.0", "Artist", "Old", "ID-OLD"),
        filename="30.09_old.txt", kind="schedule", start_date="2026-09-30",
    )
    wrong = import_gselector_export(
        _song("10:00:00.0", "Artist", "Wrong", "ID-WRONG"),
        filename="30.09_wrong.txt", kind="schedule", start_date="2026-09-30",
    )
    assert [r["title"] for r in events_for_day("schedule", "2026-09-30")] == ["Wrong"]
    deleted = delete_import(wrong["import_id"])
    assert deleted["restored_days"] == 1
    assert [r["title"] for r in events_for_day("schedule", "2026-09-30")] == ["Old"]
    again = import_gselector_export(
        _song("10:00:00.0", "Artist", "Wrong", "ID-WRONG"),
        filename="30.09_wrong.txt", kind="schedule", start_date="2026-10-01",
    )
    assert again["duplicate"] is False
    assert again["date_from"] == "2026-10-01"
    assert first["import_id"] != again["import_id"]


def test_v124_etm_gap_presets_and_daily_summary_contract(tmp_path, monkeypatch):
    _use_db(monkeypatch, tmp_path / "etm124.db")
    text = "\n".join([
        '"06:00:00.0"\t"ETM_00:00_Hard"\t"+00:00.0"\t"671"',
        '"06:30:00.0"\t"ETM_30:00_Hard"\t"+01:12.0"\t"668"',
        '"07:00:00.0"\t"ETM_00:00_Soft"\t"-00:18.0"\t"158"',
        '"07:15:00.0"\t"ETM_15:00_Reset"\t"+00:05.0"\t"667"',
        '"07:59:00.0"\t"ETM_59:00_Hit"\t"-00:03.0"\t"2"',
    ])
    import_gselector_export(text, filename="30.09_log.txt", kind="schedule", start_date="2026-09-30")
    rows = events_for_day("schedule", "2026-09-30")
    assert [r["etm_delta_raw"] for r in rows] == ["+00:00.0", "+01:12.0", "-00:18.0", "+00:05.0", "-00:03.0"]
    assert '"Hard + Soft": {"Hard", "Soft"}' in APP
    assert '"Reset + Hit": {"Reset", "Hit"}' in APP
    assert '"Programowe (bez ETM/komend)"' in APP
    assert 'ETM Hard / Soft — gapy planu GSelector' in APP
    assert 'nie gap Zetty' in APP
    assert 'frame.loc[etm_mask, "Gap"]' in APP


def test_v125_compare_day_reads_each_daily_log_once(tmp_path, monkeypatch):
    _use_db(monkeypatch, tmp_path / "compare125.db")
    schedule = "\n".join([
        _song("10:00:00.0", "Artist", "A", "ID-A"),
        _song("11:00:00.0", "Artist", "B", "ID-B"),
    ])
    played = "\n".join([
        _song("10:00:10.0", "Artist", "A", "ID-A"),
        _song("11:00:10.0", "Artist", "B", "ID-B"),
    ])
    import_gselector_export(schedule, filename="30.09_schedule.txt", kind="schedule", start_date="2026-09-30")
    import_gselector_export(played, filename="30.09_played.txt", kind="played", start_date="2026-09-30")

    original = local_station.events_for_day
    calls = []

    def counted(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(local_station, "events_for_day", counted)
    result = local_station.compare_day("2026-09-30", include_hour_details=True)
    assert result["matched"] == 2
    assert len(result["hour_details"]) == 24
    assert len(calls) == 2
    assert all(call_kwargs.get("hour") is None for _call_args, call_kwargs in calls)


def test_v126_shared_compare_scroll_lazy_subviews_and_status_contract():
    assert 'class="rc-compare-scroll"' in APP
    assert 'Scheduled i Played mają jeden wspólny pionowy scroll' in APP
    assert 'st.segmented_control(' in APP
    assert '["Scheduled", "Played", "Porównanie", "Utwory", "Import"]' in APP
    assert 'tab_schedule, tab_played, tab_compare, tab_songs, tab_import = st.tabs' not in APP
    assert '_bootstrap_local_station_seed_once()' in APP
    assert '_cached_local_station_song_links(catalog_revision())' in APP
    assert 'return "✓", "rc-status-ok", "Zgodne"' in APP
    assert 'return "✕", "rc-status-bad", "Nie zagrano / usunięte"' in APP
    assert 'return "+", "rc-status-bad", "Dodane w Played"' in APP
    assert 'return "↻", "rc-status-move", "Zmieniona kolejność"' in APP
    assert 'rc-log-ghost' in APP
    assert 'with_radio_presence(df, days=7, air_rev=AIR_REV)' in APP


def test_v126_compare_display_pairs_keep_missing_as_played_ghost(tmp_path, monkeypatch):
    _use_db(monkeypatch, tmp_path / "compare126.db")
    schedule = "\n".join([
        _song("10:00:00.0", "Artist", "A", "ID-A"),
        _song("10:03:00.0", "Artist", "B", "ID-B"),
    ])
    played = "\n".join([
        _song("10:00:05.0", "Artist", "A", "ID-A"),
        _song("10:06:00.0", "Artist", "C", "ID-C"),
    ])
    import_gselector_export(schedule, filename="30.09_schedule.txt", kind="schedule", start_date="2026-09-30")
    import_gselector_export(played, filename="30.09_played.txt", kind="played", start_date="2026-09-30")
    result = compare_hour("2026-09-30", 10)
    pairs = result["display_pairs"]
    assert any(p["status"] == "Niezagrane" and p["scheduled_row"] and p["played_row"] is None for p in pairs)
    assert any(p["status"] == "Dodane" and p["scheduled_row"] is None and p["played_row"] for p in pairs)
    assert any(p["status"] == "OK" and p["scheduled_row"] and p["played_row"] for p in pairs)
