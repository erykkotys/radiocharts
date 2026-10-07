from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_schedule_preview_uses_delegated_click_handler():
    app = (ROOT / 'radiocharts' / 'app.py').read_text(encoding='utf-8')
    assert '__rcPreviewDelegationInstalled' in app
    assert "closest('.rc-local-preview')" in app
    assert 'data-song=' in app
    assert 'onclick="event.stopPropagation(); if(window.top.__rcPlayPreview)' not in app


def test_release_1223():
    assert (ROOT / 'VERSION').read_text(encoding='utf-8').strip() == '1.2.25'
    gradle = (ROOT / 'android' / 'RadioChartsAndroid' / 'app' / 'build.gradle.kts').read_text(encoding='utf-8')
    assert 'versionCode = 48' in gradle
    assert 'versionName = "1.2.25"' in gradle
