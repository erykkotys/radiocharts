from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "radiocharts" / "app.py").read_text(encoding="utf-8")


def test_release_version_106():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "1.2.27"
    gradle = (ROOT / "android" / "RadioChartsAndroid" / "app" / "build.gradle.kts").read_text(encoding="utf-8")
    assert 'versionCode = 50' in gradle
    assert 'versionName = "1.2.27"' in gradle


def test_status_editor_is_bounded_and_page_has_bottom_room():
    assert '"valueListMaxHeight": 310' in APP
    assert '"valueListMaxWidth": 220' in APP
    assert 'padding-bottom: 8rem !important;' in APP
    # Natural status order remains untouched.
    assert '*BASE_STATUSES' in APP
    assert 'RADIO_STATUS_TOP_DOWN = list(reversed(RADIO_STATUS_BOTTOM_UP))' in APP


def test_spotify_click_is_react_safe_and_supports_modifier_open():
    # Regression: returning HTMLAnchorElement from a JsCode renderer causes
    # Minified React error #31 in streamlit-aggrid.
    assert 'SPOTIFY_LABEL_FORMATTER' in APP
    assert "document.createElement('a')" not in APP
    assert 'cellRenderer=SPOTIFY_LINK_RENDERER' not in APP
    assert 'valueFormatter=SPOTIFY_LABEL_FORMATTER' in APP
    assert "if (field === 'spotify')" in APP
    assert "host.open(url, '_blank'" in APP
    assert 'ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.button === 1' in APP
    assert 'host.focus()' in APP


def test_share_column_resolves_direct_spotify_track_url():
    assert '"spotify_copy", "Udostępnij"' in APP
    assert "spotify-id-from-metadata/json" in APP
    assert "spotify_track_ids" in APP
    assert "https://open.spotify.com/track/" in APP
    assert "navigator.share" in APP
    assert "navigator.clipboard.writeText" in APP
    assert "https://song.link/i/" not in APP


def test_share_handler_avoids_async_await_aggrid_parser_regression():
    start = APP.index('GRID_CLICK_HANDLER = JsCode("""')
    end = APP.index('GRID_DOUBLE_CLICK_HANDLER = JsCode("""', start)
    handler = APP[start:end]
    assert 'async (' not in handler
    assert 'await ' not in handler
    assert 'var shareDirect = function(url)' in handler
    assert '.catch(function(' in handler
