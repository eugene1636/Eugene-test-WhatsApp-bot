"""The KPI warehouse: Supabase (Postgres).

Python computes, Supabase stores and serves. The schema lives in `db/schema.sql`
and is the authority on shape and on the rules we refuse to break:

- `kpi.snapshots` is append-only, enforced by a trigger, not by good manners.
  A correction is a new row with revision + 1.
- A snapshot may not claim to be available without a value, or unavailable
  without a reason. That is the fail-loud rule, as a check constraint.
- A snapshot may not reference a metric_id that is not in `kpi.metrics`, which
  is seeded from config/kpis.yaml.

Dashboards read `kpi.snapshots_current` (latest revision per metric-week) and
`kpi.board` (every KPI with its most recent value and 4 week average).
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence

from . import config
from .errors import SourceError
from .models import MetricResult, Snapshot, SourceRun
from .registry import KpiSpec

SCHEMA_PATH = config.REPO_ROOT / "db" / "schema.sql"


class WarehouseError(SourceError):
    """The warehouse is unreachable or refused a write."""

    def __init__(self, message: str) -> None:
        super().__init__("warehouse", message)


UPSERT_METRIC = """
insert into kpi.metrics
    (metric_id, name, department, owner, type, sources, definition, sub_metric_specs)
values
    (%(metric_id)s, %(name)s, %(department)s, %(owner)s, %(type)s,
     %(sources)s, %(definition)s, %(sub_metric_specs)s)
on conflict (metric_id) do update set
    name = excluded.name,
    department = excluded.department,
    owner = excluded.owner,
    type = excluded.type,
    sources = excluded.sources,
    definition = excluded.definition,
    sub_metric_specs = excluded.sub_metric_specs,
    updated_at = now()
"""

INSERT_SNAPSHOT = """
insert into kpi.snapshots
    (metric_id, week_start, revision, value, available, sub_metrics, source_refs,
     error, computed_at)
values
    (%(metric_id)s, %(week_start)s,
     (select coalesce(max(revision) + 1, 0) from kpi.snapshots
      where metric_id = %(metric_id)s and week_start = %(week_start)s),
     %(value)s, %(available)s, %(sub_metrics)s, %(source_refs)s, %(error)s,
     %(computed_at)s)
returning id, revision
"""

INSERT_SOURCE_RUN = """
insert into kpi.source_runs
    (source, week_start, status, started_at, finished_at, records_fetched, error, note)
values
    (%(source)s, %(week_start)s, %(status)s, %(started_at)s, %(finished_at)s,
     %(records_fetched)s, %(error)s, %(note)s)
returning id
"""

SELECT_HISTORY = """
select week_start, value, revision, sub_metrics, error
from kpi.snapshots_current
where metric_id = %(metric_id)s and week_start = any(%(weeks)s)
order by week_start
"""


class Warehouse:
    def __init__(self, dsn: str | None = None, connection: Any = None) -> None:
        if connection is not None:
            self._conn = connection
            return
        import psycopg  # noqa: PLC0415

        target = dsn or config.require("SUPABASE_DB_URL")
        try:
            self._conn = psycopg.connect(target, autocommit=True)
        except Exception as exc:
            raise WarehouseError(f"cannot connect: {type(exc).__name__}: {exc}") from exc

    # ------------------------------------------------------------------ setup

    def apply_schema(self, path: Path | None = None) -> None:
        """Run db/schema.sql. Idempotent, safe against a live warehouse."""
        sql = (path or SCHEMA_PATH).read_text()
        with self._cursor() as cur:
            cur.execute(sql)

    def seed_metrics(self, specs: Sequence[KpiSpec]) -> int:
        rows = [
            {
                "metric_id": spec.id,
                "name": spec.name,
                "department": spec.department,
                "owner": spec.owner,
                "type": spec.type,
                "sources": list(spec.sources),
                "definition": spec.definition,
                "sub_metric_specs": list(spec.sub_metric_specs),
            }
            for spec in specs
        ]
        with self._cursor() as cur:
            cur.executemany(UPSERT_METRIC, rows)
        return len(rows)

    def known_metric_ids(self) -> set[str]:
        with self._cursor() as cur:
            cur.execute("select metric_id from kpi.metrics")
            return {row[0] for row in cur.fetchall()}

    # -------------------------------------------------------------- snapshots

    def next_revision(self, metric_id: str, week_start: date) -> int:
        with self._cursor() as cur:
            cur.execute(
                "select coalesce(max(revision) + 1, 0) from kpi.snapshots"
                " where metric_id = %s and week_start = %s",
                (metric_id, week_start),
            )
            return int(cur.fetchone()[0])

    def write_snapshot(
        self, result: MetricResult, computed_at: datetime | None = None
    ) -> dict:
        """Append one snapshot. The revision is picked by the database."""
        with self._cursor() as cur:
            row = self._insert_snapshot(cur, result, computed_at)
        return row

    def write_source_run(self, run: SourceRun) -> int:
        with self._cursor() as cur:
            return self._insert_source_run(cur, run)

    def write_week(
        self,
        results: Sequence[MetricResult],
        runs: Sequence[SourceRun],
        computed_at: datetime | None = None,
    ) -> list[dict]:
        """One transaction for the whole week, so a crash never half-writes it."""
        written: list[dict] = []
        with self._transaction() as cur:
            for result in results:
                written.append(self._insert_snapshot(cur, result, computed_at))
            for run in runs:
                self._insert_source_run(cur, run)
        return written

    def history(self, metric_id: str, weeks: Sequence[date]) -> list[Snapshot]:
        """Latest revision per requested week, oldest first, missing weeks skipped."""
        if not weeks:
            return []
        with self._cursor() as cur:
            cur.execute(SELECT_HISTORY, {"metric_id": metric_id, "weeks": list(weeks)})
            rows = cur.fetchall()
        return [
            Snapshot(
                metric_id=metric_id,
                week_start=row[0],
                value=row[1],
                revision=row[2],
                sub_metrics=row[3] or {},
                error=row[4] or None,
            )
            for row in rows
        ]

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:  # closing a broken connection is not news
            pass

    # ------------------------------------------------------------- primitives

    def _insert_snapshot(
        self, cur: Any, result: MetricResult, computed_at: datetime | None
    ) -> dict:
        from psycopg.types.json import Json  # noqa: PLC0415

        if not result.available and not result.error:
            raise WarehouseError(
                f"{result.metric_id} has no value and no reason. "
                "An unavailable metric must say which source failed."
            )
        cur.execute(
            INSERT_SNAPSHOT,
            {
                "metric_id": result.metric_id,
                "week_start": result.week_start,
                "value": result.value,
                "available": result.available,
                "sub_metrics": Json(result.sub_metrics),
                "source_refs": Json(result.source_refs),
                "error": result.error,
                "computed_at": computed_at or datetime.now(timezone.utc),
            },
        )
        row = cur.fetchone()
        return {"id": row[0], "revision": row[1], "metric_id": result.metric_id}

    def _insert_source_run(self, cur: Any, run: SourceRun) -> int:
        cur.execute(
            INSERT_SOURCE_RUN,
            {
                "source": run.source,
                "week_start": run.week_start,
                "status": run.status,
                "started_at": run.started_at,
                "finished_at": run.finished_at,
                "records_fetched": run.records_fetched,
                "error": run.error,
                "note": run.note,
            },
        )
        return int(cur.fetchone()[0])

    @contextmanager
    def _cursor(self) -> Iterator[Any]:
        try:
            with self._conn.cursor() as cur:
                yield cur
        except Exception as exc:
            raise _wrap(exc) from exc

    @contextmanager
    def _transaction(self) -> Iterator[Any]:
        try:
            with self._conn.transaction():
                with self._conn.cursor() as cur:
                    yield cur
        except Exception as exc:
            raise _wrap(exc) from exc


def _wrap(exc: Exception) -> Exception:
    if isinstance(exc, WarehouseError):
        return exc
    return WarehouseError(f"{type(exc).__name__}: {exc}")
