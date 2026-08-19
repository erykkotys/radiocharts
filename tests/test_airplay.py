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


def test_airplay_summary_is_independent_and_track_detail_breaks_down_stations(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "airplay.db")
    monkeypatch.setattr(db, "_INITIALIZED_DB_PATH", None)
    db.init_db()
    # A chart song with the same credit may exist, but Emisje must not link to it.
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
    assert "song_id" not in row

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
        linked = con.execute("SELECT COUNT(*) FROM airplay_plays WHERE song_id IS NOT NULL").fetchone()[0]
    assert linked == 0

