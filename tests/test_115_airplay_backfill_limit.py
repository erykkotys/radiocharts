from pathlib import Path

from radiocharts.airplay import AIRPLAY_BACKFILL_MAX_WINDOWS


def test_airplay_backfill_limit_is_500k_and_shared_with_ui():
    assert AIRPLAY_BACKFILL_MAX_WINDOWS == 500_000
    root = Path(__file__).resolve().parents[1]
    app = (root / "radiocharts" / "app.py").read_text(encoding="utf-8")
    airplay = (root / "radiocharts" / "airplay.py").read_text(encoding="utf-8")
    assert "estimated_windows <= AIRPLAY_BACKFILL_MAX_WINDOWS" in app
    assert "estimated_windows > AIRPLAY_BACKFILL_MAX_WINDOWS" in app
    assert "max_windows: int = AIRPLAY_BACKFILL_MAX_WINDOWS" in airplay
