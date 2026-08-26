from pathlib import Path

APP = Path('radiocharts/app.py').read_text(encoding='utf-8')


def test_0332_row_numbers_refresh_after_grid_sort_and_filter():
    assert "cellRenderer=JsCode(\"function(params){ return (params.node && params.node.rowIndex != null) ? String(params.node.rowIndex + 1) : ''; }\")" in APP
    assert "onSortChanged=row_number_refresh" in APP
    assert "onFilterChanged=row_number_refresh" in APP
    assert "refreshCells({columns: ['_row_number'], force: true})" in APP
