from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "radiocharts" / "app.py").read_text(encoding="utf-8")


def test_listened_checkbox_refreshes_immediately_from_status():
    assert "GRID_CELL_VALUE_CHANGED_HANDLER" in APP
    assert "field !== 'status'" in APP
    assert "row.heard = listened" in APP
    assert "columns: ['heard']" in APP
    assert "onCellValueChanged=GRID_CELL_VALUE_CHANGED_HANDLER" in APP


def test_listened_and_downloaded_have_distinct_checked_colors():
    assert 'cellClass="rc-listened-checkbox"' in APP
    assert 'cellClass="rc-downloaded-checkbox"' in APP
    assert '"#ff3b3b !important"' in APP
    assert '"#22c55e !important"' in APP
