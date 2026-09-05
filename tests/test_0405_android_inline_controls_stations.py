from __future__ import annotations

import importlib
from pathlib import Path


def test_airplay_api_respects_selected_station_ids(tmp_path, monkeypatch):
    monkeypatch.setenv("RADIOCHARTS_DB", str(tmp_path / "station-filter.db"))
    import radiocharts.db as db
    import radiocharts.metrics as metrics
    import radiocharts.api as api
    importlib.reload(db)
    importlib.reload(metrics)
    importlib.reload(api)

    db.init_db()
    db.upsert_airplay_stations([
        {"station_id": 1, "name": "Radio A", "slug": "a", "source_url": "", "active": True},
        {"station_id": 2, "name": "Radio B", "slug": "b", "source_url": "", "active": True},
    ])
    with db.connect() as con:
        song_a = db.get_or_create_song(con, "Artist A", "Song A")
        song_b = db.get_or_create_song(con, "Artist B", "Song B")
        con.executemany(
            """INSERT INTO airplay_plays(station_id,played_at,artist,title,artist_key,title_key,song_id,source_url,retrieved_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            [
                (1, "2026-09-05T08:00", "Artist A", "Song A", db.normalize("Artist A"), db.normalize("Song A"), song_a, "", "2026-09-05T08:10"),
                (2, "2026-09-05T09:00", "Artist B", "Song B", db.normalize("Artist B"), db.normalize("Song B"), song_b, "", "2026-09-05T09:10"),
            ],
        )

    only_a = api.songs(
        mode="airplay", search="", statuses=[], downloaded="any", sort="spins", descending=True,
        start=None, end=None, station_ids="1", limit=50, offset=0,
    )
    only_b = api.songs(
        mode="airplay", search="", statuses=[], downloaded="any", sort="spins", descending=True,
        start=None, end=None, station_ids="2", limit=50, offset=0,
    )
    assert [row["song_id"] for row in only_a["items"]] == [song_a]
    assert [row["song_id"] for row in only_b["items"]] == [song_b]
    assert only_a["reporting_stations"] == 1
    assert only_b["reporting_stations"] == 1


def test_android_013_has_inline_preview_status_and_airplay_station_picker():
    root = Path(__file__).resolve().parents[1]
    main = (root / "android/RadioChartsAndroid/app/src/main/java/pl/radiocharts/mobile/MainActivity.kt").read_text(encoding="utf-8")
    api_kt = (root / "android/RadioChartsAndroid/app/src/main/java/pl/radiocharts/mobile/Api.kt").read_text(encoding="utf-8")
    gradle = (root / "android/RadioChartsAndroid/app/build.gradle.kts").read_text(encoding="utf-8")

    assert 'mode == "dashboard" || mode == "airplay"' in main
    assert "PreviewButton(s)" in main
    assert "InlineStatusMenu(" in main
    assert "changeStatus(row: SongRow, newStatus: String)" in main
    assert 'Text(if(count == 0) "Stacje: wszystkie" else "Stacje: $count wybranych")' in main
    assert "selectedStationIds" in main
    assert "api.stations()" in main
    assert "stationIds = before.selectedStationIds" in main
    assert '@Query("station_ids") stationIds: String? = null' in api_kt
    assert 'versionCode = 4' in gradle
    assert 'versionName = "0.1.3"' in gradle


def test_version_0405():
    root = Path(__file__).resolve().parents[1]
    assert (root / "VERSION").read_text(encoding="utf-8").strip() == "0.4.5"
