from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "radiocharts" / "app.py").read_text(encoding="utf-8")


def test_played_timeline_refreshes_as_one_fragment():
    assert "@st.fragment(run_every=5.0)" in APP
    assert "def _render_local_played_timeline_fragment" in APP
    assert "fresh_revision = local_station_revision()" in APP
    assert "_render_local_now_playing_fragment(selected_date, revision)" in APP


def test_now_playing_is_not_a_separate_fragment_anymore():
    marker = "def _render_local_now_playing_fragment(service_date: str, revision: str | None = None)"
    pos = APP.index(marker)
    before = APP[max(0, pos-80):pos]
    assert "@st.fragment" not in before


def test_release_version():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "1.2.26"
    gradle = (ROOT / "android" / "RadioChartsAndroid" / "app" / "build.gradle.kts").read_text(encoding="utf-8")
    assert 'versionCode = 49' in gradle
    assert 'versionName = "1.2.26"' in gradle
