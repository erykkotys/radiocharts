from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "radiocharts" / "app.py").read_text(encoding="utf-8")


def test_listened_checkbox_refreshes_immediately_from_status():
    assert "GRID_CELL_VALUE_CHANGED_HANDLER" in APP
    assert "field !== 'status'" in APP
    assert "row.heard = listened" in APP
    assert "columns: ['heard']" in APP
    assert "onCellValueChanged=GRID_CELL_VALUE_CHANGED_HANDLER" in APP


def test_listened_and_downloaded_style_actual_ag_grid_checkbox_glyphs():
    assert 'cellClass="rc-listened-checkbox"' in APP
    assert 'cellClass="rc-downloaded-checkbox"' in APP
    assert 'cellRendererParams={"disabled": True}' in APP
    assert '.rc-listened-checkbox .ag-checkbox-input-wrapper.ag-disabled' in APP
    assert '.rc-listened-checkbox .ag-checkbox-input-wrapper.ag-checked::after' in APP
    assert '.rc-downloaded-checkbox .ag-checkbox-input-wrapper.ag-checked::after' in APP
    assert '"color": "#ff2d2d !important"' in APP
    assert '"color": "#22c55e !important"' in APP
