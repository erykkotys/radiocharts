from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "android/RadioChartsAndroid/app/src/main/java/pl/radiocharts/mobile/MainActivity.kt").read_text(encoding="utf-8")
MODELS = (ROOT / "android/RadioChartsAndroid/app/src/main/java/pl/radiocharts/mobile/Models.kt").read_text(encoding="utf-8")
API = (ROOT / "radiocharts/api.py").read_text(encoding="utf-8")


def test_android_schedule_has_native_preview_player():
    assert "LocalRadioPreviewButton" in MAIN
    assert "previewVm.toggle(song)" in MAIN
    assert 'LocalRadioTimeline(store, "schedule", onSong, previewVm)' in MAIN
    assert 'LocalRadioTimeline(store, "played", onSong, previewVm)' in MAIN
    assert "LocalRadioCompare(store, onSong, previewVm)" in MAIN


def test_android_compare_portrait_prefers_played_and_landscape_has_both_sides():
    assert "val landscape = LocalConfiguration.current.orientation == Configuration.ORIENTATION_LANDSCAPE" in MAIN
    assert 'Text("Scheduled cutoff"' in MAIN
    assert 'Text("Played / live Zetta"' in MAIN
    assert "val played = pair.played_row" in MAIN
    assert "LocalRadioCompareSide(played, pair.status, \"played\"" in MAIN


def test_mobile_compare_api_exposes_side_specific_pairs():
    assert "data class LocalRadioComparePair" in MODELS
    assert "val display_pairs: List<LocalRadioComparePair>" in MODELS
    assert 'elif key == "display_pairs"' in API
    assert '"scheduled_row"' in API and '"played_row"' in API


def test_android_schedule_hour_bar_has_current_shortcut():
    assert 'Text("⌂"' in MAIN
    assert "onHour(LocalTime.now().hour)" in MAIN
