from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "radiocharts" / "app.py").read_text(encoding="utf-8")


def test_release_version_106():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "1.0.6"
    gradle = (ROOT / "android" / "RadioChartsAndroid" / "app" / "build.gradle.kts").read_text(encoding="utf-8")
    assert 'versionCode = 17' in gradle
    assert 'versionName = "1.0.6"' in gradle


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


def test_share_column_resolves_exact_songlink_from_itunes_track_id():
    assert '"spotify_copy", "Udostępnij"' in APP
    assert "https://itunes.apple.com/search?term=" in APP
    assert "x.trackId" in APP
    assert "https://song.link/i/" in APP
    assert "tab.location.replace(shareUrl)" in APP
