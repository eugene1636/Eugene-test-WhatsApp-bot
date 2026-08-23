"""stripe_conn connector.

Contract: expose fetch_* functions taking (week_start: date, week_end: date)
and returning plain dicts. No pandas here. Log every run to source_runs.
See CLAUDE.md conventions and config/kpis.yaml for which metrics need what.

HARD RULE (CLAUDE.md): never read subscription MRR or subscription amount fields.
Discounts, changed renewal dates and tier changes have made them unreliable for
us. Everything here is computed from invoices, which record dollars that actually
moved.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Iterable

from ..errors import SourceError
from ..weeks import Week, week_of

# billing_reason values that can represent a first membership payment.
FIRST_PAYMENT_REASONS = {"subscription_create", "manual", None, ""}


class StripeSource:
    """Thin wrapper so tests can hand the connector a fake with the same shape."""

    def __init__(self, api_key: str | None = None, stripe_module: Any = None) -> None:
        if stripe_module is None:
            import stripe as stripe_module  # noqa: PLC0415
        from ..config import require

        stripe_module.api_key = api_key or require("STRIPE_API_KEY")
        self._stripe = stripe_module

    def list_invoices(self, **params: Any) -> list[dict]:
        try:
            page = self._stripe.Invoice.list(**params)
            return list(page.auto_paging_iter())
        except Exception as exc:  # stripe raises its own hierarchy
            raise SourceError("stripe", f"invoice list failed: {exc}") from exc


def _window(week_start: date, week_end: date) -> Week:
    week = week_of(week_start)
    if week.end != week_end:
        raise ValueError(f"{week_start}..{week_end} is not a Mon-Sun week")
    return week


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _customer_id(invoice: Any) -> str | None:
    customer = _get(invoice, "customer")
    if isinstance(customer, str):
        return customer
    return _get(customer or {}, "id")


def _customer_field(invoice: Any, field: str) -> str | None:
    """Prefer the expanded customer object, fall back to the invoice snapshot."""
    customer = _get(invoice, "customer")
    if customer is not None and not isinstance(customer, str):
        value = _get(customer, field)
        if value:
            return value
    return _get(invoice, f"customer_{field}")


def _plan_interval(invoice: Any) -> str:
    """month | year | one_time. Read off the line item price, never MRR fields."""
    lines = _get(invoice, "lines") or {}
    for line in _get(lines, "data") or []:
        price = _get(line, "price") or {}
        recurring = _get(price, "recurring") or {}
        interval = _get(recurring, "interval")
        if interval:
            return str(interval)
    return "one_time"


def _paid_at(invoice: Any) -> datetime:
    transitions = _get(invoice, "status_transitions") or {}
    stamp = _get(transitions, "paid_at") or _get(invoice, "created")
    return datetime.fromtimestamp(int(stamp), tz=timezone.utc)


def fetch_new_member_payments(
    week_start: date, week_end: date, *, client: StripeSource | None = None
) -> dict:
    """First-time membership payments settled in the week.

    A payment counts as a first-time membership payment when the invoice was
    raised inside the window, reached status paid, collected more than $0, and
    the customer has no earlier paid invoice. That last check is what makes this
    a *new member* number rather than a payments number.
    """
    week = _window(week_start, week_end)
    source = client or StripeSource()

    candidates = source.list_invoices(
        created={"gte": week.start_ts, "lte": week.end_ts},
        status="paid",
        limit=100,
        expand=["data.customer"],
    )

    new_members: list[dict] = []
    for invoice in candidates:
        amount_cents = int(_get(invoice, "amount_paid") or 0)
        if amount_cents <= 0:
            continue
        if _get(invoice, "billing_reason") not in FIRST_PAYMENT_REASONS:
            continue
        customer_id = _customer_id(invoice)
        if customer_id is None:
            continue
        if _has_earlier_paid_invoice(source, customer_id, week.start_ts):
            continue
        new_members.append(
            {
                "customer_id": customer_id,
                "email": (_customer_field(invoice, "email") or "").strip().lower(),
                "name": _customer_field(invoice, "name") or "",
                "invoice_id": _get(invoice, "id"),
                "amount_cents": amount_cents,
                "amount_dollars": round(amount_cents / 100, 2),
                "currency": (_get(invoice, "currency") or "usd").lower(),
                "plan_interval": _plan_interval(invoice),
                "paid_at": _paid_at(invoice).isoformat(),
            }
        )

    return {
        "source": "stripe",
        "week_start": week.start.isoformat(),
        "week_end": week.end.isoformat(),
        "new_members": new_members,
        "record_ids": [m["invoice_id"] for m in new_members],
    }


def _has_earlier_paid_invoice(
    source: StripeSource, customer_id: str, before_ts: int
) -> bool:
    earlier = source.list_invoices(
        customer=customer_id,
        status="paid",
        created={"lt": before_ts},
        limit=1,
    )
    return any(int(_get(inv, "amount_paid") or 0) > 0 for inv in earlier)


def fetch_new_member_payments_over(
    weeks: Iterable[Week], *, client: StripeSource | None = None
) -> dict:
    """Same pull across several weeks. Used for trailing conversion windows."""
    source = client or StripeSource()
    members: list[dict] = []
    for week in weeks:
        payload = fetch_new_member_payments(week.start, week.end, client=source)
        for member in payload["new_members"]:
            member = dict(member)
            member["week_start"] = week.start.isoformat()
            members.append(member)
    return {
        "source": "stripe",
        "new_members": members,
        "record_ids": [m["invoice_id"] for m in members],
    }
