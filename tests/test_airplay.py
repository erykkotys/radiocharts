from datetime import date

import radiocharts.db as db
from radiocharts.airplay import parse_playlist_html, parse_station_directory, parse_station_id


def test_station_directory_and_id_parser():
    directory_html = """
    <html><body>
      <a href="/radio/rmf_fm">RMF FM</a>
      <a href="/radio/eska">Eska</a>
      <a href="/radio">Radia</a>
    </body></html>
    """
    rows = parse_station_directory(directory_html)
    assert [x["slug"] for x in rows] == ["eska", "rmf_fm"]
    assert parse_station_id('<a href="/szukaj.php?r=2">Sprawdź co było grane!</a>') == 2


def test_playlist_parser_keeps_exact_times_and_song_credit():
    html = """
    <table>
      <tr><th>Godzina</th><th>Nazwa utworu</th></tr>
      <tr><td>18:00</td><td></td></tr>
      <tr><td>18:05</td><td>Dua Lipa - Houdini</td></tr>
      <tr><td>18:11</td><td>Kuba I Kuba - Stygnie Lato</td></tr>
    </table>
    """
    rows = parse_playlist_html(html, date(2026, 8, 18), 18, "https://example.test")
    assert rows == [
        {
            "played_at": "2026-08-18T18:05",
            "artist": "Dua Lipa",
            "title": "Houdini",
            "source_url": "https://example.test",
        },
        {
            "played_at": "2026-08-18T18:11",
            "artist": "Kuba I Kuba",
            "title": "Stygnie Lato",
            "source_url": "https://example.test",
        },
    ]


def test_airplay_summary_keeps_metric_separate_but_shares_song_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "airplay.db")
    monkeypatch.setattr(db, "_INITIALIZED_DB_PATH", None)
    db.init_db()
    # Same musical object: airplay links to the chart song, but spin counts stay separate.
    db.upsert_issue("RMF", "2026-08-18", "x", 20, [
        {"position": 1, "artist": "Dua Lipa", "title": "Houdini"},
    ])
    db.upsert_airplay_stations([
        {"station_id": 2, "name": "RMF FM"},
        {"station_id": 3, "name": "Eska"},
    ])
    db.store_airplay_window(2, "RMF FM", "2026-08-18", 18, [
        {"played_at": "2026-08-18T18:05", "artist": "Dua Lipa", "title": "Houdini"},
        {"played_at": "2026-08-18T18:55", "artist": "Dua Lipa", "title": "Houdini"},
    ])
    db.store_airplay_window(3, "Eska", "2026-08-18", 18, [
        {"played_at": "2026-08-18T18:15", "artist": "Dua Lipa", "title": "Houdini"},
    ])
    rows = db.airplay_summary([2, 3], date(2026, 8, 18), date(2026, 8, 18))
    assert len(rows) == 1
    row = rows[0]
    assert row["spins"] == 3
    assert row["stations_count"] == 2
    assert row["max_station_spins"] == 2
    assert row["top_station"] == "RMF FM"
    assert isinstance(row["song_id"], int)

    detail = db.airplay_track_detail(
        [2, 3], date(2026, 8, 18), date(2026, 8, 18),
        row["artist_key"], row["title_key"],
    )
    assert detail["total_spins"] == 3
    assert detail["stations_count"] == 2
    assert [x["spins"] for x in detail["stations"]] == [2, 1]
    assert len(detail["daily"]) == 2
    assert len(detail["plays"]) == 3

    with db.connect() as con:
        chart_song_id = con.execute("SELECT song_id FROM chart_entries LIMIT 1").fetchone()[0]
        linked_ids = {r[0] for r in con.execute("SELECT DISTINCT song_id FROM airplay_plays").fetchall()}
    assert linked_ids == {chart_song_id}
    assert row["song_id"] == chart_song_id



def test_airplay_only_song_does_not_change_chart_revision_or_scores(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "separate-metric.db")
    monkeypatch.setattr(db, "_INITIALIZED_DB_PATH", None)
    db.init_db()
    db.upsert_issue("RMF", "2026-08-18", "x", 20, [
        {"position": 4, "artist": "Chart Artist", "title": "Chart Song"},
    ])
    before = db.chart_revision()

    db.upsert_airplay_stations([{"station_id": 48, "name": "Radio Kalisz"}])
    db.store_airplay_window(48, "Radio Kalisz", "2026-08-18", 18, [
        {"played_at": "2026-08-18T18:12", "artist": "Airplay Artist", "title": "Airplay Only"},
    ])
    after = db.chart_revision()

    assert after == before
    with db.connect() as con:
        chart_ids = {r[0] for r in con.execute("SELECT DISTINCT song_id FROM chart_entries").fetchall()}
        airplay_ids = {r[0] for r in con.execute("SELECT DISTINCT song_id FROM airplay_plays").fetchall()}
    assert chart_ids.isdisjoint(airplay_ids)
    assert len(chart_ids) == 1
    assert len(airplay_ids) == 1


def test_full_historical_day_has_twelve_two_hour_windows():
    from datetime import datetime
    from radiocharts.airplay import completed_windows_in_range

    rows = completed_windows_in_range(
        date(2026, 8, 18), date(2026, 8, 18),
        now=datetime(2026, 8, 19, 16, 36),
    )
    assert len(rows) == 12
    assert [hour for _, hour in rows] == list(range(0, 24, 2))


def test_current_day_never_includes_unfinished_or_future_blocks():
    from datetime import datetime
    from radiocharts.airplay import completed_windows_in_range

    rows = completed_windows_in_range(
        date(2026, 8, 19), date(2026, 8, 19),
        now=datetime(2026, 8, 19, 16, 36),
    )
    assert [hour for _, hour in rows] == [0, 2, 4, 6, 8, 10, 12, 14]


def test_recent_24h_is_twelve_two_hour_windows():
    from datetime import datetime
    from radiocharts.airplay import recent_completed_windows

    rows = recent_completed_windows(24, now=datetime(2026, 8, 19, 16, 36))
    assert len(rows) == 12
    assert rows[-1] == (date(2026, 8, 19), 14)
    assert rows[0] == (date(2026, 8, 18), 16)
