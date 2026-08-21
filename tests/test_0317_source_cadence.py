from datetime import datetime
from zoneinfo import ZoneInfo

from radiocharts.freshness import source_cadence_info


def test_freshness_semantics_friday_morning_2026_08_21():
    now = datetime(2026, 8, 21, 11, 14, tzinfo=ZoneInfo("Europe/Warsaw"))
    expected = {
        "RMF": "2026-08-20",
        "ZET": "2026-08-20",
        "OLIA": "2026-08-14",
        "OLIS": "2026-08-13",
        "ESKA": "2026-08-21",
        "UK": "2026-08-20",
        "BILLBOARD": "2026-08-22",
    }
    for source, day in expected.items():
        _, got = source_cadence_info(source, now)
        assert got.isoformat() == day, (source, got)


def test_uk_rolls_to_new_period_after_friday_release():
    now = datetime(2026, 8, 21, 19, 0, tzinfo=ZoneInfo("Europe/Warsaw"))
    _, got = source_cadence_info("UK", now)
    assert got.isoformat() == "2026-08-27"


def test_olis_rolls_to_just_finished_period_after_friday_release():
    now = datetime(2026, 8, 21, 19, 0, tzinfo=ZoneInfo("Europe/Warsaw"))
    _, got = source_cadence_info("OLIS", now)
    assert got.isoformat() == "2026-08-20"
