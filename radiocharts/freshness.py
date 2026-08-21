from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


def _latest_weekday_on_or_before(day: date, weekday: int) -> date:
    return day - timedelta(days=(day.weekday() - int(weekday)) % 7)


def _latest_business_day(day: date) -> date:
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def source_cadence_info(source: str, when: date | datetime | None = None) -> tuple[str, date]:
    """Human cadence label plus conservative newest-issue expectation.

    The returned expected date uses the same date semantics as each parser:
    publication day for daily lists, end-of-period for UK/OLiS, and Billboard's
    Saturday "Week of" issue date.
    """
    tz = ZoneInfo("Europe/Warsaw")
    if when is None:
        now = datetime.now(tz)
    elif isinstance(when, datetime):
        now = when.astimezone(tz) if when.tzinfo else when.replace(tzinfo=tz)
    else:
        now = datetime.combine(when, datetime.max.time()).replace(tzinfo=tz)
    today = now.date()

    def previous_business(d: date) -> date:
        return _latest_business_day(d - timedelta(days=1))

    source = str(source).upper()
    if source == "RMF":
        expected = _latest_business_day(today)
        if today.weekday() < 5 and now.hour < 20:
            expected = previous_business(today)
        return "pn–pt · ok. 19:00", expected

    if source == "ZET":
        expected = today if now.hour >= 20 else today - timedelta(days=1)
        return "codziennie · od 19:00", expected

    if source == "OLIA":
        # Reporting period ends on Friday. On Friday itself the just-ending
        # period is not treated as already due.
        base = today - timedelta(days=1) if today.weekday() == 4 else today
        return "tygodniowo · okres do pt", _latest_weekday_on_or_before(base, 4)

    if source == "OLIS":
        # Stored chart_date is the END of the reporting period (Thursday).
        # The following weekly edition is not assumed available on Friday morning.
        release = _latest_weekday_on_or_before(today, 4)  # Friday
        if today.weekday() == 4 and now.hour < 18:
            release -= timedelta(days=7)
        return "tygodniowo · okres do czw", release - timedelta(days=1)

    if source == "ESKA":
        # The page does not expose a reliable issue date; collector stamps read day.
        return "pn–pt · data = dzień odczytu", _latest_business_day(today)

    if source == "UK":
        # A Friday Official Charts edition covers Fri–Thu and our chart_date is
        # the Thursday END of that range. Before Friday's new release, yesterday's
        # Thursday remains the expected latest end date.
        release = _latest_weekday_on_or_before(today, 4)
        if today.weekday() == 4 and now.hour < 18:
            release -= timedelta(days=7)
        return "pt · okres pt–czw", release + timedelta(days=6)

    if source == "BILLBOARD":
        # Hot 100 uses a Saturday "Week of" issue date that is published earlier.
        # Conservatively roll to the new issue from Tuesday evening Warsaw time.
        release = _latest_weekday_on_or_before(today, 1)
        if today.weekday() == 1 and now.hour < 18:
            release -= timedelta(days=7)
        return "tygodniowo · data wydania: sob", release + timedelta(days=4)

    return "—", today
