"""Pre-send checks (docs/architecture.md, Scheduling).

Two different rules, deliberately at two different severities:

- A failed source pull is a WARN. The fail-loud rule in CLAUDE.md says the recap
  must state "metric unavailable this week, source X failed", so the recap still
  goes out and carries the bad news. Pass require_all_green=True to promote
  these to blocking if you would rather hold the send.
- A metric moving more than 5x week over week is a BLOCK. That is usually a
  source change or a bug, and blasting it to the team unreviewed is worse than
  being late. Acknowledge it to release the send.
"""
from __future__ import annotations

from dataclasses import dataclass

from .models import MetricResult, Snapshot, SourceRun

MOVE_FACTOR = 5.0

BLOCK = "block"
WARN = "warn"


@dataclass(frozen=True)
class Finding:
    level: str
    code: str
    metric_id: str | None
    message: str


def validate(
    results: list[MetricResult],
    history: dict[str, list[Snapshot]],
    source_runs: list[SourceRun],
    *,
    require_all_green: bool = False,
    acknowledge_anomalies: bool = False,
) -> list[Finding]:
    findings: list[Finding] = []

    for run in source_runs:
        if run.ok:
            continue
        findings.append(
            Finding(
                level=BLOCK if require_all_green else WARN,
                code="source_failed",
                metric_id=None,
                message=f"{run.source} pull failed: {run.error}",
            )
        )

    for result in results:
        if not result.available:
            findings.append(
                Finding(
                    level=WARN,
                    code="metric_unavailable",
                    metric_id=result.metric_id,
                    message=f"{result.metric_id} unavailable: {result.error}",
                )
            )
            continue

        prior = _previous_value(history.get(result.metric_id, []), result)
        if prior is None or prior == 0:
            continue
        ratio = abs(result.value) / abs(prior)
        if ratio > MOVE_FACTOR or ratio < 1 / MOVE_FACTOR:
            findings.append(
                Finding(
                    level=WARN if acknowledge_anomalies else BLOCK,
                    code="move_over_5x",
                    metric_id=result.metric_id,
                    message=(
                        f"{result.metric_id} moved {prior:g} -> {result.value:g} "
                        f"({ratio:.1f}x week over week). Check the source before sending."
                    ),
                )
            )

    return findings


def blocked(findings: list[Finding]) -> bool:
    return any(f.level == BLOCK for f in findings)


def _previous_value(snapshots: list[Snapshot], result: MetricResult) -> float | None:
    earlier = [s for s in snapshots if s.week_start < result.week_start and s.available]
    if not earlier:
        return None
    return earlier[-1].value
