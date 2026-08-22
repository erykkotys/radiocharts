from pathlib import Path


def test_version_badge_is_attached_to_streamlit_header_layer():
    app = (Path(__file__).resolve().parents[1] / "radiocharts" / "app.py").read_text(encoding="utf-8")
    assert '[data-testid="stHeader"]::after' in app
    assert 'content: "{_rc_version_css}"' in app
    assert 'right: 3.35rem' in app


def test_release_version_file_matches_package_version():
    root = Path(__file__).resolve().parents[1]
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    package = (root / "radiocharts" / "__init__.py").read_text(encoding="utf-8")
    assert version and version != "dev"
    assert f'__version__ = "{version}"' in package
