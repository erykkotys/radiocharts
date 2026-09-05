from pathlib import Path


def test_android_016_pins_cf_statuses_and_adds_spotify_to_cards():
    root = Path(__file__).resolve().parents[1]
    main = (root / "android/RadioChartsAndroid/app/src/main/java/pl/radiocharts/mobile/MainActivity.kt").read_text(encoding="utf-8")
    gradle = (root / "android/RadioChartsAndroid/app/build.gradle.kts").read_text(encoding="utf-8")

    assert 'val pinned = listOf("Baza CF1", "Baza CF2")' in main
    assert 'androidStatusOrder(state.meta.statuses)' in main
    assert main.count('androidStatusOrder(statuses).forEach') >= 2
    assert 'modifier=Modifier.heightIn(max=420.dp)' in main
    assert 'SpotifyButton(s, compact = true)' in main
    assert 'https://open.spotify.com/search/$q' in main
    assert 'versionCode = 7' in gradle
    assert 'versionName = "0.1.6"' in gradle


def test_version_0408():
    root = Path(__file__).resolve().parents[1]
    assert (root / "VERSION").read_text(encoding="utf-8").strip() == "0.4.8"
