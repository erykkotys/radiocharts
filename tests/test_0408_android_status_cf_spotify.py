from pathlib import Path


def test_android_017_keeps_api_status_order_and_scrollable_picker_with_spotify():
    root = Path(__file__).resolve().parents[1]
    main = (root / "android/RadioChartsAndroid/app/src/main/java/pl/radiocharts/mobile/MainActivity.kt").read_text(encoding="utf-8")
    gradle = (root / "android/RadioChartsAndroid/app/build.gradle.kts").read_text(encoding="utf-8")

    assert 'private fun androidStatusOrder(statuses: List<String>): List<String> = statuses.distinct()' in main
    assert 'StatusPickerDialog(' in main
    assert 'LazyColumn(Modifier.heightIn(max=460.dp))' in main
    assert 'items(androidStatusOrder(statuses))' in main
    assert 'SpotifyButton(s, compact = true)' in main
    assert 'https://open.spotify.com/search/$q' in main
<<<<<<< HEAD
    assert 'versionCode = 26' in gradle
    assert 'versionName = "1.2.1"' in gradle
=======
    assert 'versionCode = 25' in gradle
    assert 'versionName = "1.2.0"' in gradle
>>>>>>> a98c8593defab725ea67d3c33366c2c60006ed9f


def test_version_0409():
    root = Path(__file__).resolve().parents[1]
<<<<<<< HEAD
    assert (root / "VERSION").read_text(encoding="utf-8").strip() == "1.2.1"
=======
    assert (root / "VERSION").read_text(encoding="utf-8").strip() == "1.2.0"
>>>>>>> a98c8593defab725ea67d3c33366c2c60006ed9f
