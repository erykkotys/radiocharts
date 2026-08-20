from datetime import date
from pathlib import Path

import radiocharts.db as db
from radiocharts.metrics import _weekly_source_stats


def test_normalize_folds_polish_l():
    assert db.normalize("Męskie Łąki") == "meskie laki"


def test_familiarity_has_slow_memory_but_momentum_fades():
    rows = []
    for d, pos in [
        ("2026-01-05", 1), ("2026-01-12", 2), ("2026-01-19", 2),
        ("2026-01-26", 3), ("2026-02-02", 2), ("2026-02-09", 4),
        ("2026-02-16", 3), ("2026-02-23", 4), ("2026-03-02", 5),
        ("2026-03-09", 5), ("2026-03-16", 6), ("2026-03-23", 6),
    ]:
        rows.append({"chart_date": d, "position": pos, "chart_size": 20, "reported_weeks": None, "reported_peak": None})
    fresh = _weekly_source_stats(__import__('pandas').DataFrame(rows), "2026-03-23")
    month_later = _weekly_source_stats(__import__('pandas').DataFrame(rows), "2026-04-20")
    assert fresh["familiarity"] >= 85
    assert month_later["familiarity"] >= fresh["familiarity"] - 3
    assert month_later["momentum"] < fresh["momentum"] * 0.5


def test_rds_project_suffix_relinks_to_unique_chart_song(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "suffix.db")
    monkeypatch.setattr(db, "_INITIALIZED_DB_PATH", None)
    db.init_db()
    db.upsert_issue(
        "RMF", "2026-08-11", "x", 20,
        [{"position": 1, "artist": "Męskie Granie Orkiestra 2026", "title": "Nareszcie"}],
    )
    db.upsert_airplay_stations([{"station_id": 1, "name": "MC Radio"}])
    db.store_airplay_window(1, "MC Radio", "2026-08-20", 10, [
        {"played_at": "2026-08-20T10:05", "artist": "Igor Herbut, Zalia, Vito Bambino", "title": "Nareszcie (Męskie Granie 2026)"}
    ])
    with db.connect() as con:
        chart_sid = int(con.execute("SELECT song_id FROM chart_entries LIMIT 1").fetchone()["song_id"])
        air_sid = int(con.execute("SELECT song_id FROM airplay_plays LIMIT 1").fetchone()["song_id"])
    assert air_sid == chart_sid
    detail = db.airplay_track_detail_by_song([1], date(2026,8,20), date(2026,8,20), chart_sid)
    assert detail["total_spins"] == 1


def test_song_picker_catalog_excludes_unrated_airplay_noise(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "catalog.db")
    monkeypatch.setattr(db, "_INITIALIZED_DB_PATH", None)
    db.init_db()
    db.upsert_issue("RMF", "2026-08-11", "x", 20, [{"position": 1, "artist": "Chart", "title": "Song"}])
    db.upsert_airplay_stations([{"station_id": 1, "name": "One"}])
    db.store_airplay_window(1, "One", "2026-08-20", 10, [
        {"played_at": "2026-08-20T10:05", "artist": "Noise Artist", "title": "One-off RDS credit"}
    ])
    cat = db.song_catalog()
    assert {(r["artist"], r["title"]) for r in cat} == {("Chart", "Song")}
