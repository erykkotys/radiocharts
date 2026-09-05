from pathlib import Path


def test_android_ci_workflow_present_and_builds_apk():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github" / "workflows" / "android-apk.yml").read_text(encoding="utf-8")
    assert "android-actions/setup-android@v3" in workflow
    assert "gradle-version: '8.9'" in workflow
    assert "gradle :app:assembleRelease" in workflow
    assert "RadioCharts-Android-release.apk" in workflow
    assert "ANDROID_KEYSTORE_BASE64" in workflow


def test_version_current():
    root = Path(__file__).resolve().parents[1]
    assert (root / "VERSION").read_text(encoding="utf-8").strip() == "0.4.3"
