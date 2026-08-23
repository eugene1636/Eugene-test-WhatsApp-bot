"""Apply db/schema.sql to the Supabase warehouse and seed the KPI registry.

Phase 1, first checklist item of docs/roadmap.md. Idempotent: run it as often as
you like, and re-run it whenever config/kpis.yaml changes. It creates what is
missing and never drops or retypes anything that holds data.

    python scripts/bootstrap_warehouse.py --dry-run
    python scripts/bootstrap_warehouse.py

Needs SUPABASE_DB_URL (Project settings -> Database -> Connection string, URI).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import registry  # noqa: E402
from src.warehouse import SCHEMA_PATH, Warehouse  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-seed", action="store_true", help="schema only")
    parser.add_argument("--dsn", help="override SUPABASE_DB_URL")
    args = parser.parse_args(argv)

    specs = list(registry.default().kpis.values())

    if args.dry_run:
        print(f"would apply {SCHEMA_PATH} to the warehouse:")
        for line in _objects(SCHEMA_PATH):
            print(f"  {line}")
        print(f"\nwould seed {len(specs)} KPI registry rows from config/kpis.yaml:")
        for spec in specs:
            print(f"  {spec.id} ({spec.department}, {spec.owner})")
        return 0

    warehouse = Warehouse(dsn=args.dsn)
    try:
        warehouse.apply_schema()
        print(f"schema applied from {SCHEMA_PATH}")
        if args.skip_seed:
            return 0
        count = warehouse.seed_metrics(specs)
        print(f"{count} KPI registry rows seeded")
        known = warehouse.known_metric_ids()
        print(f"warehouse now knows {len(known)} metrics")
    finally:
        warehouse.close()
    return 0


def _objects(path: Path) -> list[str]:
    """The create statements in the schema, for the dry run listing."""
    lines = []
    for raw in path.read_text().splitlines():
        stripped = raw.strip().lower()
        for prefix in (
            "create schema",
            "create table",
            "create index",
            "create or replace view",
            "create or replace function",
            "create trigger",
        ):
            if stripped.startswith(prefix):
                lines.append(raw.strip().rstrip("("). rstrip())
                break
    return lines


if __name__ == "__main__":
    raise SystemExit(main())
