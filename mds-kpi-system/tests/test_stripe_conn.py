from datetime import date

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
