from datetime import date

import pytest

from src.connectors import stripe_conn
from src.weeks import week_of
from tests.fakes import FakeStripe, invoice

WEEK = week_of(date(2026, 8, 17))
MID_WEEK = WEEK.start_ts + 86_400


def test_first_time_payers_are_counted():
    source = FakeStripe([
        invoice("in_1", "cus_a", MID_WEEK, 249_500, email="A@Example.com", interval="year"),
        invoice("in_2", "cus_b", MID_WEEK, 49_900, email="b@example.com"),
    ])
    payload = stripe_conn.fetch_new_member_payments(WEEK.start, WEEK.end, client=source)

    assert len(payload["new_members"]) == 2
    assert payload["new_members"][0]["email"] == "a@example.com"  # normalized
    assert payload["new_members"][0]["amount_dollars"] == 2495.0
    assert payload["new_members"][0]["plan_interval"] == "year"
    assert payload["record_ids"] == ["in_1", "in_2"]


def test_a_returning_customer_is_not_a_new_member():
    source = FakeStripe([
        invoice("in_old", "cus_a", WEEK.start_ts - 400_000, 49_900),
        invoice("in_new", "cus_a", MID_WEEK, 49_900),
        invoice("in_first", "cus_b", MID_WEEK, 49_900),
    ])
    payload = stripe_conn.fetch_new_member_payments(WEEK.start, WEEK.end, client=source)
    assert [m["customer_id"] for m in payload["new_members"]] == ["cus_b"]


def test_renewals_and_zero_dollar_invoices_are_excluded():
    source = FakeStripe([
        invoice("in_cycle", "cus_c", MID_WEEK, 49_900, billing_reason="subscription_cycle"),
        invoice("in_free", "cus_d", MID_WEEK, 0),
    ])
    payload = stripe_conn.fetch_new_member_payments(WEEK.start, WEEK.end, client=source)
    assert payload["new_members"] == []


def test_payments_outside_the_window_are_excluded():
    source = FakeStripe([
        invoice("in_early", "cus_e", WEEK.start_ts - 10, 49_900),
        invoice("in_late", "cus_f", WEEK.end_ts + 10, 49_900),
    ])
    payload = stripe_conn.fetch_new_member_payments(WEEK.start, WEEK.end, client=source)
    assert payload["new_members"] == []


def test_an_invoice_paid_inside_the_week_counts_even_if_raised_before_it():
    # raised on the Friday, card settled on the Tuesday
    source = FakeStripe([
        invoice("in_late", "cus_g", WEEK.start_ts - 3 * 86_400, 49_900, paid_at=MID_WEEK),
    ])
    payload = stripe_conn.fetch_new_member_payments(WEEK.start, WEEK.end, client=source)
    assert [m["invoice_id"] for m in payload["new_members"]] == ["in_late"]


def test_an_invoice_raised_in_the_week_but_paid_after_it_does_not_count():
    source = FakeStripe([
        invoice("in_open", "cus_h", MID_WEEK, 49_900, paid_at=WEEK.end_ts + 86_400),
    ])
    payload = stripe_conn.fetch_new_member_payments(WEEK.start, WEEK.end, client=source)
    assert payload["new_members"] == []


def test_a_retry_that_settles_an_older_invoice_late_is_still_the_first_payment():
    # in_first was raised before the week and only cleared inside it, after a
    # second invoice had already been raised. Paid order, not created order.
    source = FakeStripe([
        invoice("in_first", "cus_i", WEEK.start_ts - 5 * 86_400, 49_900, paid_at=MID_WEEK),
        invoice("in_second", "cus_i", MID_WEEK + 3600, 49_900, paid_at=MID_WEEK + 3600),
    ])
    payload = stripe_conn.fetch_new_member_payments(WEEK.start, WEEK.end, client=source)
    assert [m["invoice_id"] for m in payload["new_members"]] == ["in_first"]


@pytest.mark.parametrize("line_shape", ["price", "plan", "pricing"])
@pytest.mark.parametrize("interval", ["month", "year"])
def test_the_plan_interval_survives_every_stripe_line_item_shape(line_shape, interval):
    source = FakeStripe([
        invoice("in_1", "cus_a", MID_WEEK, 49_900, interval=interval, line_shape=line_shape),
    ])
    payload = stripe_conn.fetch_new_member_payments(WEEK.start, WEEK.end, client=source)
    assert payload["new_members"][0]["plan_interval"] == interval
