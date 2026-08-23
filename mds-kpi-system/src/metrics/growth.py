"""growth department metrics.

Expose: compute(week_start: date) -> list[MetricResult]
Specs live in config/kpis.yaml under departments.growth. Read them first.

Phase 1 of docs/roadmap.md: new_members_paid, new_member_cash_collected,
discovery_calls_showed. Sources are injected through RunContext so a failure in
one source only takes down the metrics that depend on it.
"""
from __future__ import annotations

from ..connectors import gohighlevel as ghl
from ..connectors import stripe_conn as stripe
from ..context import RunContext
from ..errors import SourceError
from ..models import MetricResult
from ..weeks import Week, trailing

LEAD_SOURCE_BUCKETS = ("event", "referral", "website", "facebook", "second_seat", "unknown")
CONVERSION_TRAILING_WEEKS = 4


def compute(week: Week, ctx: RunContext) -> list[MetricResult]:
    payments, payments_error = _pull_payments(week, ctx)
    calls, calls_error = _pull_calls(week, ctx)

    return [
        _new_members_paid(week, ctx, payments, payments_error),
        _new_member_cash_collected(week, payments, payments_error),
        _discovery_calls_showed(week, ctx, calls, calls_error),
    ]


# ------------------------------------------------------------------- pulls


def _pull_payments(week: Week, ctx: RunContext) -> tuple[dict | None, str | None]:
    try:
        payload = ctx.pull(
            "stripe",
            lambda client: stripe.fetch_new_member_payments(
                week.start, week.end, client=client
            ),
            note="new member first payments",
        )
    except SourceError as exc:
        return None, exc.detail
    return payload, None


def _pull_calls(week: Week, ctx: RunContext) -> tuple[dict | None, str | None]:
    try:
        payload = ctx.pull(
            "gohighlevel",
            lambda client: ghl.fetch_discovery_calls(week.start, week.end, client=client),
            note="discovery calls",
        )
    except SourceError as exc:
        return None, exc.detail
    return payload, None


# ----------------------------------------------------------------- metrics


def _new_members_paid(
    week: Week, ctx: RunContext, payments: dict | None, error: str | None
) -> MetricResult:
    if payments is None:
        return MetricResult.unavailable("new_members_paid", week.start, error or "stripe failed")

    members = payments["new_members"]
    emails = [m["email"] for m in members if m["email"]]

    by_lead_source: dict[str, object]
    ghl_contact_ids: list[str] = []
    try:
        attribution = ctx.pull(
            "gohighlevel",
            lambda client: ghl.fetch_lead_sources(emails, client=client),
            note="lead source attribution",
        )
    except SourceError as exc:
        by_lead_source = {"unavailable": f"gohighlevel failed: {exc.message}"}
        discovery_split = {"unavailable": f"gohighlevel failed: {exc.message}"}
    else:
        lookup = attribution["lead_sources"]
        ghl_contact_ids = attribution["record_ids"]
        counts = {bucket: 0 for bucket in LEAD_SOURCE_BUCKETS}
        for member in members:
            counts[lookup.get(member["email"], "unknown")] += 1
        by_lead_source = counts
        discovery_split = _discovery_split(week, ctx, members)

    return MetricResult(
        metric_id="new_members_paid",
        week_start=week.start,
        value=float(len(members)),
        sub_metrics={
            "by_lead_source": by_lead_source,
            "with_vs_without_discovery_call": discovery_split,
        },
        source_refs={
            "stripe_invoice_ids": payments["record_ids"],
            "gohighlevel_contact_ids": ghl_contact_ids,
        },
    )


def _discovery_split(week: Week, ctx: RunContext, members: list[dict]) -> dict:
    """Did each new member sit a discovery call in the trailing window?"""
    try:
        history = _trailing_calls(week, ctx)
    except SourceError as exc:
        return {"unavailable": f"gohighlevel failed: {exc.message}"}

    called = {c["email"] for c in history["calls"] if c["email"] and c["status"] == "showed"}
    with_call = sum(1 for m in members if m["email"] in called)
    return {"with": with_call, "without": len(members) - with_call}


def _new_member_cash_collected(
    week: Week, payments: dict | None, error: str | None
) -> MetricResult:
    if payments is None:
        return MetricResult.unavailable(
            "new_member_cash_collected", week.start, error or "stripe failed"
        )

    members = payments["new_members"]
    total_cents = sum(m["amount_cents"] for m in members)
    total = round(total_cents / 100, 2)

    mix: dict[str, dict[str, float]] = {}
    for member in members:
        interval = member["plan_interval"]
        bucket = "annual" if interval == "year" else "monthly" if interval == "month" else "other"
        entry = mix.setdefault(bucket, {"count": 0, "dollars": 0.0})
        entry["count"] += 1
        entry["dollars"] = round(entry["dollars"] + member["amount_dollars"], 2)

    return MetricResult(
        metric_id="new_member_cash_collected",
        week_start=week.start,
        value=total,
        sub_metrics={
            "avg_first_payment": round(total / len(members), 2) if members else 0.0,
            "plan_mix": mix,
            "new_member_count": len(members),
        },
        source_refs={"stripe_invoice_ids": payments["record_ids"]},
    )


def _discovery_calls_showed(
    week: Week, ctx: RunContext, calls: dict | None, error: str | None
) -> MetricResult:
    if calls is None:
        return MetricResult.unavailable(
            "discovery_calls_showed", week.start, error or "gohighlevel failed"
        )

    rows = calls["calls"]
    booked = len(rows)
    showed = sum(1 for c in rows if c["status"] == "showed")
    canceled = sum(1 for c in rows if c["status"] == "canceled")
    no_show = sum(1 for c in rows if c["status"] == "no_show")

    return MetricResult(
        metric_id="discovery_calls_showed",
        week_start=week.start,
        value=float(showed),
        sub_metrics={
            "booked": booked,
            "canceled": canceled,
            "no_show": no_show,
            "show_rate": round(showed / booked, 4) if booked else None,
            "trailing_4w_conversion_rate": _trailing_conversion(week, ctx),
        },
        source_refs={"gohighlevel_event_ids": calls["record_ids"]},
    )


def _trailing_conversion(week: Week, ctx: RunContext) -> dict:
    """Share of showed calls in the trailing 4 weeks that became paid members.

    A call converts when the same email shows up as a first-time membership
    payment inside the same trailing window. The payment lookup stops at the end
    of the reported week, so calls late in the window are still open and the
    rate is a floor, not a final number.
    """
    try:
        history = _trailing_calls(week, ctx)
        payments = _trailing_payments(week, ctx)
    except SourceError as exc:
        return {"unavailable": exc.message}

    paid_emails = {m["email"] for m in payments["new_members"] if m["email"]}
    showed = [c for c in history["calls"] if c["status"] == "showed" and c["email"]]
    converted = sum(1 for c in showed if c["email"] in paid_emails)
    return {
        "showed": len(showed),
        "converted": converted,
        "rate": round(converted / len(showed), 4) if showed else None,
        "window_weeks": CONVERSION_TRAILING_WEEKS,
        "note": "floor, late conversions land in later weeks",
    }


def _trailing_calls(week: Week, ctx: RunContext) -> dict:
    weeks = trailing(week, CONVERSION_TRAILING_WEEKS, include_self=True)
    return ctx.pull_once(
        f"ghl_calls_{CONVERSION_TRAILING_WEEKS}w_{week.label}",
        "gohighlevel",
        lambda client: ghl.fetch_discovery_calls_over(weeks, client=client),
        note="discovery calls, trailing 4 weeks",
    )


def _trailing_payments(week: Week, ctx: RunContext) -> dict:
    weeks = trailing(week, CONVERSION_TRAILING_WEEKS, include_self=True)
    return ctx.pull_once(
        f"stripe_payments_{CONVERSION_TRAILING_WEEKS}w_{week.label}",
        "stripe",
        lambda client: stripe.fetch_new_member_payments_over(weeks, client=client),
        note="new member payments, trailing 4 weeks",
    )
