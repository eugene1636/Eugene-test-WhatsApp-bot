from datetime import date

import pytest

from src.connectors import gohighlevel as ghl
from src.errors import SourceError
from src.weeks import week_of
from tests.fakes import FakeGhl, FakeRest, appointment

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


# --- request shape ----------------------------------------------------------
# GoHighLevel moved both the version header and the contact search endpoint.
# These pin what we actually send.


def source_with(rest, monkeypatch, **env):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return ghl.GoHighLevelSource(api_key="k", location_id="loc", rest=rest)


def real_source(monkeypatch, **env):
    """A source with a real RestClient, so we can inspect the headers it builds."""
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("GHL_API_KEY", "test-key")
    monkeypatch.setenv("GHL_LOCATION_ID", "loc")
    return ghl.GoHighLevelSource()


def test_the_version_header_defaults_to_v3(monkeypatch):
    monkeypatch.delenv("GHL_API_VERSION", raising=False)
    assert real_source(monkeypatch).rest.headers["Version"] == "v3"


def test_the_version_header_can_be_pinned_for_an_older_token(monkeypatch):
    source = real_source(monkeypatch, GHL_API_VERSION="2021-04-15")
    assert source.rest.headers["Version"] == "2021-04-15"


def test_contact_search_posts_a_filter_by_default(monkeypatch):
    rest = FakeRest({"/contacts/search": {"contacts": [{"id": "c1", "email": "a@x.com"}]}})
    monkeypatch.delenv("GHL_CONTACT_SEARCH", raising=False)
    source = source_with(rest, monkeypatch)

    assert source.search_contact_by_email("a@x.com") == {"id": "c1", "email": "a@x.com"}
    sent = rest.requests[0]
    assert (sent["method"], sent["path"]) == ("POST", "/contacts/search")
    assert sent["json"]["filters"] == [
        {"field": "email", "operator": "eq", "value": "a@x.com"}
    ]


def test_contact_search_falls_back_to_the_older_get_when_configured(monkeypatch):
    rest = FakeRest({"/contacts/": {"contacts": [{"id": "c1", "email": "a@x.com"}]}})
    source = source_with(rest, monkeypatch, GHL_CONTACT_SEARCH="get")

    assert source.search_contact_by_email("a@x.com")["id"] == "c1"
    sent = rest.requests[0]
    assert (sent["method"], sent["path"]) == ("GET", "/contacts/")
    assert sent["params"]["query"] == "a@x.com"


def test_a_near_miss_email_is_not_treated_as_a_match(monkeypatch):
    rest = FakeRest({"/contacts/search": {"contacts": [{"id": "c9", "email": "aa@x.com"}]}})
    source = source_with(rest, monkeypatch)
    assert source.search_contact_by_email("a@x.com") is None


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("new", "booked"),
        ("confirmed", "booked"),
        ("active", "booked"),
        ("showed", "showed"),
        ("completed", "showed"),
        ("noshow", "no_show"),
        ("cancelled", "canceled"),
        ("invalid", "invalid"),
    ],
)
def test_every_documented_appointment_status_maps(raw, expected):
    assert ghl.normalize_status(raw) == expected
