from datetime import date
from pathlib import Path

import radiocharts.db as db
from radiocharts.airplay import parse_playlist_html

APP = (Path(__file__).resolve().parents[1] / "radiocharts" / "app.py").read_text(encoding="utf-8")


def _use_db(monkeypatch, path):
    monkeypatch.setattr(db, "DB_PATH", path)
    monkeypatch.setattr(db, "_INITIALIZED_DB_PATH", None)


def test_0322_airplay_tables_share_basic_metrics_and_station_reach():
    # Common/basic song metrics requested for all research tables.
    for field in ['"familiarity"', '"momentum"', '"radio_reach"', '"avg_position"']:
        assert field in APP
    assert '"stations_count", "Zasięg"' in APP
    assert "Math.round(pct) + '% (' + Math.round(v) + ')'" in APP
    assert 'station_total=reporting_station_count' in APP
    assert 'station_total=song_reporting_count' in APP


def test_0322_airplay_range_dates_are_always_editable_and_manual_change_is_custom():
    assert 'selected = c2.date_input(' in APP
    assert 'st.session_state[preset_key] = "Własny zakres"' in APP
    assert 'on_change=_preset_changed' in APP
    assert 'on_change=_dates_changed' in APP


def test_0322_airplay_ui_is_consolidated_and_manual_collapsed():
    assert 'st.tabs(["🔥 Najczęściej grane", "🔎 Sprawdź utwór"])' not in APP
    assert APP.count('🔎 Co dokładnie zostało pobrane — pokrycie per stacja') == 1
    assert 'def render_airplay_data_management(' in APP
    assert 'render_airplay_data_management(running)' in APP
    # Every numbered Manual section defaults closed.
    manual_pos = APP.index('st.markdown("## 📘 Manual RadioCharts")')
    manual = APP[manual_pos:]
    assert manual.count('with st.expander("') >= 11
    assert 'expanded=True' not in manual
    assert 'bottom:75px' in APP
    assert 'padding-top: .85rem' in APP
    assert '30-sekundowy podgląd Apple/iTunes · możesz przewijać suwakiem' not in APP


def test_0322_parser_drops_standalone_eska_jingles_but_not_kreska():
    html = """
    <table>
      <tr><td>10:01</td><td>ESKA - Najlepsze Hity</td></tr>
      <tr><td>10:02</td><td>Artist - ESKA News</td></tr>
      <tr><td>10:03</td><td>Kreska - Normalny utwór</td></tr>
      <tr><td>10:04</td><td>Artist - Kreska</td></tr>
    </table>
    """
    rows = parse_playlist_html(html, date(2026, 8, 22), 10)
    assert [(r["artist"], r["title"]) for r in rows] == [
        ("Kreska", "Normalny utwór"),
        ("Artist", "Kreska"),
    ]


def test_0322_migration_purges_existing_eska_jingles_and_repairs_window(tmp_path, monkeypatch):
    _use_db(monkeypatch, tmp_path / "eska-cleanup.db")
    db.init_db()
    now = "2026-08-22T12:00:00+00:00"
    with db.connect() as con:
        con.execute("DELETE FROM app_meta WHERE key='airplay_eska_jingle_cleanup_v1'")
        con.execute(
            "INSERT OR REPLACE INTO airplay_stations(station_id,name,active,discovered_at,updated_at) VALUES(?,?,?,?,?)",
            (123, "Test FM", 1, now, now),
        )
        # Seed three songs directly because normal ingestion already rejects ESKA jingles.
        songs = [
            (1001, "ESKA", "Jingle", "eska", "jingle"),
            (1002, "Artist", "ESKA News", "artist", "eska news"),
            (1003, "Kreska", "Normalny utwór", "kreska", "normalny utwor"),
        ]
        for sid, artist, title, akey, tkey in songs:
            con.execute(
                "INSERT OR REPLACE INTO songs(id,artist,title,artist_key,title_key,release_date,created_at) VALUES(?,?,?,?,?,?,?)",
                (sid, artist, title, akey, tkey, None, now),
            )
        plays = [
            ("2026-08-22T10:01", "ESKA", "Jingle", "eska", "jingle", 1001),
            ("2026-08-22T10:02", "Artist", "ESKA News", "artist", "eska news", 1002),
            ("2026-08-22T10:03", "Kreska", "Normalny utwór", "kreska", "normalny utwor", 1003),
        ]
        for played_at, artist, title, akey, tkey, sid in plays:
            con.execute(
                """INSERT INTO airplay_plays(station_id,played_at,artist,title,artist_key,title_key,song_id,source_url,retrieved_at)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (123, played_at, artist, title, akey, tkey, sid, "", now),
            )
        con.execute(
            """INSERT OR REPLACE INTO airplay_windows(
                   station_id,play_date,start_hour,end_hour,fetched_at,play_count,source_url,success,message
               ) VALUES(?,?,?,?,?,?,?,?,?)""",
            (123, "2026-08-22", 10, 12, now, 3, "", 1, ""),
        )

    monkeypatch.setattr(db, "_INITIALIZED_DB_PATH", None)
    db.init_db()

    with db.connect() as con:
        remaining = con.execute(
            "SELECT artist,title FROM airplay_plays WHERE station_id=123 ORDER BY played_at"
        ).fetchall()
        assert [(r[0], r[1]) for r in remaining] == [("Kreska", "Normalny utwór")]
        assert con.execute("SELECT COUNT(*) FROM songs WHERE id IN (1001,1002)").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM songs WHERE id=1003").fetchone()[0] == 1
        assert con.execute(
            "SELECT play_count FROM airplay_windows WHERE station_id=123 AND play_date='2026-08-22' AND start_hour=10"
        ).fetchone()[0] == 1
        marker = con.execute("SELECT value FROM app_meta WHERE key='airplay_eska_jingle_cleanup_v1'").fetchone()[0]
        assert "plays=2" in marker and "songs=2" in marker
