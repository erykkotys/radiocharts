from pathlib import Path


def test_android_workflows_use_sdk_apksigner_path():
    root = Path(__file__).resolve().parents[1]
    expected = '$ANDROID_HOME/build-tools/35.0.0/apksigner'
    for rel in ['.github/workflows/android-apk.yml', '.github/workflows/docker.yml']:
        text = (root / rel).read_text(encoding='utf-8')
        assert expected in text
        assert 'run: apksigner verify' not in text


def test_version_0404():
    root = Path(__file__).resolve().parents[1]
    assert (root / 'VERSION').read_text(encoding='utf-8').strip() == '0.4.6'
