"""Warehouse tests. These run against a real Postgres, not a stub.

The rules this module is protecting (append-only history, no available metric
without a value, no snapshot for an unknown metric_id) are enforced in
db/schema.sql, so testing them against anything other than Postgres would test
nothing.
"""
from datetime import date, datetime, timezone

import pytest

from src.models import MetricResult, SourceRun
from src.registry import load
from src.warehouse import WarehouseError

WEEK = date(2026, 8, 17)
PRIOR = date(2026, 8, 10)


@pytest.fixture
def seeded(warehouse):
    warehouse.seed_metrics(list(load().kpis.values()))
    return warehouse


def source_run(status="success", error=None):
    now = datetime.now(timezone.utc)
    return SourceRun("stripe", WEEK, status, now, now, records_fetched=3, error=error)


def test_seeding_is_idempotent_and_covers_the_whole_board(warehouse):
    specs = list(load().kpis.values())
    warehouse.seed_metrics(specs)
    warehouse.seed_metrics(specs)
    assert len(warehouse.known_metric_ids()) == 13


def test_a_snapshot_round_trips_with_its_sub_metrics(seeded):
    seeded.write_snapshot(
        MetricResult(
            metric_id="new_members_paid",
            week_start=WEEK,
            value=3.0,
            sub_metrics={"by_lead_source": {"event": 2}},
            source_refs={"stripe_invoice_ids": ["in_1"]},
        )
    )
    history = seeded.history("new_members_paid", [WEEK])
    assert len(history) == 1
    assert history[0].value == 3.0
    assert history[0].sub_metrics["by_lead_source"]["event"] == 2


def test_the_database_assigns_the_revision(seeded):
    first = seeded.write_snapshot(MetricResult("new_members_paid", WEEK, 3.0))
    second = seeded.write_snapshot(MetricResult("new_members_paid", WEEK, 9.0))
    assert (first["revision"], second["revision"]) == (0, 1)
    assert seeded.next_revision("new_members_paid", WEEK) == 2


def test_history_returns_the_latest_revision_only(seeded):
    seeded.write_snapshot(MetricResult("new_members_paid", PRIOR, 1.0))
    seeded.write_snapshot(MetricResult("new_members_paid", WEEK, 3.0))
    seeded.write_snapshot(MetricResult("new_members_paid", WEEK, 9.0))

    history = seeded.history("new_members_paid", [PRIOR, WEEK])
    assert [(s.week_start, s.value) for s in history] == [(PRIOR, 1.0), (WEEK, 9.0)]


def test_history_skips_weeks_that_were_never_computed(seeded):
    seeded.write_snapshot(MetricResult("new_members_paid", WEEK, 3.0))
    assert len(seeded.history("new_members_paid", [PRIOR, WEEK])) == 1


def test_the_database_refuses_to_rewrite_history(seeded):
    seeded.write_snapshot(MetricResult("new_members_paid", WEEK, 3.0))
    with pytest.raises(Exception, match="append-only"):
        with seeded._cursor() as cur:
            cur.execute("update kpi.snapshots set value = 99")


def test_the_database_refuses_to_delete_history(seeded):
    seeded.write_snapshot(MetricResult("new_members_paid", WEEK, 3.0))
    with pytest.raises(Exception, match="append-only"):
        with seeded._cursor() as cur:
            cur.execute("delete from kpi.snapshots")


def test_an_unavailable_metric_is_recorded_with_its_reason(seeded):
    seeded.write_snapshot(
        MetricResult.unavailable("discovery_calls_showed", WEEK, "gohighlevel: 503")
    )
    snapshot = seeded.history("discovery_calls_showed", [WEEK])[0]
    assert snapshot.value is None
    assert snapshot.error == "gohighlevel: 503"
    assert not snapshot.available


def test_an_unavailable_metric_without_a_reason_is_refused(seeded):
    silent = MetricResult("new_members_paid", WEEK, None)  # no value, no reason
    with pytest.raises(WarehouseError, match="which source failed"):
        seeded.write_snapshot(silent)


def test_a_metric_id_that_is_not_in_the_registry_is_refused(seeded):
    with pytest.raises(WarehouseError):
        seeded.write_snapshot(MetricResult("mrr_from_stripe_subs", WEEK, 1.0))


def test_write_week_is_one_transaction(seeded):
    good = MetricResult("new_members_paid", WEEK, 3.0)
    bad = MetricResult("not_a_real_metric", WEEK, 1.0)

    with pytest.raises(WarehouseError):
        seeded.write_week([good, bad], [source_run()])

    # the good row rolled back with the bad one, so the week can be re-run clean
    assert seeded.history("new_members_paid", [WEEK]) == []
    assert seeded.next_revision("new_members_paid", WEEK) == 0


def test_write_week_records_snapshots_and_source_runs_together(seeded):
    written = seeded.write_week(
        [
            MetricResult("new_members_paid", WEEK, 3.0),
            MetricResult.unavailable("discovery_calls_showed", WEEK, "gohighlevel: 503"),
        ],
        [source_run(), source_run("failed", "401 invalid key")],
    )
    assert [w["revision"] for w in written] == [0, 0]
    with seeded._cursor() as cur:
        cur.execute("select status, error from kpi.source_runs order by status")
        assert cur.fetchall() == [("failed", "401 invalid key"), ("success", None)]


def test_the_board_view_carries_the_four_week_average(seeded):
    for week, value in zip(
        [date(2026, 7, 20), date(2026, 7, 27), date(2026, 8, 3), PRIOR, WEEK],
        [2.0, 4.0, 6.0, 8.0, 3.0],
    ):
        seeded.write_snapshot(MetricResult("new_members_paid", week, value))

    with seeded._cursor() as cur:
        cur.execute(
            "select week_start, value, avg_4w from kpi.board where metric_id = %s",
            ("new_members_paid",),
        )
        week_start, value, avg_4w = cur.fetchone()
    assert (week_start, value) == (WEEK, 3.0)
    assert float(avg_4w) == 5.0  # 4, 6, 8 and 2 -> the four weeks before this one


def test_the_board_lists_every_kpi_even_before_it_has_data(seeded):
    with seeded._cursor() as cur:
        cur.execute("select count(*) from kpi.board")
        assert cur.fetchone()[0] == 13
