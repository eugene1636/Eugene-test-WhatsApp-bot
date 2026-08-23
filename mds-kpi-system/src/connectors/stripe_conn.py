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

# Stripe can only filter invoices on `created`, but we want invoices *paid* in
# the week. Pull a wider created-window and filter on paid_at, so an invoice
# raised on the Friday and paid on the Monday lands in the week it was paid.
PAID_LOOKBACK_DAYS = 7

# Deriving the plan interval from the line period, when no price object is
# expanded. Stripe removed `line.price` in the 2025 API versions.
YEARLY_MIN_DAYS = 300
MONTHLY_MIN_DAYS = 25


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
    """month | year | one_time. Read off the invoice line, never MRR fields.

    Three shapes, tried in order, because Stripe moved this twice:
    - `line.price.recurring.interval`, the pre-2025 shape and what you get if
      the price is expanded
    - `line.plan.interval`, the legacy shape
    - the length of `line.period`, which works on every API version and needs
      no expansion. In the 2025+ shape a line only carries
      `pricing.price_details.price`, a bare price id, so there is no interval to
      read without a second API call.
    """
    lines = _get(invoice, "lines") or {}
    for line in _get(lines, "data") or []:
        price = _get(line, "price") or {}
        interval = _get(_get(price, "recurring") or {}, "interval")
        if interval:
            return str(interval)
        interval = _get(_get(line, "plan") or {}, "interval")
        if interval:
            return str(interval)
        span = _period_days(line)
        if span is None:
            continue
        if span >= YEARLY_MIN_DAYS:
            return "year"
        if span >= MONTHLY_MIN_DAYS:
            return "month"
    return "one_time"


def _period_days(line: Any) -> float | None:
    period = _get(line, "period") or {}
    start, end = _get(period, "start"), _get(period, "end")
    if not start or not end or end <= start:
        return None
    return (int(end) - int(start)) / 86_400


def _paid_at(invoice: Any) -> datetime:
    transitions = _get(invoice, "status_transitions") or {}
    stamp = _get(transitions, "paid_at") or _get(invoice, "created")
    return datetime.fromtimestamp(int(stamp), tz=timezone.utc)


def fetch_new_member_payments(
    week_start: date, week_end: date, *, client: StripeSource | None = None
) -> dict:
    """First-time membership payments settled in the week.

    A payment counts as a first-time membership payment when it was *paid*
    inside the window, collected more than $0, and is the earliest paid invoice
    that customer has. That last check is what makes this a *new member* number
    rather than a payments number.
    """
    week = _window(week_start, week_end)
    source = client or StripeSource()

    lookback = week.start_ts - PAID_LOOKBACK_DAYS * 86_400
    candidates = source.list_invoices(
        created={"gte": lookback, "lte": week.end_ts},
        status="paid",
        limit=100,
        expand=["data.customer"],
    )

    new_members: list[dict] = []
    for invoice in candidates:
        amount_cents = int(_get(invoice, "amount_paid") or 0)
        if amount_cents <= 0:
            continue
        paid_at = _paid_at(invoice)
        if not week.start_dt <= paid_at.astimezone(week.start_dt.tzinfo) <= week.end_dt:
            continue
        if _get(invoice, "billing_reason") not in FIRST_PAYMENT_REASONS:
            continue
        customer_id = _customer_id(invoice)
        if customer_id is None:
            continue
        if not _is_first_paid_invoice(source, customer_id, _get(invoice, "id")):
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
                "paid_at": paid_at.isoformat(),
            }
        )

    return {
        "source": "stripe",
        "week_start": week.start.isoformat(),
        "week_end": week.end.isoformat(),
        "new_members": new_members,
        "record_ids": [m["invoice_id"] for m in new_members],
    }


def _is_first_paid_invoice(
    source: StripeSource, customer_id: str, invoice_id: str | None
) -> bool:
    """Is this the earliest invoice the customer has ever actually paid?

    Compared on paid_at rather than created, because a card retry can settle an
    older invoice after a newer one. Asking "is this the first" rather than "is
    there an earlier one" also keeps the candidate itself from disqualifying it,
    which matters now that the pull window reaches back before the week.
    """
    paid = [
        inv
        for inv in source.list_invoices(customer=customer_id, status="paid", limit=100)
        if int(_get(inv, "amount_paid") or 0) > 0
    ]
    if not paid:
        return False
    earliest = min(paid, key=lambda inv: _paid_at(inv))
    return _get(earliest, "id") == invoice_id


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
