"""Shared types. Keep it boring."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass
class MetricResult:
    metric_id: str          # must exist in config/kpis.yaml
    week_start: date        # Monday, US Eastern
    value: float | None     # None = unavailable this week (fail loud in recap)
    sub_metrics: dict = field(default_factory=dict)
    source_refs: dict = field(default_factory=dict)  # record ids used, for drill-down
    error: str | None = None

    @property
    def available(self) -> bool:
        return self.value is not None and self.error is None

    @classmethod
    def unavailable(cls, metric_id: str, week_start: date, error: str) -> "MetricResult":
        return cls(metric_id=metric_id, week_start=week_start, value=None, error=error)


@dataclass
class SourceRun:
    """One pull from one source system, for the fail-loud rule."""

    source: str
    week_start: date
    status: str             # success | failed
    started_at: datetime
    finished_at: datetime
    records_fetched: int = 0
    error: str | None = None
    note: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "success"

    @property
    def duration_seconds(self) -> float:
        return (self.finished_at - self.started_at).total_seconds()


@dataclass
class Snapshot:
    """A row read back out of the warehouse."""

    metric_id: str
    week_start: date
    value: float | None
    revision: int = 0
    sub_metrics: dict = field(default_factory=dict)
    error: str | None = None

    @property
    def available(self) -> bool:
        return self.value is not None and self.error is None
