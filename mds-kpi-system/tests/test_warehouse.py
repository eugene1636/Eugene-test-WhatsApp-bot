import json
from datetime import date

from src.connectors.airtable_wh import (
    METRICS_TABLE,
    SNAPSHOTS_TABLE,
    SOURCE_RUNS_TABLE,
    Warehouse,
)
from src.models import MetricResult
from src.registry import load
from tests.fakes import FakeTable

WEEK = date(2026, 8, 17)


def warehouse():
    return Warehouse(
        tables={
            METRICS_TABLE: FakeTable(),
            SNAPSHOTS_TABLE: FakeTable(),
            SOURCE_RUNS_TABLE: FakeTable(),
        }
    )


def test_snapshot_write_serializes_sub_metrics_and_refs():
    wh = warehouse()
    result = MetricResult(
        metric_id="new_members_paid",
        week_start=WEEK,
        value=3.0,
        sub_metrics={"by_lead_source": {"event": 2}},
        source_refs={"stripe_invoice_ids": ["in_1"]},
    )
    record = wh.write_snapshot(result)

    fields = record["fields"]
    assert fields["key"] == "new_members_paid|2026-08-17|r0"
    assert fields["value"] == 3.0
    assert fields["available"] is True
    assert json.loads(fields["sub_metrics"])["by_lead_source"]["event"] == 2
    assert json.loads(fields["source_refs"])["stripe_invoice_ids"] == ["in_1"]


def test_corrections_append_a_new_revision_and_leave_history_alone():
    wh = warehouse()
    wh.write_snapshot(MetricResult("new_members_paid", WEEK, 3.0))
    wh.write_snapshot(MetricResult("new_members_paid", WEEK, 4.0))

    rows = wh.table(SNAPSHOTS_TABLE).rows
    assert [r["fields"]["revision"] for r in rows] == [0, 1]
    assert [r["fields"]["value"] for r in rows] == [3.0, 4.0]  # original untouched


def test_history_returns_the_latest_revision_per_week_oldest_first():
    wh = warehouse()
    wh.write_snapshot(MetricResult("new_members_paid", date(2026, 8, 10), 1.0))
    wh.write_snapshot(MetricResult("new_members_paid", WEEK, 3.0))
    wh.write_snapshot(MetricResult("new_members_paid", WEEK, 9.0))  # correction

    history = wh.history("new_members_paid", [date(2026, 8, 10), WEEK])
    assert [(s.week_start.isoformat(), s.value) for s in history] == [
        ("2026-08-10", 1.0),
        ("2026-08-17", 9.0),
    ]


def test_unavailable_metrics_are_still_recorded():
    wh = warehouse()
    wh.write_snapshot(MetricResult.unavailable("discovery_calls_showed", WEEK, "ghl 503"))
    fields = wh.table(SNAPSHOTS_TABLE).rows[0]["fields"]
    assert fields["value"] is None
    assert fields["available"] is False
    assert fields["error"] == "ghl 503"


def test_seeding_the_registry_twice_does_not_duplicate_rows():
    wh = warehouse()
    specs = list(load().kpis.values())
    first = wh.seed_metrics(specs)
    second = wh.seed_metrics(specs)

    assert len(wh.table(METRICS_TABLE).rows) == 13
    assert first == second  # same record ids, updated in place
