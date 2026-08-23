"""Run context: the week, the source clients, and the pull log.

Metric modules never construct source clients themselves. They ask the context,
which builds them lazily (so a Phase 1 run needs only Stripe and GoHighLevel
credentials) and records a source_runs row for every pull, success or failure.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from .errors import SourceError
from .models import SourceRun
from .weeks import Week


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class RunContext:
    week: Week
    clients: dict[str, Any] = field(default_factory=dict)
    runs: list[SourceRun] = field(default_factory=list)
    _memo: dict[str, Any] = field(default_factory=dict, repr=False)

    def client(self, source: str) -> Any:
        """Lazily build (and cache) the client for a source system."""
        if source not in self.clients:
            self.clients[source] = _build_client(source)
        return self.clients[source]

    def pull(
        self,
        source: str,
        fetch: Callable[[Any], Any],
        *,
        note: str | None = None,
        week: Week | None = None,
    ) -> Any:
        """Run one source pull, log it, and let SourceError propagate.

        Callers catch SourceError and turn it into an unavailable MetricResult.
        Nothing here converts a failure into a zero.
        """
        started = _now()
        try:
            payload = fetch(self.client(source))
        except SourceError as exc:
            self.runs.append(
                SourceRun(
                    source=source,
                    week_start=(week or self.week).start,
                    status="failed",
                    started_at=started,
                    finished_at=_now(),
                    error=exc.message,
                    note=note,
                )
            )
            raise
        except Exception as exc:  # unexpected: still fail loud, never a zero
            self.runs.append(
                SourceRun(
                    source=source,
                    week_start=(week or self.week).start,
                    status="failed",
                    started_at=started,
                    finished_at=_now(),
                    error=f"{type(exc).__name__}: {exc}",
                    note=note,
                )
            )
            raise SourceError(source, f"{type(exc).__name__}: {exc}") from exc

        self.runs.append(
            SourceRun(
                source=source,
                week_start=(week or self.week).start,
                status="success",
                started_at=started,
                finished_at=_now(),
                records_fetched=_count(payload),
                note=note,
            )
        )
        return payload

    def pull_once(
        self,
        key: str,
        source: str,
        fetch: Callable[[Any], Any],
        *,
        note: str | None = None,
        week: Week | None = None,
    ) -> Any:
        """pull(), but the same key is only fetched once per run.

        Several metrics share the trailing 4-week windows. Without this they
        would hit the same endpoints twice and write duplicate source_runs rows.
        A cached failure re-raises rather than triggering a retry.
        """
        if key in self._memo:
            cached = self._memo[key]
            if isinstance(cached, SourceError):
                raise cached
            return cached
        try:
            payload = self.pull(source, fetch, note=note, week=week)
        except SourceError as exc:
            self._memo[key] = exc
            raise
        self._memo[key] = payload
        return payload

    @property
    def failed_sources(self) -> list[str]:
        return sorted({run.source for run in self.runs if not run.ok})


def _count(payload: Any) -> int:
    if isinstance(payload, dict):
        if "record_ids" in payload:
            return len(payload["record_ids"])
        return sum(len(v) for v in payload.values() if isinstance(v, list))
    if isinstance(payload, list):
        return len(payload)
    return 0


def _build_client(source: str) -> Any:
    if source == "stripe":
        from .connectors.stripe_conn import StripeSource

        return StripeSource()
    if source == "gohighlevel":
        from .connectors.gohighlevel import GoHighLevelSource

        return GoHighLevelSource()
    raise SourceError(source, "no client wired up for this source yet")
