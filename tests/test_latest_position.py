import pandas as pd
from radiocharts.metrics import _weekly_source_stats


def test_latest_position_is_none_when_song_missing_from_latest_issue():
    g = pd.DataFrame([
        {"chart_date": "2026-08-04", "chart_size": 20, "position": 11, "reported_weeks": None, "reported_peak": None},
        {"chart_date": "2026-08-05", "chart_size": 20, "position": 12, "reported_weeks": None, "reported_peak": None},
    ])
    stats = _weekly_source_stats(g, "2026-08-11")
    assert stats["latest_position"] is None
    assert stats["weeks"] >= 1
    assert stats["peak"] == 11


def test_latest_position_is_current_issue_only():
    g = pd.DataFrame([
        {"chart_date": "2026-08-04", "chart_size": 20, "position": 11, "reported_weeks": None, "reported_peak": None},
        {"chart_date": "2026-08-11", "chart_size": 20, "position": 3, "reported_weeks": None, "reported_peak": None},
    ])
    stats = _weekly_source_stats(g, "2026-08-11")
    assert stats["latest_position"] == 3
