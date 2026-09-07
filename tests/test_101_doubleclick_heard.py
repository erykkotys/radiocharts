from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "radiocharts" / "app.py").read_text(encoding="utf-8")


def test_101_no_open_column_and_doubleclick_identity_navigation():
    assert '"details", "Otwórz"' not in APP
    assert 'onCellDoubleClicked=GRID_DOUBLE_CLICK_HANDLER' in APP
    assert "field !== 'artist' && field !== 'title'" in APP
    assert "params.node.setDataValue('_open_request', sid)" in APP


def test_101_heard_checkbox_is_present_but_derived_and_read_only():
    assert '"heard", "✓"' in APP
    assert 'Przesłuchany — zaznacza się automatycznie' in APP
    assert 'show["heard"] = show["status"].fillna("Nie słuchałem").astype(str).ne("Nie słuchałem")' in APP
    assert '"preview", "heard", "status", "downloaded"' in APP
