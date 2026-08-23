from datetime import date

import pytest

from src.connectors import gohighlevel as ghl
from src.errors import SourceError
from src.weeks import week_of
from tests.fakes import FakeGhl, appointment

WEEK = week_of(date(2026, 8, 17))
MID_WEEK_MS = WEEK.start_ms + 86_400_000


def make_source(**kwargs):
    return FakeGhl(events={"cal_disc": kwargs.pop("events", [])}, **kwargs)


def test_statuses_are_normalized_and_invalid_dropped():
    source = make_source(events=[
        appointment("ev1", MID_WEEK_MS, "showed", "a@x.com"),
        appointment("ev2", MID_WEEK_MS, "cancelled", "b@x.com"),
        appointment("ev3", MID_WEEK_MS, "noshow", "c@x.com"),
        appointment("ev4", MID_WEEK_MS, "confirmed", "d@x.com"),
        appointment("ev5", MID_WEEK_MS, "invalid", "e@x.com"),
    ])
    calls = ghl.fetch_discovery_calls(WEEK.start, WEEK.end, client=source)["calls"]
    assert [c["status"] for c in calls] == ["showed", "canceled", "no_show", "booked"]


def test_calendar_selection_fails_loud_when_nothing_matches():
    source = FakeGhl(calendars=[{"id": "cal_x", "name": "Onboarding"}])
    with pytest.raises(SourceError, match="GHL_DISCOVERY_CALENDAR_IDS"):
        ghl.fetch_discovery_calls(WEEK.start, WEEK.end, client=source)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("MDS Summit Miami", "event"),
        ("Member referral", "referral"),
        ("Website application", "website"),
        ("Facebook Group", "facebook"),
        ("Second Seat", "second_seat"),
        ("", "unknown"),
        ("carrier pigeon", "unknown"),
    ],
)
def test_lead_source_bucketing(raw, expected):
    assert ghl.bucket_lead_source(raw) == expected


def test_lead_sources_marks_unmatched_emails_unknown():
    source = FakeGhl(contacts={"c1": {"id": "c1", "email": "a@x.com", "source": "Referral"}})
    payload = ghl.fetch_lead_sources(["a@x.com", "ghost@x.com"], client=source)
    assert payload["lead_sources"] == {"a@x.com": "referral", "ghost@x.com": "unknown"}
    assert payload["record_ids"] == ["c1"]
