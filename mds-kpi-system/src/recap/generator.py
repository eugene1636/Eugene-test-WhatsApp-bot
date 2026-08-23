"""Recap generation via Claude API.

Input: this week's MetricResults + trailing 8 weeks of snapshots for context.
Output: per-department recap (5-8 sentences) + exec recap (all 13, biggest
mover flagged).

Voice rules (non-negotiable, see CLAUDE.md):
- like a text from a sharp friend, casual, direct, short sentences
- no em-dashes, no corporate phrasing
- lead with what changed, flag what needs attention
- exactly one suggested action max per department
- if a source failed, say the metric is unavailable and why; never show
  stale or zero values as if real
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .. import config
from ..models import MetricResult, Snapshot, SourceRun
from ..registry import Registry
from ..weeks import Week, trailing

HISTORY_WEEKS = 8
MAX_TOKENS = 4000

SYSTEM_PROMPT = """You write the Monday KPI recap for Million Dollar Sellers, a \
community of about 700 seven and eight figure ecommerce founders. You are writing \
to one specific teammate who owns these numbers.

Voice:
- Write like a text from a sharp friend. Casual, direct, short sentences.
- Never use an em-dash or an en-dash. Use a comma, a full stop, or start a new sentence.
- No corporate phrasing. Never write "per our analysis", "key takeaway", "circle back",
  "leverage", "synergy".
- Lead with what actually changed this week. Then flag what needs attention.
- End with at most ONE concrete suggested action. If nothing needs doing, say so and stop.

Hard rules about the numbers:
- Only use numbers present in the facts you are given. Never estimate, never fill a gap.
- If a metric is marked unavailable, say it is unavailable this week and name the source
  that failed. Never show a zero or a prior week's number as if it were this week's.
- Percentages and dollar amounts must match the facts exactly.

Length: 5 to 8 sentences. Plain text, no headings, no bullet lists, no markdown."""

EXEC_EXTRA = """This is the exec recap for Eugene and Ian. Cover the whole board in \
one screen. Call out the single biggest mover by name and say whether it is good or bad. \
Still 5 to 8 sentences, still one suggested action at most."""


@dataclass
class Recap:
    audience: str          # department name, or "exec"
    title: str
    body: str
    generated_by: str = "claude"
    facts: dict = field(default_factory=dict)

    def as_text(self) -> str:
        return f"{self.title}\n\n{self.body}"


def scrub(text: str) -> str:
    """Belt and braces on the no-dash rule, plus tidy whitespace."""
    cleaned = (
        text.replace("—", ", ")
        .replace("–", ", ")
        .replace(" ,", ",")
        .replace(",,", ",")
    )
    lines = [" ".join(line.split()) for line in cleaned.strip().splitlines()]
    return "\n".join(line for line in lines).strip()


def build_facts(
    week: Week,
    results: list[MetricResult],
    history: dict[str, list[Snapshot]],
    source_runs: list[SourceRun],
    registry: Registry,
    *,
    department: str | None = None,
) -> dict:
    """The only numbers the model is allowed to see, and therefore to print."""
    selected = [
        r
        for r in results
        if department is None or registry[r.metric_id].department == department
    ]
    metrics = []
    for result in selected:
        spec = registry[result.metric_id]
        past = history.get(result.metric_id, [])
        metrics.append(
            {
                "metric_id": spec.id,
                "name": spec.name,
                "department": spec.department,
                "owner": spec.owner,
                "type": spec.type,
                "definition": spec.definition,
                "value": result.value,
                "available": result.available,
                "unavailable_reason": result.error,
                "sub_metrics": result.sub_metrics,
                "prior_weeks": [
                    {"week_start": s.week_start.isoformat(), "value": s.value}
                    for s in past
                    if s.available
                ],
                "prior_4_week_avg": _average(
                    [s.value for s in past[-4:] if s.available]
                ),
            }
        )

    failures = []
    seen: set[tuple[str, str | None]] = set()
    for run in source_runs:
        if run.ok or (run.source, run.error) in seen:
            continue
        seen.add((run.source, run.error))
        failures.append({"source": run.source, "error": run.error})
    return {
        "week_start": week.start.isoformat(),
        "week_end": week.end.isoformat(),
        "audience": department or "exec",
        "owner": registry.owner_of(department) if department else "Eugene and Ian",
        "metrics": metrics,
        "failed_sources": failures,
        "history_weeks_available": HISTORY_WEEKS,
    }


def history_weeks(week: Week) -> list[Week]:
    return trailing(week, HISTORY_WEEKS)


def generate(
    facts: dict,
    *,
    client: Any = None,
    model: str | None = None,
    use_llm: bool = True,
) -> Recap:
    """Write one recap. Falls back to a plain formatter if Claude is unreachable."""
    audience = facts["audience"]
    title = _title(facts)
    if not use_llm:
        return Recap(audience, title, fallback_body(facts), generated_by="fallback", facts=facts)

    try:
        body = _ask_claude(facts, client=client, model=model)
    except Exception as exc:  # the recap still has to land Monday morning
        body = fallback_body(facts)
        note = f"(Claude unavailable, auto-formatted instead: {type(exc).__name__})"
        return Recap(audience, title, f"{body}\n\n{note}", generated_by="fallback", facts=facts)
    return Recap(audience, title, body, generated_by="claude", facts=facts)


def _ask_claude(facts: dict, *, client: Any = None, model: str | None = None) -> str:
    if client is None:
        import anthropic  # noqa: PLC0415

        client = anthropic.Anthropic(api_key=config.require("ANTHROPIC_API_KEY"))

    system = SYSTEM_PROMPT
    if facts["audience"] == "exec":
        system = f"{SYSTEM_PROMPT}\n\n{EXEC_EXTRA}"

    response = client.messages.create(
        model=model or config.RECAP_MODEL,
        max_tokens=MAX_TOKENS,
        system=system,
        thinking={"type": "adaptive"},
        output_config={"effort": "medium"},
        messages=[
            {
                "role": "user",
                "content": (
                    f"Week of {facts['week_start']} to {facts['week_end']}. "
                    f"Recap for {facts['owner']} ({facts['audience']}).\n\n"
                    "Facts, JSON:\n"
                    f"{json.dumps(facts, indent=2, default=str)}\n\n"
                    "Write the recap now."
                ),
            }
        ],
    )
    text = "".join(
        block.text for block in response.content if getattr(block, "type", "") == "text"
    ).strip()
    if not text:
        raise RuntimeError("Claude returned no text block")
    return scrub(text)


def fallback_body(facts: dict) -> str:
    """Deterministic recap used when Claude is unavailable. Same rules, no flair."""
    lines: list[str] = []
    for metric in facts["metrics"]:
        if not metric["available"]:
            lines.append(
                _sentence(
                    f"{metric['name']}: unavailable this week, "
                    f"{metric['unavailable_reason']}"
                )
            )
            continue
        prior = metric["prior_4_week_avg"]
        value = _format_value(metric["metric_id"], metric["value"])
        if prior is None:
            lines.append(f"{metric['name']}: {value}. No prior weeks to compare yet.")
        elif metric["value"] == prior:
            lines.append(
                f"{metric['name']}: {value}, flat against a 4 week average of "
                f"{_format_value(metric['metric_id'], prior)}."
            )
        else:
            direction = "up from" if metric["value"] > prior else "down from"
            lines.append(
                f"{metric['name']}: {value}, {direction} a 4 week average of "
                f"{_format_value(metric['metric_id'], prior)}."
            )
    for failure in facts["failed_sources"]:
        lines.append(_sentence(f"Source {failure['source']} failed: {failure['error']}"))
    if not lines:
        lines.append("No metrics computed for this week.")
    return scrub("\n".join(lines))


def _sentence(text: str) -> str:
    stripped = text.rstrip()
    return stripped if stripped.endswith((".", "!", "?")) else f"{stripped}."


def _title(facts: dict) -> str:
    who = "Exec" if facts["audience"] == "exec" else facts["audience"].title()
    return f"{who} KPI recap, week of {facts['week_start']}"


def _format_value(metric_id: str, value: float | None) -> str:
    if value is None:
        return "unavailable"
    if "cash" in metric_id or "dollars" in metric_id:
        return f"${value:,.0f}"
    if float(value).is_integer():
        return f"{int(value)}"
    return f"{value:,.2f}"


def _average(values: list[float]) -> float | None:
    numbers = [v for v in values if v is not None]
    if not numbers:
        return None
    return round(sum(numbers) / len(numbers), 2)
