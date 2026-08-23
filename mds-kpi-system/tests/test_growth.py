from datetime import date

from src.context import RunContext
from src.metrics import growth
from src.weeks import week_of
from tests.fakes import FakeGhl, FakeStripe, appointment, invoice

WEEK = week_of(date(2026, 8, 17))
MID = WEEK.start_ts + 86_400
MID_MS = WEEK.start_ms + 86_400_000
PRIOR_MS = WEEK.previous().start_ms + 86_400_000


def context(stripe_source, ghl_source):
    return RunContext(
        week=WEEK, clients={"stripe": stripe_source, "gohighlevel": ghl_source}
    )


def by_id(results):
    return {r.metric_id: r for r in results}


def default_stripe():
    return FakeStripe([
        invoice("in_1", "cus_a", MID, 249_500, email="a@x.com", interval="year"),
        invoice("in_2", "cus_b", MID, 49_900, email="b@x.com"),
        invoice("in_3", "cus_c", MID, 49_900, email="c@x.com"),
    ])


def default_ghl():
    return FakeGhl(
        events={
            "cal_disc": [
                appointment("ev1", MID_MS, "showed", "a@x.com"),
                appointment("ev2", MID_MS, "showed", "b@x.com"),
                appointment("ev3", MID_MS, "cancelled", "z@x.com"),
                appointment("ev4", PRIOR_MS, "showed", "c@x.com"),
            ]
        },
        contacts={
            "c1": {"id": "c1", "email": "a@x.com", "source": "MDS Summit"},
            "c2": {"id": "c2", "email": "b@x.com", "source": "Member referral"},
            "c3": {"id": "c3", "email": "c@x.com", "source": "Website application"},
        },
    )


def test_new_members_paid_counts_and_splits_by_lead_source():
    results = by_id(growth.compute(WEEK, context(default_stripe(), default_ghl())))
    metric = results["new_members_paid"]

    assert metric.value == 3.0
    assert metric.sub_metrics["by_lead_source"] == {
        "event": 1,
        "referral": 1,
        "website": 1,
        "facebook": 0,
        "second_seat": 0,
        "unknown": 0,
    }
    # c@x.com showed a call last week, still inside the trailing window.
    assert metric.sub_metrics["with_vs_without_discovery_call"] == {"with": 3, "without": 0}
    assert metric.source_refs["stripe_invoice_ids"] == ["in_1", "in_2", "in_3"]


def test_cash_collected_sums_dollars_and_splits_the_plan_mix():
    results = by_id(growth.compute(WEEK, context(default_stripe(), default_ghl())))
    metric = results["new_member_cash_collected"]

    assert metric.value == 3493.0
    assert metric.sub_metrics["avg_first_payment"] == 1164.33
    assert metric.sub_metrics["plan_mix"]["annual"] == {"count": 1, "dollars": 2495.0}
    assert metric.sub_metrics["plan_mix"]["monthly"] == {"count": 2, "dollars": 998.0}


def test_discovery_calls_showed_reports_the_funnel():
    results = by_id(growth.compute(WEEK, context(default_stripe(), default_ghl())))
    metric = results["discovery_calls_showed"]

    assert metric.value == 2.0
    assert metric.sub_metrics["booked"] == 3
    assert metric.sub_metrics["canceled"] == 1
    assert metric.sub_metrics["show_rate"] == 0.6667
    conversion = metric.sub_metrics["trailing_4w_conversion_rate"]
    assert conversion["showed"] == 3
    assert conversion["converted"] == 3
    assert conversion["rate"] == 1.0


def test_a_stripe_failure_makes_its_metrics_unavailable_never_zero():
    ctx = context(FakeStripe([], fail="401 invalid key"), default_ghl())
    results = by_id(growth.compute(WEEK, ctx))

    for metric_id in ("new_members_paid", "new_member_cash_collected"):
        assert results[metric_id].value is None
        assert "401 invalid key" in results[metric_id].error
    # GoHighLevel is fine, so the calls metric still reports.
    assert results["discovery_calls_showed"].value == 2.0
    assert ctx.failed_sources == ["stripe"]


def test_a_ghl_failure_keeps_the_stripe_metrics_and_flags_the_sub_metrics():
    ctx = context(default_stripe(), FakeGhl(fail="503 upstream"))
    results = by_id(growth.compute(WEEK, ctx))

    assert results["new_members_paid"].value == 3.0
    assert "503 upstream" in results["new_members_paid"].sub_metrics["by_lead_source"]["unavailable"]
    assert results["new_member_cash_collected"].value == 3493.0
    assert results["discovery_calls_showed"].value is None
    assert "503 upstream" in results["discovery_calls_showed"].error


def test_an_empty_week_is_a_real_zero_with_no_error():
    ctx = context(FakeStripe([]), FakeGhl(events={"cal_disc": []}))
    results = by_id(growth.compute(WEEK, ctx))

    assert results["new_members_paid"].value == 0.0
    assert results["new_members_paid"].error is None
    assert results["discovery_calls_showed"].sub_metrics["show_rate"] is None


def test_trailing_windows_are_pulled_once_per_run():
    ctx = context(default_stripe(), default_ghl())
    growth.compute(WEEK, ctx)
    trailing_runs = [r for r in ctx.runs if "trailing" in (r.note or "")]
    assert sorted(r.source for r in trailing_runs) == ["gohighlevel", "stripe"]
