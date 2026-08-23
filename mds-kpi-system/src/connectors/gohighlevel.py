"""gohighlevel connector.

Contract: expose fetch_* functions taking (week_start: date, week_end: date)
and returning plain dicts. No pandas here. Log every run to source_runs.
See CLAUDE.md conventions and config/kpis.yaml for which metrics need what.

Covers two things in Phase 1:
- discovery calls booked / canceled / showed (discovery_calls_showed)
- lead source attribution for new members (new_members_paid sub-metric)

Which calendars count as discovery is config, not code: set
GHL_DISCOVERY_CALENDAR_IDS, or leave it unset and every calendar whose name
matches GHL_DISCOVERY_CALENDAR_MATCH (default "discovery") is used.
"""
from __future__ import annotations

from datetime import date

from .. import config
from ..errors import SourceError
from ..weeks import Week, week_of
from .http import RestClient

API_BASE = "https://services.leadconnectorhq.com"
API_VERSION = "2021-07-28"

# GoHighLevel appointmentStatus -> our canonical status.
STATUS_MAP = {
    "new": "booked",
    "confirmed": "booked",
    "showed": "showed",
    "noshow": "no_show",
    "no-show": "no_show",
    "cancelled": "canceled",
    "canceled": "canceled",
    "invalid": "invalid",
}

# Free-text GHL contact source -> the lead source buckets in kpis.yaml.
LEAD_SOURCE_BUCKETS = (
    ("second seat", "second_seat"),
    ("second-seat", "second_seat"),
    ("referral", "referral"),
    ("refer", "referral"),
    ("facebook", "facebook"),
    (" fb", "facebook"),
    ("event", "event"),
    ("summit", "event"),
    ("chapter", "event"),
    ("website", "website"),
    ("web form", "website"),
    ("application", "website"),
    ("organic", "website"),
)


class GoHighLevelSource:
    def __init__(
        self,
        api_key: str | None = None,
        location_id: str | None = None,
        rest: RestClient | None = None,
    ) -> None:
        self.location_id = location_id or config.require("GHL_LOCATION_ID")
        self.rest = rest or RestClient(
            source="gohighlevel",
            base_url=API_BASE,
            headers={
                "Authorization": f"Bearer {api_key or config.require('GHL_API_KEY')}",
                "Version": API_VERSION,
                "Accept": "application/json",
            },
        )

    def list_calendars(self) -> list[dict]:
        body = self.rest.get("/calendars/", params={"locationId": self.location_id})
        return body.get("calendars") or []

    def list_events(self, calendar_id: str, start_ms: int, end_ms: int) -> list[dict]:
        body = self.rest.get(
            "/calendars/events",
            params={
                "locationId": self.location_id,
                "calendarId": calendar_id,
                "startTime": start_ms,
                "endTime": end_ms,
            },
        )
        return body.get("events") or []

    def get_contact(self, contact_id: str) -> dict:
        body = self.rest.get(f"/contacts/{contact_id}")
        return body.get("contact") or {}

    def search_contact_by_email(self, email: str) -> dict | None:
        body = self.rest.get(
            "/contacts/",
            params={"locationId": self.location_id, "query": email, "limit": 5},
        )
        for contact in body.get("contacts") or []:
            if (contact.get("email") or "").strip().lower() == email:
                return contact
        return None


def _window(week_start: date, week_end: date) -> Week:
    week = week_of(week_start)
    if week.end != week_end:
        raise ValueError(f"{week_start}..{week_end} is not a Mon-Sun week")
    return week


def discovery_calendar_ids(source: GoHighLevelSource) -> list[str]:
    configured = config.get_list("GHL_DISCOVERY_CALENDAR_IDS")
    if configured:
        return configured
    needle = (config.get("GHL_DISCOVERY_CALENDAR_MATCH") or "discovery").lower()
    matched = [
        cal["id"]
        for cal in source.list_calendars()
        if needle in (cal.get("name") or "").lower() and cal.get("id")
    ]
    if not matched:
        raise SourceError(
            "gohighlevel",
            f"no calendar name contains {needle!r}. Set GHL_DISCOVERY_CALENDAR_IDS.",
        )
    return matched


def normalize_status(raw: str | None) -> str:
    return STATUS_MAP.get((raw or "").strip().lower(), "booked")


def fetch_discovery_calls(
    week_start: date, week_end: date, *, client: GoHighLevelSource | None = None
) -> dict:
    """Every discovery call slotted inside the week, with its outcome.

    Booked = every non-invalid appointment on a discovery calendar in the week.
    Showed / canceled / no_show are read from appointmentStatus at pull time,
    which is why this metric is pulled after the week has closed.
    """
    week = _window(week_start, week_end)
    source = client or GoHighLevelSource()

    calls: list[dict] = []
    for calendar_id in discovery_calendar_ids(source):
        for event in source.list_events(calendar_id, week.start_ms, week.end_ms):
            status = normalize_status(event.get("appointmentStatus"))
            if status == "invalid":
                continue
            calls.append(
                {
                    "event_id": event.get("id"),
                    "calendar_id": calendar_id,
                    "contact_id": event.get("contactId"),
                    "email": (event.get("email") or "").strip().lower(),
                    "title": event.get("title") or "",
                    "status": status,
                    "start_time": event.get("startTime"),
                }
            )

    return {
        "source": "gohighlevel",
        "week_start": week.start.isoformat(),
        "week_end": week.end.isoformat(),
        "calls": calls,
        "record_ids": [c["event_id"] for c in calls],
    }


def bucket_lead_source(raw: str | None) -> str:
    text = (raw or "").strip().lower()
    if not text:
        return "unknown"
    for needle, bucket in LEAD_SOURCE_BUCKETS:
        if needle in text:
            return bucket
    return "unknown"


def fetch_lead_sources(
    emails: list[str], *, client: GoHighLevelSource | None = None
) -> dict:
    """Lead source bucket per email. Unmatched emails come back as 'unknown'."""
    source = client or GoHighLevelSource()
    by_email: dict[str, str] = {}
    contact_ids: list[str] = []
    for email in {e.strip().lower() for e in emails if e and e.strip()}:
        contact = source.search_contact_by_email(email)
        if not contact:
            by_email[email] = "unknown"
            continue
        raw = contact.get("source") or contact.get("attributionSource") or ""
        by_email[email] = bucket_lead_source(raw)
        if contact.get("id"):
            contact_ids.append(contact["id"])
    return {
        "source": "gohighlevel",
        "lead_sources": by_email,
        "record_ids": contact_ids,
    }


def fetch_discovery_calls_over(
    weeks: list[Week], *, client: GoHighLevelSource | None = None
) -> dict:
    """Same pull across several weeks, for the trailing conversion sub-metric."""
    source = client or GoHighLevelSource()
    calls: list[dict] = []
    for week in weeks:
        payload = fetch_discovery_calls(week.start, week.end, client=source)
        for call in payload["calls"]:
            call = dict(call)
            call["week_start"] = week.start.isoformat()
            calls.append(call)
    return {
        "source": "gohighlevel",
        "calls": calls,
        "record_ids": [c["event_id"] for c in calls],
    }
