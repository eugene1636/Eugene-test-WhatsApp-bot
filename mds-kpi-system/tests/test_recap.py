from datetime import date, datetime, timezone

from src import registry
from src.models import MetricResult, Snapshot, SourceRun
from src.recap import generator
from src.weeks import week_of

WEEK = week_of(date(2026, 8, 17))
REG = registry.load()


class FakeClaude:
    """Captures the request and returns a canned message."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.request: dict = {}
        self.messages = self

    def create(self, **kwargs):
        self.request = kwargs

        class Block:
            type = "text"

        block = Block()
        block.text = self.text
        return type("Response", (), {"content": [block]})()


def results():
    return [
        MetricResult(
            "new_members_paid",
            WEEK.start,
            4.0,
            sub_metrics={"by_lead_source": {"event": 2, "referral": 2}},
        ),
        MetricResult("new_member_cash_collected", WEEK.start, 12480.0),
        MetricResult.unavailable("discovery_calls_showed", WEEK.start, "gohighlevel 503"),
    ]


def history():
    return {
        "new_members_paid": [
            Snapshot("new_members_paid", date(2026, 8, 3), 3.0),
            Snapshot("new_members_paid", date(2026, 8, 10), 5.0),
        ],
        "new_member_cash_collected": [
            Snapshot("new_member_cash_collected", date(2026, 8, 10), 9000.0)
        ],
    }


def failed_runs():
    now = datetime.now(timezone.utc)
    return [SourceRun("gohighlevel", WEEK.start, "failed", now, now, error="503 upstream")]


def facts(department="growth"):
    return generator.build_facts(
        WEEK, results(), history(), failed_runs(), REG, department=department
    )


def test_facts_carry_only_the_departments_metrics_and_their_history():
    payload = facts()
    assert [m["metric_id"] for m in payload["metrics"]] == [
        "new_members_paid",
        "new_member_cash_collected",
        "discovery_calls_showed",
    ]
    assert payload["owner"] == "Sashani"
    assert payload["metrics"][0]["prior_4_week_avg"] == 4.0
    assert payload["failed_sources"] == [
        {"source": "gohighlevel", "error": "503 upstream"}
    ]


def test_an_unavailable_metric_carries_its_reason_and_no_value():
    metric = facts()["metrics"][2]
    assert metric["available"] is False
    assert metric["value"] is None
    assert metric["unavailable_reason"] == "gohighlevel 503"


def test_scrub_removes_every_dash_the_voice_rules_ban():
    assert "—" not in generator.scrub("Joins are up — nice week.")
    assert "–" not in generator.scrub("Cash is flat – watch it.")
    assert generator.scrub("Joins are up — nice week.") == "Joins are up, nice week."


def test_generated_recaps_are_scrubbed_before_delivery():
    client = FakeClaude("Joins hit 4 — best week since July.")
    recap = generator.generate(facts(), client=client)

    assert "—" not in recap.body
    assert recap.generated_by == "claude"
    assert recap.title == "Growth KPI recap, week of 2026-08-17"


def test_the_model_request_pins_the_voice_rules_and_the_facts():
    client = FakeClaude("ok")
    generator.generate(facts(), client=client)

    system = client.request["system"]
    assert "em-dash" in system
    assert "ONE concrete suggested action" in system
    assert "gohighlevel 503" in client.request["messages"][0]["content"]
    assert client.request["thinking"] == {"type": "adaptive"}


def test_the_exec_recap_gets_the_whole_board_and_the_exec_brief():
    client = FakeClaude("ok")
    payload = generator.build_facts(WEEK, results(), history(), failed_runs(), REG)
    generator.generate(payload, client=client)

    assert payload["audience"] == "exec"
    assert payload["owner"] == "Eugene and Ian"
    assert "biggest mover" in client.request["system"]


def test_a_claude_outage_still_produces_a_recap_and_says_so():
    class Broken:
        messages = property(lambda self: self)

        def create(self, **kwargs):
            raise RuntimeError("connection reset")

    recap = generator.generate(facts(), client=Broken())
    assert recap.generated_by == "fallback"
    assert "Claude unavailable" in recap.body
    assert "unavailable this week, gohighlevel 503" in recap.body


def test_the_fallback_never_prints_a_stale_or_zero_number_for_a_dead_source():
    body = generator.fallback_body(facts())
    assert "Discovery calls showed: unavailable this week, gohighlevel 503." in body
    assert "New members paid: 4, flat against a 4 week average of 4." in body
    assert "$12,480" in body
