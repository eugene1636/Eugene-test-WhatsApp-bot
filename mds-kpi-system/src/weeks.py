"""Week windows. Monday 00:00:00 to Sunday 23:59:59.999999, US Eastern.

Every metric in this system is keyed on the Monday date of its week. All source
pulls convert that window to whatever the source wants (unix seconds for Stripe,
epoch milliseconds for GoHighLevel, ISO strings for Airtable).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .config import timezone_name


def tz() -> ZoneInfo:
    return ZoneInfo(timezone_name())


@dataclass(frozen=True, order=True)
class Week:
    start: date  # Monday
    end: date  # Sunday

    def __post_init__(self) -> None:
        if self.start.weekday() != 0:
            raise ValueError(f"week must start on a Monday, got {self.start}")
        if self.end != self.start + timedelta(days=6):
            raise ValueError(f"week end must be start + 6 days, got {self.end}")

    @property
    def label(self) -> str:
        return self.start.isoformat()

    @property
    def start_dt(self) -> datetime:
        return datetime.combine(self.start, time.min, tzinfo=tz())

    @property
    def end_dt(self) -> datetime:
        return datetime.combine(self.end, time.max, tzinfo=tz())

    @property
    def start_ts(self) -> int:
        """Unix seconds, inclusive."""
        return int(self.start_dt.timestamp())

    @property
    def end_ts(self) -> int:
        """Unix seconds, inclusive."""
        return int(self.end_dt.timestamp())

    @property
    def start_ms(self) -> int:
        return self.start_ts * 1000

    @property
    def end_ms(self) -> int:
        return self.end_ts * 1000 + 999

    def previous(self, n: int = 1) -> "Week":
        return week_of(self.start - timedelta(weeks=n))

    def next(self, n: int = 1) -> "Week":
        return week_of(self.start + timedelta(weeks=n))

    def contains(self, moment: datetime) -> bool:
        return self.start_dt <= moment.astimezone(tz()) <= self.end_dt

    def __str__(self) -> str:  # pragma: no cover - display only
        return f"{self.start.isoformat()} to {self.end.isoformat()}"


def week_of(day: date) -> Week:
    """The Mon-Sun week containing `day`."""
    if isinstance(day, datetime):
        day = day.astimezone(tz()).date()
    monday = day - timedelta(days=day.weekday())
    return Week(start=monday, end=monday + timedelta(days=6))


def last_full_week(now: datetime | None = None) -> Week:
    """The most recent complete Mon-Sun week.

    Run Monday 6am ET, this returns the week that ended the night before.
    """
    moment = (now or datetime.now(tz())).astimezone(tz())
    return week_of(moment.date()).previous()


def trailing(week: Week, count: int, include_self: bool = False) -> list[Week]:
    """`count` weeks ending at `week`, oldest first."""
    if count < 1:
        return []
    last = week if include_self else week.previous()
    weeks = [last.previous(offset) for offset in range(count)]
    return sorted(weeks)


def parse_week(value: str) -> Week:
    """Accepts any date; snaps to the Monday of that week."""
    return week_of(date.fromisoformat(value))
