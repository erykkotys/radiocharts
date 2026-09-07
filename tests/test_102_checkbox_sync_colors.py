from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "radiocharts" / "app.py").read_text(encoding="utf-8")


def test_listened_checkbox_refreshes_immediately_from_status():
    assert "GRID_CELL_VALUE_CHANGED_HANDLER" in APP
    assert "field !== 'status'" in APP
    assert "row.heard = listened" in APP
    assert "columns: ['heard']" in APP
    assert "onCellValueChanged=GRID_CELL_VALUE_CHANGED_HANDLER" in APP


def test_listened_and_downloaded_use_scoped_ag_grid_checkbox_theme_variables():
    assert 'cellClass="rc-listened-checkbox"' in APP
    assert 'cellClass="rc-downloaded-checkbox"' in APP
    assert 'cellRendererParams={"disabled": False}' in APP
    assert '"--ag-checkbox-checked-color": "#ff2d2d"' in APP
    assert '"--ag-checkbox-checked-color": "#22c55e"' in APP
    assert '"--ag-checkbox-unchecked-color": "#6b7280"' in APP
    assert '"pointer-events": "none !important"' in APP
    assert '.ag-checkbox-input-wrapper.ag-checked::after' not in APP
