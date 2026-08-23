"""Print a Monday recap from fixture numbers. No source credentials needed.

The point of this script is the Phase 1 milestone conversation: it shows what
lands in Slack on Monday, and it exercises the real Claude call so the voice can
be tuned before Stripe and GoHighLevel are wired up.

    python scripts/demo_recap.py --no-llm     # deterministic, zero API calls
    python scripts/demo_recap.py              # real Claude call, needs ANTHROPIC_API_KEY
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import registry  # noqa: E402
from src.models import MetricResult, Snapshot, SourceRun  # noqa: E402
from src.recap import generator  # noqa: E402
from src.weeks import week_of  # noqa: E402

WEEK = week_of(date(2026, 8, 17))


def fixture_results() -> list[MetricResult]:
    return [
        MetricResult(
            metric_id="new_members_paid",
            week_start=WEEK.start,
            value=6.0,
            sub_metrics={
                "by_lead_source": {
                    "event": 3, "referral": 2, "website": 1,
                    "facebook": 0, "second_seat": 0, "unknown": 0,
                },
                "with_vs_without_discovery_call": {"with": 5, "without": 1},
            },
        ),
        MetricResult(
            metric_id="new_member_cash_collected",
            week_start=WEEK.start,
            value=18740.0,
            sub_metrics={
                "avg_first_payment": 3123.33,
                "plan_mix": {
                    "annual": {"count": 4, "dollars": 15760.0},
                    "monthly": {"count": 2, "dollars": 2980.0},
                },
                "new_member_count": 6,
            },
        ),
        MetricResult.unavailable(
            "discovery_calls_showed", WEEK.start, "gohighlevel: HTTP 503 from /calendars/events"
        ),
    ]


def fixture_history() -> dict[str, list[Snapshot]]:
    weeks = [w.start for w in generator.history_weeks(WEEK)]
    joins = [4.0, 5.0, 7.0, 4.0, 6.0, 5.0, 9.0, 4.0]
    cash = [11200.0, 14300.0, 21050.0, 9800.0, 16400.0, 12900.0, 26100.0, 10450.0]
    return {
        "new_members_paid": [
            Snapshot("new_members_paid", w, v) for w, v in zip(weeks, joins)
        ],
        "new_member_cash_collected": [
            Snapshot("new_member_cash_collected", w, v) for w, v in zip(weeks, cash)
        ],
        "discovery_calls_showed": [
            Snapshot("discovery_calls_showed", w, v)
            for w, v in zip(weeks, [8.0, 11.0, 9.0, 6.0, 10.0, 7.0, 12.0, 9.0])
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-llm", action="store_true", help="skip the Claude call")
    args = parser.parse_args(argv)

    now = datetime.now(timezone.utc)
    runs = [
        SourceRun("stripe", WEEK.start, "success", now, now, records_fetched=6),
        SourceRun(
            "gohighlevel", WEEK.start, "failed", now, now,
            error="HTTP 503 from /calendars/events",
        ),
    ]
    reg = registry.default()
    results = fixture_results()
    history = fixture_history()

    print(f"Fixture data, week of {WEEK}. This is not real MDS data.\n")
    for department in ("growth", None):
        facts = generator.build_facts(
            WEEK, results, history, runs, reg, department=department
        )
        recap = generator.generate(facts, use_llm=not args.no_llm)
        print("=" * 72)
        print(f"{recap.title}   [{recap.generated_by}]\n")
        print(recap.body)
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
