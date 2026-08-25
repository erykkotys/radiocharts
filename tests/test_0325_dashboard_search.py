from pathlib import Path

APP = (Path(__file__).resolve().parents[1] / "radiocharts" / "app.py").read_text(encoding="utf-8")


def test_0325_dashboard_grid_key_tracks_search_and_filters():
    assert "dashboard_grid_state = quote(" in APP
    assert "downloaded_choice" in APP and "selected_statuses" in APP and "dashboard_grid_state = quote(" in APP
    assert 'key=f"dashboard_grid_{lookback}_{scope}_{source_layout}_{dashboard_grid_state}"' in APP


def test_0325_version():
    version = (Path(__file__).resolve().parents[1] / "VERSION").read_text(encoding="utf-8").strip()
    assert version == "0.3.28"
