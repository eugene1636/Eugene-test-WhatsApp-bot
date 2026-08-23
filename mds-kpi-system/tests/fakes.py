"""Fixture doubles for the source systems. No network in the test suite.

The warehouse is not faked. It is Postgres, and db/schema.sql carries rules that
only Postgres can enforce, so those tests use a real database (see conftest.py).
"""
from __future__ import annotations

from typing import Any

from src.errors import SourceError


class FakeStripe:
    """Stands in for StripeSource. Invoices are plain dicts, as Stripe returns."""

    def __init__(self, invoices: list[dict], fail: str | None = None) -> None:
        self.invoices = invoices
        self.fail = fail
        self.calls: list[dict] = []

    def list_invoices(self, **params: Any) -> list[dict]:
        if self.fail:
            raise SourceError("stripe", self.fail)
        self.calls.append(params)
        rows = [i for i in self.invoices if i.get("status") == params.get("status", "paid")]
        if "customer" in params:
            rows = [i for i in rows if i["customer"]["id"] == params["customer"]]
        created = params.get("created") or {}
        if "gte" in created:
            rows = [i for i in rows if i["created"] >= created["gte"]]
        if "lte" in created:
            rows = [i for i in rows if i["created"] <= created["lte"]]
        if "lt" in created:
            rows = [i for i in rows if i["created"] < created["lt"]]
        limit = params.get("limit")
        return rows[:limit] if limit else rows


class FakeGhl:
    def __init__(
        self,
        calendars: list[dict] | None = None,
        events: dict[str, list[dict]] | None = None,
        contacts: dict[str, dict] | None = None,
        fail: str | None = None,
    ) -> None:
        self.calendars = calendars or [{"id": "cal_disc", "name": "Discovery Call"}]
        self.events = events or {}
        self.contacts = contacts or {}
        self.fail = fail

    def _guard(self) -> None:
        if self.fail:
            raise SourceError("gohighlevel", self.fail)

    def list_calendars(self) -> list[dict]:
        self._guard()
        return self.calendars

    def list_events(self, calendar_id: str, start_ms: int, end_ms: int) -> list[dict]:
        self._guard()
        return [
            e
            for e in self.events.get(calendar_id, [])
            if start_ms <= int(e.get("startTime", 0)) <= end_ms
        ]

    def get_contact(self, contact_id: str) -> dict:
        self._guard()
        return self.contacts.get(contact_id, {})

    def search_contact_by_email(self, email: str) -> dict | None:
        self._guard()
        for contact in self.contacts.values():
            if (contact.get("email") or "").lower() == email:
                return contact
        return None


MONTH = 30 * 86_400
YEAR = 365 * 86_400


def invoice(
    invoice_id: str,
    customer_id: str,
    created: int,
    amount_cents: int,
    *,
    email: str = "",
    name: str = "",
    interval: str = "month",
    billing_reason: str = "subscription_create",
    status: str = "paid",
    paid_at: int | None = None,
    line_shape: str = "price",
) -> dict:
    """One Stripe invoice.

    line_shape picks which era of the API the line item looks like:
    - "price"   pre-2025, or a 2025 invoice with the price expanded
    - "plan"    the legacy plan field
    - "pricing" 2025+, where the line only carries a bare price id and the
                interval has to come off the period
    """
    settled = created if paid_at is None else paid_at
    span = YEAR if interval == "year" else MONTH
    period = {"start": settled, "end": settled + span}
    if line_shape == "price":
        line = {"price": {"recurring": {"interval": interval}}, "period": period}
    elif line_shape == "plan":
        line = {"plan": {"interval": interval}, "period": period}
    else:
        line = {
            "pricing": {"price_details": {"price": "price_123"}, "type": "price_details"},
            "period": period,
        }
    return {
        "id": invoice_id,
        "status": status,
        "created": created,
        "amount_paid": amount_cents,
        "currency": "usd",
        "billing_reason": billing_reason,
        "customer": {"id": customer_id, "email": email, "name": name},
        "status_transitions": {"paid_at": settled},
        "lines": {"data": [line]},
    }


def appointment(
    event_id: str, start_ms: int, status: str, email: str = "", contact_id: str = ""
) -> dict:
    return {
        "id": event_id,
        "startTime": start_ms,
        "appointmentStatus": status,
        "email": email,
        "contactId": contact_id,
        "title": "Discovery Call",
    }


class FakeRest:
    """Records requests and replays canned bodies, keyed by path.

    Used where the thing under test is the request we build (header, verb, body)
    rather than what we do with the answer.
    """

    def __init__(self, bodies: dict[str, dict] | None = None) -> None:
        self.bodies = bodies or {}
        self.requests: list[dict] = []

    def get(self, path: str, params: dict | None = None) -> dict:
        self.requests.append({"method": "GET", "path": path, "params": params})
        return self.bodies.get(path, {})

    def post(self, path: str, payload: dict) -> dict:
        self.requests.append({"method": "POST", "path": path, "json": payload})
        return self.bodies.get(path, {})
