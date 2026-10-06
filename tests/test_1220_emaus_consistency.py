from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "radiocharts/app.py").read_text(encoding="utf-8")
LOCAL = (ROOT / "radiocharts/local_station.py").read_text(encoding="utf-8")
API = (ROOT / "radiocharts/api.py").read_text(encoding="utf-8")
ANDROID = (ROOT / "android/RadioChartsAndroid/app/src/main/java/pl/radiocharts/mobile/MainActivity.kt").read_text(encoding="utf-8")
MODELS = (ROOT / "android/RadioChartsAndroid/app/src/main/java/pl/radiocharts/mobile/Models.kt").read_text(encoding="utf-8")


def test_1220_web_has_shared_emaus_tabs_colors_and_collapsible_traffic():
    assert '["Scheduled", "ETM", "Played", "Porównanie", "Utwory", "Import"]' in APP
    assert "REKLAMA/AUTOPROMOCJA" in APP
    assert "details.rc-traffic-block" in APP
    assert "--rc-song:#f4f4f5" in APP
    assert "--rc-link:#f4cf57" in APP
    assert "--rc-etm:#69d6ff" in APP
    assert "--rc-toh:#ff79c6" in APP
    assert "--rc-traffic:#ff5d5d" in APP


def test_1220_etm_is_whole_day_three_column_and_ignore_resets_default():
    assert "def _render_local_etm_page" in APP
    assert 'value=True,\n        key="our_radio_etm_ignore_resets"' in APP
    assert "column_count = min(3" in APP
    assert "grid-template-rows:repeat" in APP


def test_1220_custom_element_presets_are_persisted():
    assert 'LOCAL_ELEMENT_PRESETS_SETTING = "emaus_element_presets_json_v1"' in APP
    assert "def _local_save_element_preset" in APP
    assert '"Zapisz preset"' in APP
    assert "set_app_settings" in APP


def test_1220_midnight_carry_rejects_next_day_queued_rows_and_repairs_old_snapshots():
    assert "if actual.hour != 23:" in LOCAL
    assert '"native_midnight_guard"' in LOCAL
    assert "abs(inherited) >= 10 * 60 * 1000" in LOCAL


def test_1220_played_continuity_and_inline_progress_exist_web_and_android():
    assert "def _local_played_continuity_rows" in APP
    assert 'row["_display_phase"] = "future_schedule"' in APP
    assert "rc-row-progress" in APP
    assert "rc-played-past" in APP
    assert "def _mobile_played_continuity" in API
    assert 'row["display_phase"] = "future_schedule"' in API
    assert '"future_schedule"' in ANDROID
    assert "LocalRadioTrafficBlock" in ANDROID


def test_1220_hour_navigation_and_song_deep_links_include_comparison():
    assert "def _render_local_hour_nav" in APP
    assert "window.parent.document" in APP
    assert "data-target=\"now\"" in APP
    assert "our-radio-compare-hour-" in APP
    assert "rc-hour-nav" in APP
    assert "rc-local-song-link" in APP
    assert "LocalHourJumpBar" in ANDROID
    assert "LocalRadioCompare(store, onSong)" in ANDROID
    assert "song_id: Int?" in MODELS


def test_1220_android_has_separate_etm_tab_and_traffic_blocks():
    assert 'listOf("Scheduled", "ETM", "Played", "Porównanie", "Utwory", "Import")' in ANDROID
    assert "LocalRadioEtm(store)" in ANDROID
    assert "REKLAMA/AUTOPROMOCJA" in ANDROID
    assert "var ignoreResets by remember { mutableStateOf(true) }" in ANDROID
