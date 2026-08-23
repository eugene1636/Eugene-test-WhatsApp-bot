"""End to end: pull, compute, snapshot, validate, recap.

The source systems are fixture doubles; the warehouse is a real Postgres, so
these exercise the same SQL that runs on Monday.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from src import context as context_module
from src import run_weekly
from src.models import MetricResult
from src.registry import load
from src.weeks import week_of
from tests.fakes import FakeGhl, FakeStripe, appointment, invoice

WEEK = week_of(date(2026, 8, 17))
MID = WEEK.start_ts + 86_400
MID_MS = WEEK.start_ms + 86_400_000


def stripe_double():
    return FakeStripe([
        invoice("in_1", "cus_a", MID, 249_500, email="a@x.com", interval="year"),
        invoice("in_2", "cus_b", MID, 49_900, email="b@x.com"),
    ])


def ghl_double():
    return FakeGhl(
        events={"cal_disc": [
            appointment("ev1", MID_MS, "showed", "a@x.com"),
            appointment("ev2", MID_MS, "cancelled", "z@x.com"),
        ]},
        contacts={"c1": {"id": "c1", "email": "a@x.com", "source": "MDS Summit"}},
    )


def wire_sources(monkeypatch, stripe=None, ghl=None):
    sources = {"stripe": stripe or stripe_double(), "gohighlevel": ghl or ghl_double()}
    monkeypatch.setattr(context_module, "_build_client", lambda source: sources[source])
    return sources


@pytest.fixture
def wired(monkeypatch, warehouse):
    """Fake sources plus a seeded real warehouse, wired into run_weekly."""
    wire_sources(monkeypatch)
    warehouse.seed_metrics(list(load().kpis.values()))
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
    assert wired.history("new_members_paid", [WEEK.start]) == []
    assert all(d["status"] in {"dry_run", "skipped"} for d in out["deliveries"])


def test_send_appends_snapshots_and_source_runs(wired, capsys):
    code, out = run(["--week", "2026-08-17", "--no-llm", "--send", "--json"], capsys)

    assert code == 0
    assert out["snapshots_written"] == 3
    assert wired.history("new_members_paid", [WEEK.start])[0].value == 2.0
    with wired._cursor() as cur:
        cur.execute("select count(*) from kpi.source_runs where status = 'success'")
        assert cur.fetchone()[0] == len(out["source_runs"])


def test_a_second_send_of_the_same_week_appends_a_revision(wired, capsys):
    run(["--week", "2026-08-17", "--no-llm", "--send", "--json"], capsys)
    run(["--week", "2026-08-17", "--no-llm", "--send", "--json"], capsys)

    assert wired.next_revision("new_members_paid", WEEK.start) == 2
    assert len(wired.history("new_members_paid", [WEEK.start])) == 1  # latest only


def test_both_department_and_exec_recaps_are_produced(wired, capsys):
    _, out = run(["--week", "2026-08-17", "--no-llm", "--json"], capsys)

    assert [r["audience"] for r in out["recaps"]] == ["growth", "exec"]
    assert all(r["generated_by"] == "fallback" for r in out["recaps"])
    assert "New members paid: 2" in out["recaps"][0]["body"]


def test_the_recap_compares_against_weeks_already_in_the_warehouse(wired, capsys):
    for week, value in zip(
        [date(2026, 7, 20), date(2026, 7, 27), date(2026, 8, 3), date(2026, 8, 10)],
        [6.0, 6.0, 6.0, 6.0],
    ):
        wired.write_snapshot(MetricResult("new_members_paid", week, value))

    _, out = run(["--week", "2026-08-17", "--no-llm", "--json"], capsys)
    assert "New members paid: 2, down from a 4 week average of 6." in out["recaps"][0]["body"]


def test_a_5x_move_holds_the_send(wired, capsys):
    wired.write_snapshot(MetricResult("new_members_paid", date(2026, 8, 10), 20.0))
    code, out = run(["--week", "2026-08-17", "--no-llm", "--send", "--json"], capsys)

    assert code == 1
    assert any(f["code"] == "move_over_5x" for f in out["findings"])
    assert out["deliveries"] == []
    # the snapshot is still written, we hold the message not the history
    assert out["snapshots_written"] == 3


def test_acknowledging_the_anomaly_lets_it_through(wired, capsys):
    wired.write_snapshot(MetricResult("new_members_paid", date(2026, 8, 10), 20.0))
    code, out = run(
        ["--week", "2026-08-17", "--no-llm", "--send", "--acknowledge-anomalies", "--json"],
        capsys,
    )

    assert code == 0
    assert out["deliveries"] != []


def test_a_dead_source_still_sends_a_recap_that_says_unavailable(monkeypatch, wired, capsys):
    wire_sources(
        monkeypatch,
        stripe=FakeStripe([], fail="401 invalid key"),
        ghl=FakeGhl(events={"cal_disc": []}),
    )
    code, out = run(["--week", "2026-08-17", "--no-llm", "--send", "--json"], capsys)

    assert code == 0
    assert any(f["code"] == "source_failed" for f in out["findings"])
    assert "unavailable this week, stripe: 401 invalid key" in out["recaps"][0]["body"]
    # the failure is in the warehouse too, not just in the message
    assert wired.history("new_members_paid", [WEEK.start])[0].error.startswith("stripe:")


def test_require_all_green_holds_the_send_on_a_dead_source(monkeypatch, wired, capsys):
    wire_sources(
        monkeypatch,
        stripe=FakeStripe([], fail="401 invalid key"),
        ghl=FakeGhl(events={"cal_disc": []}),
    )
    code, _ = run(
        ["--week", "2026-08-17", "--no-llm", "--require-all-green", "--json"], capsys
    )
    assert code == 1


def test_a_dry_run_works_with_no_warehouse_configured(monkeypatch, capsys):
    """A laptop with source keys but no SUPABASE_DB_URL still previews the week."""
    wire_sources(monkeypatch)
    monkeypatch.setattr(
        run_weekly, "Warehouse", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no dsn"))
    )
    code, out = run(["--week", "2026-08-17", "--no-llm", "--json"], capsys)

    assert code == 0
    assert "no dsn" in out["warehouse_error"]
    assert {r["metric_id"] for r in out["results"]} == {
        "new_members_paid", "new_member_cash_collected", "discovery_calls_showed",
    }


def test_a_send_with_no_warehouse_is_refused(monkeypatch, capsys):
    wire_sources(monkeypatch)
    monkeypatch.setattr(
        run_weekly, "Warehouse", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no dsn"))
    )
    assert run_weekly.main(["--week", "2026-08-17", "--no-llm", "--send", "--json"]) == 2


def test_an_unknown_department_is_refused():
    assert run_weekly.main(["--departments", "retention", "--json"]) == 2
