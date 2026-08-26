from pathlib import Path

APP = Path('radiocharts/app.py').read_text(encoding='utf-8')


def test_0333_song_airplay_can_filter_specific_stations():
    assert 'key="song_airplay_station_scope"' in APP
    assert '["Wszystkie stacje", "Wybrane stacje"]' in APP
    assert 'key="song_airplay_station_multiselect"' in APP
    assert 'tuple(sorted(song_station_ids))' in APP
    assert 'airplay_station_coverage(song_station_ids, song_air_start, song_air_end)' in APP


def test_0333_song_station_filter_updates_grid_identity_and_keeps_global_date_bounds():
    assert 'song_station_sig = "-".join(str(x) for x in sorted(song_station_ids)) or "none"' in APP
    assert 'key=f"song_airplay_grid_{song_id}_{song_air_start}_{song_air_end}_{song_station_sig}"' in APP
    assert 'song_cov = airplay_coverage(all_song_station_ids)' in APP
