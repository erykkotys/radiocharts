from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "radiocharts/app.py").read_text(encoding="utf-8")
ANDROID = (ROOT / "android/RadioChartsAndroid/app/src/main/java/pl/radiocharts/mobile/MainActivity.kt").read_text(encoding="utf-8")


def test_android_setup_does_not_request_removed_tools_package():
    for name in ["android-apk.yml", "docker.yml"]:
        workflow = (ROOT / ".github/workflows" / name).read_text(encoding="utf-8")
        assert "android-actions/setup-android@v4" in workflow
        assert "packages: ''" in workflow
        assert 'sdkmanager "platform-tools" "platforms;android-35" "build-tools;35.0.0"' in workflow


def test_song_screen_links_official_olis_awards_database():
    url = "https://www.olis.pl/charts/oficjalna-lista-wyroznien"
    assert url in APP
    assert "OLiS wyróżnienia ↗" in APP
    assert url in ANDROID
    assert "OLiS wyróżnienia ↗" in ANDROID
