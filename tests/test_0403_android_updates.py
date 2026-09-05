from __future__ import annotations

import hashlib
import json
from pathlib import Path


def test_android_update_metadata_and_version_comparison(tmp_path, monkeypatch):
    import radiocharts.api as api

    apk = tmp_path / "RadioCharts.apk"
    apk.write_bytes(b"signed-apk-placeholder")
    sha = hashlib.sha256(apk.read_bytes()).hexdigest()
    (tmp_path / "update.json").write_text(
        json.dumps(
            {
                "version_name": "0.1.2",
                "version_code": 3,
                "sha256": sha,
                "size_bytes": apk.stat().st_size,
                "git_sha": "abc1234",
                "built_at": "2026-09-05T18:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("RADIOCHARTS_ANDROID_DIR", str(tmp_path))

    older = api.android_update(current_version_code=2)
    current = api.android_update(current_version_code=3)
    assert older["available"] is True
    assert older["latest_version_name"] == "0.1.2"
    assert older["latest_version_code"] == 3
    assert older["download_url"] == "/api/v1/android/apk"
    assert older["sha256"] == sha
    assert current["available"] is False


def test_android_update_missing_release_is_safe(tmp_path, monkeypatch):
    import radiocharts.api as api

    monkeypatch.setenv("RADIOCHARTS_ANDROID_DIR", str(tmp_path))
    result = api.android_update(current_version_code=3)
    assert result["available"] is False
    assert result["reason"] == "not_published"


def test_android_012_has_self_update_install_flow_and_permanent_signing_contract():
    root = Path(__file__).resolve().parents[1]
    android = root / "android" / "RadioChartsAndroid"
    main = (android / "app/src/main/java/pl/radiocharts/mobile/MainActivity.kt").read_text(encoding="utf-8")
    updater = (android / "app/src/main/java/pl/radiocharts/mobile/Updater.kt").read_text(encoding="utf-8")
    api_kt = (android / "app/src/main/java/pl/radiocharts/mobile/Api.kt").read_text(encoding="utf-8")
    manifest = (android / "app/src/main/AndroidManifest.xml").read_text(encoding="utf-8")
    gradle = (android / "app/build.gradle.kts").read_text(encoding="utf-8")
    docker = (root / ".github/workflows/docker.yml").read_text(encoding="utf-8")
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")

    assert 'versionCode = 3' in gradle
    assert 'versionName = "0.1.2"' in gradle
    assert "ANDROID_KEYSTORE_FILE" in gradle
    assert "ANDROID_KEYSTORE_BASE64" in docker
    assert "assembleRelease" in docker
    assert "apksigner verify" in docker
    assert "dist/android/RadioCharts.apk" in docker
    assert "COPY dist/android /app/android" in dockerfile
    assert '@GET("api/v1/android/update")' in api_kt
    assert '@GET("api/v1/android/apk")' in api_kt
    assert "Sprawdź aktualizacje" in main
    assert "Dostępna aktualizacja" in main
    assert "AppUpdater.check" in main
    assert "AppUpdater.download" in main
    assert "REQUEST_INSTALL_PACKAGES" in manifest
    assert "FileProvider" in manifest
    assert "canRequestPackageInstalls" in updater
    assert "SHA-256" in updater


def test_version_0403():
    root = Path(__file__).resolve().parents[1]
    assert (root / "VERSION").read_text(encoding="utf-8").strip() == "0.4.4"
