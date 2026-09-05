from __future__ import annotations

import importlib
from datetime import date
from pathlib import Path

import pandas as pd


def test_mobile_period_summary_is_lean_and_correct(tmp_path, monkeypatch):
    monkeypatch.setenv("RADIOCHARTS_DB", str(tmp_path / "mobile-fast.db"))
    import radiocharts.db as db
    importlib.reload(db)
    db.init_db()
    db.upsert_airplay_stations([
        {"station_id": 1, "name": "A", "slug": "a", "source_url": "", "active": True},
        {"station_id": 2, "name": "B", "slug": "b", "source_url": "", "active": True},
    ])
    with db.connect() as con:
        s1 = db.get_or_create_song(con, "Artist 1", "Song 1")
        s2 = db.get_or_create_song(con, "Artist 2", "Song 2")
        rows = [
            (1, "2026-09-05T08:00", "Artist 1", "Song 1", db.normalize("Artist 1"), db.normalize("Song 1"), s1, "", "2026-09-05T08:10"),
            (1, "2026-09-05T09:00", "Artist 1", "Song 1", db.normalize("Artist 1"), db.normalize("Song 1"), s1, "", "2026-09-05T09:10"),
            (2, "2026-09-05T10:00", "Artist 1", "Song 1", db.normalize("Artist 1"), db.normalize("Song 1"), s1, "", "2026-09-05T10:10"),
            (2, "2026-09-05T11:00", "Artist 2", "Song 2", db.normalize("Artist 2"), db.normalize("Song 2"), s2, "", "2026-09-05T11:10"),
        ]
        con.executemany(
            """INSERT INTO airplay_plays(station_id,played_at,artist,title,artist_key,title_key,song_id,source_url,retrieved_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            rows,
        )
    summary = db.airplay_mobile_summary([1, 2], date(2026, 9, 5), date(2026, 9, 5))
    assert summary["reporting_stations"] == 2
    by_id = {int(r["song_id"]): r for r in summary["rows"]}
    assert by_id[s1]["spins"] == 3
    assert by_id[s1]["stations_count"] == 2
    assert by_id[s2]["spins"] == 1
    assert db.airplay_reporting_station_count([1, 2], "2026-09-05", "2026-09-05") == 2


def test_mobile_sort_aliases_cover_chart_and_period_fields():
    import radiocharts.api as api
    frame = pd.DataFrame([
        {"song_id": 1, "RMF_pos": 10, "period_rotation": 20.0, "stations_count": 2, "last_play": "2026-09-04T10:00"},
        {"song_id": 2, "RMF_pos": 2, "period_rotation": 80.0, "stations_count": 8, "last_play": "2026-09-05T10:00"},
    ])
    assert api._sort_frame(frame, "rmf", False).iloc[0]["song_id"] == 2
    assert api._sort_frame(frame, "rotation", True).iloc[0]["song_id"] == 2
    assert api._sort_frame(frame, "stations", True).iloc[0]["song_id"] == 2
    assert api._sort_frame(frame, "last_play", True).iloc[0]["song_id"] == 2


def test_android_011_uses_paging_longer_timeout_and_expanded_sorting():
    root = Path(__file__).resolve().parents[1]
    api_kt = (root / "android/RadioChartsAndroid/app/src/main/java/pl/radiocharts/mobile/Api.kt").read_text(encoding="utf-8")
    main = (root / "android/RadioChartsAndroid/app/src/main/java/pl/radiocharts/mobile/MainActivity.kt").read_text(encoding="utf-8")
    gradle = (root / "android/RadioChartsAndroid/app/build.gradle.kts").read_text(encoding="utf-8")
    assert "readTimeout(60" in api_kt
    assert "callTimeout(90" in api_kt
    assert '@Query("offset") offset: Int = 0' in api_kt
    assert "limit: Int = 120" in api_kt
    assert "Pokaż kolejne" in main
    for key in ["rmf", "zet", "olia", "olis", "eska", "rotation", "stations", "radio_presence7", "last_play"]:
        assert f'SortChoice("{key}"' in main
    assert "toggleDirection" in main
    assert 'versionName = "0.1.1"' in gradle


def test_version_0402():
    root = Path(__file__).resolve().parents[1]
    assert (root / "VERSION").read_text(encoding="utf-8").strip() == "0.4.2"
