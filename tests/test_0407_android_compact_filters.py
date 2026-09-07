from pathlib import Path


def test_android_015_compacts_song_list_filters():
    root = Path(__file__).resolve().parents[1]
    main = (root / "android/RadioChartsAndroid/app/src/main/java/pl/radiocharts/mobile/MainActivity.kt").read_text(encoding="utf-8")
    gradle = (root / "android/RadioChartsAndroid/app/build.gradle.kts").read_text(encoding="utf-8")

    assert "horizontalScroll(rememberScrollState())" in main
    assert "CompactFilterButton(" in main
    assert 'listOf("1d" to "1d","7d" to "7d","28d" to "28d","90d" to "3m")' in main
    assert '"Daty ${shortDate(shownStart)}–${shortDate(shownEnd)}"' in main
    assert "showExactDates" in main
    assert 'CompactFilterButton(if(count == 0) "Stacje" else "Stacje ($count)")' in main
    assert 'Text("Odśwież / zastosuj filtry")' not in main
    assert 'trailingIcon={ TextButton(onClick={reload()}) { Text("OK") } }' in main
    assert 'versionCode = 11' in gradle
    assert 'versionName = "1.0.0"' in gradle


def test_version_0407():
    root = Path(__file__).resolve().parents[1]
    assert (root / "VERSION").read_text(encoding="utf-8").strip() == "1.0.0"
