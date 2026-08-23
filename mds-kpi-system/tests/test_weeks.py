from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from src.weeks import Week, last_full_week, parse_week, trailing, week_of

ET = ZoneInfo("America/New_York")


def test_week_of_snaps_to_monday():
    week = week_of(date(2026, 8, 20))  # a Thursday
    assert week.start == date(2026, 8, 17)
    assert week.end == date(2026, 8, 23)


def test_week_rejects_a_non_monday_start():
    with pytest.raises(ValueError):
        Week(start=date(2026, 8, 18), end=date(2026, 8, 24))


def test_monday_6am_run_returns_the_week_that_just_closed():
    now = datetime(2026, 8, 24, 6, 0, tzinfo=ET)  # Monday
    week = last_full_week(now)
    assert week.start == date(2026, 8, 17)
    assert week.end == date(2026, 8, 23)


def test_window_covers_the_whole_sunday_in_eastern():
    week = week_of(date(2026, 8, 17))
    assert datetime.fromtimestamp(week.start_ts, ET).hour == 0
    end = datetime.fromtimestamp(week.end_ts, ET)
    assert (end.date(), end.hour, end.minute) == (date(2026, 8, 23), 23, 59)


def test_window_survives_the_dst_change():
    # US DST ends Sunday 2026-11-01, so this week is 169 hours long.
    week = week_of(date(2026, 10, 26))
    hours = (week.end_ts - week.start_ts) / 3600
    assert round(hours) == 169


def test_trailing_excludes_the_reported_week_by_default():
    week = week_of(date(2026, 8, 17))
    weeks = trailing(week, 4)
    assert [w.start.isoformat() for w in weeks] == [
        "2026-07-20",
        "2026-07-27",
        "2026-08-03",
        "2026-08-10",
    ]


def test_trailing_can_include_the_reported_week():
    week = week_of(date(2026, 8, 17))
    weeks = trailing(week, 4, include_self=True)
    assert weeks[-1].start == date(2026, 8, 17)
    assert len(weeks) == 4


def test_parse_week_accepts_any_day_in_the_week():
    assert parse_week("2026-08-22").start == date(2026, 8, 17)
