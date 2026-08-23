"""End to end: pull, compute, snapshot, validate, recap. No network."""
from __future__ import annotations

import json
from datetime import date

import pytest

from src import context as context_module
from src import run_weekly
from src.connectors.airtable_wh import (
    METRICS_TABLE,
    SNAPSHOTS_TABLE,
    SOURCE_RUNS_TABLE,
    Warehouse,
)
from src.weeks import week_of
from tests.fakes import FakeGhl, FakeStripe, FakeTable, appointment, invoice

WEEK = week_of(date(2026, 8, 17))
MID = WEEK.start_ts + 86_400
MID_MS = WEEK.start_ms + 86_400_000


@pytest.fixture
def wired(monkeypatch):
    """Fake sources plus an in-memory warehouse, wired into run_weekly."""
    sources = {
        "stripe": FakeStripe([
            invoice("in_1", "cus_a", MID, 249_500, email="a@x.com", interval="year"),
            invoice("in_2", "cus_b", MID, 49_900, email="b@x.com"),
        ]),
        "gohighlevel": FakeGhl(
            events={"cal_disc": [
                appointment("ev1", MID_MS, "showed", "a@x.com"),
                appointment("ev2", MID_MS, "cancelled", "z@x.com"),
            ]},
            contacts={"c1": {"id": "c1", "email": "a@x.com", "source": "MDS Summit"}},
        ),
    }
    monkeypatch.setattr(context_module, "_build_client", lambda source: sources[source])

    warehouse = Warehouse(tables={
        METRICS_TABLE: FakeTable(),
        SNAPSHOTS_TABLE: FakeTable(),
        SOURCE_RUNS_TABLE: FakeTable(),
    })
    monkeypatch.setattr(run_weekly, "Warehouse", lambda *a, **k: warehouse)
    return warehouse


def run(args, capsys):
    code = run_weekly.main(args)
    return code, json.loads(capsys.readouterr().out)


def test_dry_run_computes_everything_and_writes_nothing(wired, capsys):
    code, out = run(["--week", "2026-08-17", "--no-llm", "--json"], capsys)

    assert code == 0
    values = {r["metric_id"]: r["value"] for r in out["results"]}
    assert values == {
        "new_members_paid": 2.0,
        "new_member_cash_collected": 2994.0,
        "discovery_calls_showed": 1.0,
    }
    assert out["snapshots_written"] == 0
    assert wired.table(SNAPSHOTS_TABLE).rows == []
    assert all(d["status"] == "dry_run" or d["status"] == "skipped" for d in out["deliveries"])


def test_send_appends_snapshots_and_source_runs(wired, capsys):
    code, out = run(["--week", "2026-08-17", "--no-llm", "--send", "--json"], capsys)

    assert code == 0
    assert out["snapshots_written"] == 3
    keys = [r["fields"]["key"] for r in wired.table(SNAPSHOTS_TABLE).rows]
    assert keys == [
        "new_members_paid|2026-08-17|r0",
        "new_member_cash_collected|2026-08-17|r0",
        "discovery_calls_showed|2026-08-17|r0",
    ]
    assert len(wired.table(SOURCE_RUNS_TABLE).rows) == len(out["source_runs"])
    assert all(r["fields"]["status"] == "success" for r in wired.table(SOURCE_RUNS_TABLE).rows)


def test_both_department_and_exec_recaps_are_produced(wired, capsys):
    _, out = run(["--week", "2026-08-17", "--no-llm", "--json"], capsys)

    audiences = [r["audience"] for r in out["recaps"]]
    assert audiences == ["growth", "exec"]
    assert all(r["generated_by"] == "fallback" for r in out["recaps"])
    assert "New members paid: 2" in out["recaps"][0]["body"]


def test_a_5x_move_holds_the_send(wired, capsys):
    wired.write_snapshot(
        run_weekly.MetricResult("new_members_paid", date(2026, 8, 10), 20.0)
    )
    code, out = run(["--week", "2026-08-17", "--no-llm", "--send", "--json"], capsys)

    assert code == 1
    assert any(f["code"] == "move_over_5x" for f in out["findings"])
    assert out["deliveries"] == []
    # the snapshot is still written, we hold the message not the history
    assert out["snapshots_written"] == 3


def test_acknowledging_the_anomaly_lets_it_through(wired, capsys):
    wired.write_snapshot(
        run_weekly.MetricResult("new_members_paid", date(2026, 8, 10), 20.0)
    )
    code, out = run(
        ["--week", "2026-08-17", "--no-llm", "--send", "--acknowledge-anomalies", "--json"],
        capsys,
    )

    assert code == 0
    assert out["deliveries"] != []


def test_a_dead_source_still_sends_a_recap_that_says_unavailable(monkeypatch, wired, capsys):
    monkeypatch.setattr(
        context_module,
        "_build_client",
        lambda source: FakeStripe([], fail="401 invalid key")
        if source == "stripe"
        else FakeGhl(events={"cal_disc": []}),
    )
    code, out = run(["--week", "2026-08-17", "--no-llm", "--json"], capsys)

    assert code == 0
    assert any(f["code"] == "source_failed" for f in out["findings"])
    assert "unavailable this week, stripe: 401 invalid key" in out["recaps"][0]["body"]


def test_require_all_green_holds_the_send_on_a_dead_source(monkeypatch, wired, capsys):
    monkeypatch.setattr(
        context_module,
        "_build_client",
        lambda source: FakeStripe([], fail="401 invalid key")
        if source == "stripe"
        else FakeGhl(events={"cal_disc": []}),
    )
    code, _ = run(
        ["--week", "2026-08-17", "--no-llm", "--require-all-green", "--json"], capsys
    )
    assert code == 1


def test_an_unknown_department_is_refused(capsys):
    assert run_weekly.main(["--departments", "retention", "--json"]) == 2
