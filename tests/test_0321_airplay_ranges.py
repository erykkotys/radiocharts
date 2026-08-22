from pathlib import Path

APP = (Path(__file__).resolve().parents[1] / "radiocharts" / "app.py").read_text(encoding="utf-8")


def test_airplay_has_compact_quick_range_presets():
    for label in [
        "Ostatni tydzień",
        "Ostatnie 2 tyg.",
        "Ostatni miesiąc",
        "Ostatnie 3 miesiące",
        "Ostatnie pół roku",
        "Ostatni rok",
        "Własny zakres",
    ]:
        assert label in APP
    assert 'key_prefix="airplay_range_v3"' in APP


def test_song_view_has_period_airplay_excerpt_and_station_detail():
    assert 'st.markdown("### Emisje radiowe")' in APP
    assert 'key_prefix=f"song_airplay_range_{song_id}"' in APP
    assert 'cached_airplay_track_detail(' in APP
    assert 'Szczegóły emisji per stacja i dzień' in APP
    assert '"Śr./dzień okresu"' in APP


def test_manual_documents_quick_ranges_and_song_airplay_section():
    assert "ostatni tydzień / 2 tygodnie / miesiąc / 3 miesiące / pół roku / rok" in APP
    assert "Na karcie **Utwór** jest osobna sekcja **Emisje radiowe**" in APP
