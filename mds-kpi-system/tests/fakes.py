"""Fixture doubles for the source systems. No network in the test suite."""
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


class FakeTable:
    """In-memory stand-in for a pyairtable Table."""

    def __init__(self, rows: list[dict] | None = None) -> None:
        self.rows = rows or []
        self._next = len(self.rows) + 1

    def all(self, **kwargs: Any) -> list[dict]:
        formula = kwargs.get("formula")
        if not formula:
            return list(self.rows)
        return [r for r in self.rows if _matches(formula, r["fields"])]

    def create(self, fields: dict) -> dict:
        record = {"id": f"rec{self._next:04d}", "fields": dict(fields)}
        self._next += 1
        self.rows.append(record)
        return record

    def update(self, record_id: str, fields: dict) -> dict:
        for row in self.rows:
            if row["id"] == record_id:
                row["fields"].update(fields)
                return row
        raise KeyError(record_id)


def _matches(formula: str, fields: dict) -> bool:
    """Understands only the two formula shapes airtable_wh builds."""
    import re

    pairs = re.findall(r"\{(\w+)\}='([^']*)'", formula)
    return all(str(fields.get(key, "")) == value for key, value in pairs)


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
) -> dict:
    return {
        "id": invoice_id,
        "status": status,
        "created": created,
        "amount_paid": amount_cents,
        "currency": "usd",
        "billing_reason": billing_reason,
        "customer": {"id": customer_id, "email": email, "name": name},
        "status_transitions": {"paid_at": created},
        "lines": {"data": [{"price": {"recurring": {"interval": interval}}}]},
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
