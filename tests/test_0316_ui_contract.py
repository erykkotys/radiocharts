from pathlib import Path

APP = (Path(__file__).resolve().parents[1] / "radiocharts" / "app.py").read_text(encoding="utf-8")


def test_details_column_uses_click_handler_not_raw_html_renderer():
    assert 'DETAILS_LABEL_FORMATTER' in APP
    assert 'field === \'details\'' in APP
    assert 'OPEN_LINK_RENDERER' not in APP


def test_dashboard_has_normalized_search_before_grid():
    assert 'key="dashboard_song_search"' in APP
    assert 'view = filter_song_rows(view, song_query)' in APP


def test_airplay_rank_searches_full_summary_before_top_limit():
    search_pos = APP.index('ranked = filter_song_rows(ranked, airplay_query)')
    head_pos = APP.index('ranked = ranked.head(int(top_n))', search_pos)
    assert search_pos < head_pos


def test_airplay_backfill_is_centralized_in_data_view():
    assert 'render_airplay_data_management(running)' in APP
    assert 'Pobieranie, uzupełnianie 24h, backfill i zarządzanie stacjami są teraz w zakładce **Dane**.' in APP


def test_spotify_copy_column_is_configured():
    assert '"spotify_copy", "Kopiuj"' in APP
    assert "field === 'spotify_copy'" in APP
