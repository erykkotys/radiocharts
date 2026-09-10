from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "radiocharts" / "app.py").read_text(encoding="utf-8")


def test_release_version_105():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "1.0.5"
    gradle = (ROOT / "android" / "RadioChartsAndroid" / "app" / "build.gradle.kts").read_text(encoding="utf-8")
    assert 'versionCode = 16' in gradle
    assert 'versionName = "1.0.5"' in gradle


def test_status_editor_is_bounded_and_page_has_bottom_room():
    assert '"valueListMaxHeight": 310' in APP
    assert '"valueListMaxWidth": 220' in APP
    assert 'padding-bottom: 8rem !important;' in APP
    # Natural status order remains untouched.
    assert '*BASE_STATUSES' in APP
    assert 'RADIO_STATUS_TOP_DOWN = list(reversed(RADIO_STATUS_BOTTOM_UP))' in APP


def test_spotify_is_native_anchor_for_ctrl_click():
    assert 'SPOTIFY_LINK_RENDERER' in APP
    assert "document.createElement('a')" in APP
    assert "a.href = url" in APP
    assert "a.target = '_blank'" in APP
    assert "ev.stopPropagation()" in APP
    assert 'cellRenderer=SPOTIFY_LINK_RENDERER' in APP


def test_share_column_resolves_exact_songlink_from_itunes_track_id():
    assert '"spotify_copy", "Udostępnij"' in APP
    assert "https://itunes.apple.com/search?term=" in APP
    assert "x.trackId" in APP
    assert "https://song.link/i/" in APP
    assert "tab.location.replace(shareUrl)" in APP
