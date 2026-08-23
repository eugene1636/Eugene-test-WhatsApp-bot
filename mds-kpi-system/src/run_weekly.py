"""Entry point. n8n triggers this Mondays 6am ET.

Flow:
1. Resolve week window (last full Mon-Sun, US Eastern)
2. Run every department compute(), collect MetricResults
3. Write snapshots + source_runs to Airtable warehouse
4. Run validation checks (all pulls green, no metric moved >5x WoW unflagged)
5. Generate and send recaps (src/recap)

Phase 1 (docs/roadmap.md) runs the growth department only. Add a department to
DEPARTMENTS as its metrics module lands.

    python -m src.run_weekly                      # last full week, dry run
    python -m src.run_weekly --week 2026-08-10    # a specific week
    python -m src.run_weekly --send               # write to Airtable and deliver
    python -m src.run_weekly --no-llm             # skip Claude, plain recap
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from typing import Callable

from . import registry as registry_module
from .connectors.airtable_wh import Warehouse
from .context import RunContext
from .errors import SourceError
from .metrics import growth
from .models import MetricResult, Snapshot
from .recap import generator, sender
from .validation import BLOCK, Finding, blocked, validate
from .weeks import Week, last_full_week, parse_week

# Departments with a live compute(). Phase 1 = growth only.
DEPARTMENTS: dict[str, Callable[[Week, RunContext], list[MetricResult]]] = {
    "growth": growth.compute,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MDS weekly KPI run")
    parser.add_argument("--week", help="any date in the target week (default: last full week)")
    parser.add_argument(
        "--send",
        action="store_true",
        help="write snapshots to Airtable and deliver recaps (default is a dry run)",
    )
    parser.add_argument(
        "--departments",
        default=",".join(DEPARTMENTS),
        help=f"comma separated, from: {', '.join(DEPARTMENTS)}",
    )
    parser.add_argument("--no-llm", action="store_true", help="skip the Claude call")
    parser.add_argument(
        "--require-all-green",
        action="store_true",
        help="treat any failed source pull as blocking (architecture.md scheduling rule)",
    )
    parser.add_argument(
        "--acknowledge-anomalies",
        action="store_true",
        help="release a send that a >5x week over week move is blocking",
    )
    parser.add_argument("--json", action="store_true", help="machine readable output")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    dry_run = not args.send

    week = parse_week(args.week) if args.week else last_full_week()
    registry = registry_module.default()
    departments = [d.strip() for d in args.departments.split(",") if d.strip()]
    unknown = [d for d in departments if d not in DEPARTMENTS]
    if unknown:
        print(f"no compute() wired up for: {', '.join(unknown)}", file=sys.stderr)
        return 2

    # 1 + 2: pull and compute
    ctx = RunContext(week=week)
    results: list[MetricResult] = []
    for department in departments:
        results.extend(DEPARTMENTS[department](week, ctx))

    for result in results:
        if result.metric_id not in registry:
            print(
                f"refusing to write {result.metric_id}, not in config/kpis.yaml",
                file=sys.stderr,
            )
            return 2

    # 3: warehouse. History is needed either way for the recap comparisons.
    warehouse, warehouse_error = _open_warehouse()
    if warehouse is None and not dry_run:
        print(
            f"cannot reach the warehouse, refusing to send: {warehouse_error}",
            file=sys.stderr,
        )
        return 2
    history = _read_history(warehouse, results, week)
    written = 0
    if warehouse is not None and not dry_run:
        for result in results:
            warehouse.write_snapshot(result)
            written += 1
        for run in ctx.runs:
            warehouse.write_source_run(run)

    # 4: validate
    findings = validate(
        results,
        history,
        ctx.runs,
        require_all_green=args.require_all_green,
        acknowledge_anomalies=args.acknowledge_anomalies,
    )

    # 5: recaps
    recaps = []
    for department in departments:
        facts = generator.build_facts(
            week, results, history, ctx.runs, registry, department=department
        )
        recaps.append(generator.generate(facts, use_llm=not args.no_llm))
    exec_facts = generator.build_facts(week, results, history, ctx.runs, registry)
    recaps.append(generator.generate(exec_facts, use_llm=not args.no_llm))

    held = blocked(findings)
    deliveries = []
    if held:
        print("HOLDING SEND, blocking findings below.", file=sys.stderr)
    else:
        deliveries = sender.deliver(recaps, dry_run=dry_run)

    _report(
        args, week, results, ctx, findings, recaps, deliveries, written, warehouse_error
    )
    return 1 if held else 0


def _open_warehouse() -> tuple[Warehouse | None, str | None]:
    """A dry run tolerates a missing warehouse. A send does not."""
    try:
        return Warehouse(), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _read_history(
    warehouse: Warehouse | None, results: list[MetricResult], week: Week
) -> dict[str, list[Snapshot]]:
    if warehouse is None:
        return {}
    weeks = [w.start for w in generator.history_weeks(week)]
    history: dict[str, list[Snapshot]] = {}
    for result in results:
        try:
            history[result.metric_id] = warehouse.history(result.metric_id, weeks)
        except SourceError as exc:
            print(f"history read failed for {result.metric_id}: {exc}", file=sys.stderr)
            history[result.metric_id] = []
    return history


def _report(
    args,
    week: Week,
    results: list[MetricResult],
    ctx: RunContext,
    findings: list[Finding],
    recaps: list[generator.Recap],
    deliveries: list[sender.Delivery],
    written: int,
    warehouse_error: str | None,
) -> None:
    if args.json:
        print(
            json.dumps(
                {
                    "week_start": week.start.isoformat(),
                    "results": [_result_json(r) for r in results],
                    "source_runs": [asdict(run) for run in ctx.runs],
                    "findings": [asdict(f) for f in findings],
                    "recaps": [
                        {"audience": r.audience, "title": r.title, "body": r.body,
                         "generated_by": r.generated_by}
                        for r in recaps
                    ],
                    "deliveries": [asdict(d) for d in deliveries],
                    "snapshots_written": written,
                    "warehouse_error": warehouse_error,
                },
                indent=2,
                default=str,
            )
        )
        return

    mode = "SEND" if args.send else "DRY RUN"
    print(f"MDS KPI weekly run, week of {week}, {mode}")
    if warehouse_error:
        print(f"  warehouse not connected ({warehouse_error}), history unavailable")
    print()
    for result in results:
        if result.available:
            print(f"  {result.metric_id}: {result.value:g}")
        else:
            print(f"  {result.metric_id}: UNAVAILABLE, {result.error}")
    print()
    for run in ctx.runs:
        flag = "ok " if run.ok else "FAIL"
        print(f"  [{flag}] {run.source} ({run.note}): {run.records_fetched} records")
    if findings:
        print()
        for finding in findings:
            tag = "BLOCK" if finding.level == BLOCK else "warn "
            print(f"  [{tag}] {finding.message}")
    print()
    print(f"  snapshots written: {written}")
    for delivery in deliveries:
        print(f"  {delivery.audience} -> {delivery.channel}: {delivery.status} {delivery.detail}")
    print()
    for recap in recaps:
        print("=" * 72)
        print(f"{recap.title}   [{recap.generated_by}]")
        print()
        print(recap.body)
        print()


def _result_json(result: MetricResult) -> dict:
    payload = asdict(result)
    payload["week_start"] = result.week_start.isoformat()
    payload["available"] = result.available
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
