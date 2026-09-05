from pathlib import Path


def test_android_014_player_is_not_owned_by_lazy_row_and_library_has_inline_controls():
    root = Path(__file__).resolve().parents[1]
    main = (root / "android/RadioChartsAndroid/app/src/main/java/pl/radiocharts/mobile/MainActivity.kt").read_text(encoding="utf-8")
    gradle = (root / "android/RadioChartsAndroid/app/build.gradle.kts").read_text(encoding="utf-8")

    assert "class PreviewPlayerVm" in main
    assert "override fun onCleared()" in main
    assert "DisposableEffect(Unit){onDispose{player?.release()}}" not in main
    assert 'composable("library") { SongListScreen("library", "Baza", nav::navigate, withPeriod=true, previewVm = previewVm) }' in main
    assert "PreviewButton(s, previewVm)" in main
    assert "InlineStatusMenu(" in main
    assert 'versionCode = 5' in gradle
    assert 'versionName = "0.1.4"' in gradle


def test_android_014_airplay_defaults_to_period_spins_and_has_exact_dates():
    root = Path(__file__).resolve().parents[1]
    main = (root / "android/RadioChartsAndroid/app/src/main/java/pl/radiocharts/mobile/MainActivity.kt").read_text(encoding="utf-8")

    assert 'if (mode == "airplay") {' in main
    assert 'before = before.copy(sort = "spins", descending = true)' in main
    assert "DatePickerButton(" in main
    assert 'label = "Od"' in main
    assert 'label = "Do"' in main
    assert 'period = "custom"' in main


def test_version_0406():
    root = Path(__file__).resolve().parents[1]
    assert (root / "VERSION").read_text(encoding="utf-8").strip() == "0.4.6"
