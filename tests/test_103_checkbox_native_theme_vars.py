from pathlib import Path

APP = (Path(__file__).resolve().parents[1] / "radiocharts" / "app.py").read_text(encoding="utf-8")

def test_checkbox_columns_use_native_ag_grid_renderer_and_scoped_theme_vars():
    assert 'cellRenderer="agCheckboxCellRenderer"' in APP
    assert '"--ag-checkbox-checked-color": "#ff2d2d"' in APP
    assert '"--ag-checkbox-checked-color": "#22c55e"' in APP
    assert '"--ag-checkbox-unchecked-color": "#6b7280"' in APP
    assert 'cellRendererParams={"disabled": False}' in APP
    assert '"pointer-events": "none !important"' in APP
    assert 'document.createElement' not in APP[APP.find('if "heard" in show.columns'):APP.find('if "note" in show.columns')]

def test_release_104_metadata():
    root = Path(__file__).resolve().parents[1]
    assert (root / "VERSION").read_text(encoding="utf-8").strip() == "1.0.6"
    gradle = (root / "android" / "RadioChartsAndroid" / "app" / "build.gradle.kts").read_text(encoding="utf-8")
    assert 'versionCode = 17' in gradle
    assert 'versionName = "1.0.6"' in gradle
