"""airtable_wh connector.

Contract: expose fetch_* functions taking (week_start: date, week_end: date)
and returning plain dicts. No pandas here. Log every run to source_runs.
See CLAUDE.md conventions and config/kpis.yaml for which metrics need what.

This module is the warehouse side: it writes snapshots and source_runs, seeds
the metrics registry from config/kpis.yaml, and reads history back for the
recap. Snapshots are append-only. A correction is a new row with revision + 1,
never an edit of the row that went out last Monday.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any, Protocol

from .. import config
from ..errors import SourceError
from ..models import MetricResult, Snapshot, SourceRun
from ..registry import KpiSpec

METRICS_TABLE = "metrics"
SNAPSHOTS_TABLE = "snapshots"
SOURCE_RUNS_TABLE = "source_runs"


class TableLike(Protocol):  # what we need from pyairtable's Table
    def all(self, **kwargs: Any) -> list[dict]: ...
    def create(self, fields: dict) -> dict: ...
    def update(self, record_id: str, fields: dict) -> dict: ...


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


class Warehouse:
    """Read/write access to the KPI Warehouse base."""

    def __init__(
        self,
        api_key: str | None = None,
        base_id: str | None = None,
        tables: dict[str, TableLike] | None = None,
    ) -> None:
        if tables is not None:
            self._tables = dict(tables)
            return
        from pyairtable import Api  # noqa: PLC0415

        api = Api(api_key or config.require("AIRTABLE_API_KEY"))
        base = base_id or config.require("AIRTABLE_WAREHOUSE_BASE_ID")
        self._tables = {
            name: api.table(base, name)
            for name in (METRICS_TABLE, SNAPSHOTS_TABLE, SOURCE_RUNS_TABLE)
        }

    def table(self, name: str) -> TableLike:
        return self._tables[name]

    # ---------------------------------------------------------------- metrics

    def seed_metrics(self, specs: list[KpiSpec]) -> dict[str, str]:
        """Create or refresh one registry row per KPI. Idempotent."""
        existing = {
            rec["fields"].get("metric_id"): rec
            for rec in self._all(METRICS_TABLE)
            if rec["fields"].get("metric_id")
        }
        written: dict[str, str] = {}
        for spec in specs:
            fields = {
                "metric_id": spec.id,
                "name": spec.name,
                "department": spec.department,
                "owner": spec.owner,
                "type": spec.type,
                "sources": ", ".join(spec.sources),
                "definition": spec.definition,
                "sub_metric_specs": "\n".join(f"- {s}" for s in spec.sub_metric_specs),
            }
            record = existing.get(spec.id)
            if record is None:
                created = self._create(METRICS_TABLE, fields)
                written[spec.id] = created["id"]
            else:
                self._update(METRICS_TABLE, record["id"], fields)
                written[spec.id] = record["id"]
        return written

    # -------------------------------------------------------------- snapshots

    def next_revision(self, metric_id: str, week_start: date) -> int:
        return len(self._snapshot_rows(metric_id, week_start))

    def write_snapshot(self, result: MetricResult, computed_at: datetime | None = None) -> dict:
        """Append one snapshot row. Never updates an existing row."""
        revision = self.next_revision(result.metric_id, result.week_start)
        stamp = (computed_at or datetime.now(timezone.utc)).isoformat()
        fields = {
            "key": f"{result.metric_id}|{result.week_start.isoformat()}|r{revision}",
            "metric_id": result.metric_id,
            "week_start": result.week_start.isoformat(),
            "value": result.value,
            "available": result.available,
            "revision": revision,
            "sub_metrics": _json(result.sub_metrics),
            "source_refs": _json(result.source_refs),
            "error": result.error or "",
            "computed_at": stamp,
        }
        return self._create(SNAPSHOTS_TABLE, fields)

    def history(self, metric_id: str, weeks: list[date]) -> list[Snapshot]:
        """Latest revision per requested week, oldest first, missing weeks skipped."""
        wanted = {w.isoformat() for w in weeks}
        rows = self._all(
            SNAPSHOTS_TABLE,
            formula=f"{{metric_id}}='{_escape(metric_id)}'",
        )
        best: dict[str, dict] = {}
        for row in rows:
            fields = row.get("fields", {})
            week = fields.get("week_start")
            if week not in wanted:
                continue
            revision = int(fields.get("revision") or 0)
            if week not in best or revision > int(best[week]["fields"].get("revision") or 0):
                best[week] = row
        snapshots = []
        for week in sorted(best):
            fields = best[week]["fields"]
            snapshots.append(
                Snapshot(
                    metric_id=metric_id,
                    week_start=date.fromisoformat(week),
                    value=fields.get("value"),
                    revision=int(fields.get("revision") or 0),
                    sub_metrics=_loads(fields.get("sub_metrics")),
                    error=fields.get("error") or None,
                )
            )
        return snapshots

    # ------------------------------------------------------------ source_runs

    def write_source_run(self, run: SourceRun) -> dict:
        fields = {
            "run_key": (
                f"{run.source}|{run.week_start.isoformat()}|"
                f"{run.started_at.isoformat()}"
            ),
            "source": run.source,
            "week_start": run.week_start.isoformat(),
            "status": run.status,
            "started_at": run.started_at.isoformat(),
            "finished_at": run.finished_at.isoformat(),
            "records_fetched": run.records_fetched,
            "error": run.error or "",
            "note": run.note or "",
        }
        return self._create(SOURCE_RUNS_TABLE, fields)

    # ------------------------------------------------------------- primitives

    def _snapshot_rows(self, metric_id: str, week_start: date) -> list[dict]:
        formula = (
            f"AND({{metric_id}}='{_escape(metric_id)}', "
            f"{{week_start}}='{week_start.isoformat()}')"
        )
        return self._all(SNAPSHOTS_TABLE, formula=formula)

    def _all(self, table: str, **kwargs: Any) -> list[dict]:
        try:
            return self._tables[table].all(**kwargs)
        except Exception as exc:
            raise SourceError("airtable", f"reading {table} failed: {exc}") from exc

    def _create(self, table: str, fields: dict) -> dict:
        try:
            return self._tables[table].create(fields)
        except Exception as exc:
            raise SourceError("airtable", f"writing {table} failed: {exc}") from exc

    def _update(self, table: str, record_id: str, fields: dict) -> dict:
        try:
            return self._tables[table].update(record_id, fields)
        except Exception as exc:
            raise SourceError("airtable", f"updating {table} failed: {exc}") from exc


def _loads(raw: Any) -> dict:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
