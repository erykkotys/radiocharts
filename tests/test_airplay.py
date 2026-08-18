from radiocharts.airplay import parse_playlist_html, parse_station_catalog


def test_parse_station_catalog_options():
    html = '<select name="r">' + ''.join(f'<option value="{i}">Radio {i}</option>' for i in range(1, 12)) + '</select><select name="time_from"><option value="2">2</option></select>'
    rows = parse_station_catalog(html)
    assert {x['id'] for x in rows} == set(range(1, 12))


def test_parse_playlist_rows():
    html = '''<h1>Playlista</h1><table>
      <tr><th>Godzina</th><th>Nazwa utworu</th></tr>
      <tr><td>19:05</td><td>Doctor Alban - It's My Life</td></tr>
      <tr><td>19:09</td><td>C-Bool / Giang Pham - Magic Symphony</td></tr>
      <tr><td>20:00</td><td></td></tr>
    </table>'''
    rows = parse_playlist_html(html, '2016-11-26')
    assert len(rows) == 2
    assert rows[0]['played_at'] == '2016-11-26T19:05:00'
    assert rows[0]['artist'] == 'Doctor Alban'
    assert rows[0]['title'] == "It's My Life"


def test_airplay_db_summary(tmp_path, monkeypatch):
    import radiocharts.db as db
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'airplay.db')
    monkeypatch.setattr(db, '_INITIALIZED_DB_PATH', None)
    db.init_db()
    db.upsert_airplay_stations([{'id': 2, 'name': 'RMF FM'}, {'id': 3, 'name': 'Eska'}])
    db.save_airplay_plays(2, 'RMF FM', '2026-08-18', [
        {'played_at': '2026-08-18T10:00:00', 'artist': 'Artist', 'title': 'Song'},
        {'played_at': '2026-08-18T12:00:00', 'artist': 'Artist', 'title': 'Song'},
    ], window_key='00-10')
    db.save_airplay_plays(3, 'Eska', '2026-08-18', [
        {'played_at': '2026-08-18T11:00:00', 'artist': 'Artist', 'title': 'Song'},
    ], window_key='00-10')
    rows = db.airplay_summary('2026-08-18', '2026-08-18', [2, 3])
    assert rows[0]['plays'] == 3
    assert rows[0]['station_count'] == 2
    assert db.airplay_window_done(2, '2026-08-18', '00-10') is True


def test_airplay_daily_rollup_does_not_double_count_duplicate_spin(tmp_path, monkeypatch):
    import radiocharts.db as db
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'airplay_daily.db')
    monkeypatch.setattr(db, '_INITIALIZED_DB_PATH', None)
    db.init_db()
    db.upsert_airplay_stations([{'id': 2, 'name': 'RMF FM'}])
    spin = {'played_at': '2026-08-18T10:00:00', 'artist': 'Artist', 'title': 'Song'}
    db.save_airplay_plays(2, 'RMF FM', '2026-08-18', [spin], window_key='a')
    db.save_airplay_plays(2, 'RMF FM', '2026-08-18', [spin], window_key='b')
    rows = db.airplay_summary('2026-08-18', '2026-08-18', [2])
    assert rows[0]['plays'] == 1
    assert rows[0]['station_count'] == 1
