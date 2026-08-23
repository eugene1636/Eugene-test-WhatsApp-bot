"""Create (or top up) the Airtable KPI Warehouse tables, then seed the registry.

Phase 1, first checklist item of docs/roadmap.md. Idempotent: run it as often as
you like. It creates missing tables and missing fields, and never deletes or
retypes anything that already exists.

    python scripts/bootstrap_warehouse.py --dry-run
    python scripts/bootstrap_warehouse.py

Needs AIRTABLE_API_KEY (with schema.bases:write) and AIRTABLE_WAREHOUSE_BASE_ID.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config, registry  # noqa: E402
from src.connectors.airtable_wh import (  # noqa: E402
    METRICS_TABLE,
    SNAPSHOTS_TABLE,
    SOURCE_RUNS_TABLE,
    Warehouse,
)

META = "https://api.airtable.com/v0/meta/bases"

SCHEMA: dict[str, list[dict]] = {
    METRICS_TABLE: [
        {"name": "metric_id", "type": "singleLineText"},
        {"name": "name", "type": "singleLineText"},
        {"name": "department", "type": "singleLineText"},
        {"name": "owner", "type": "singleLineText"},
        {"name": "type", "type": "singleLineText"},
        {"name": "sources", "type": "singleLineText"},
        {"name": "definition", "type": "multilineText"},
        {"name": "sub_metric_specs", "type": "multilineText"},
    ],
    SNAPSHOTS_TABLE: [
        {"name": "key", "type": "singleLineText"},
        {"name": "metric_id", "type": "singleLineText"},
        {"name": "week_start", "type": "date", "options": {"dateFormat": {"name": "iso"}}},
        {"name": "value", "type": "number", "options": {"precision": 2}},
        {"name": "available", "type": "checkbox",
         "options": {"color": "greenBright", "icon": "check"}},
        {"name": "revision", "type": "number", "options": {"precision": 0}},
        {"name": "sub_metrics", "type": "multilineText"},
        {"name": "source_refs", "type": "multilineText"},
        {"name": "error", "type": "multilineText"},
        {"name": "computed_at", "type": "singleLineText"},
    ],
    SOURCE_RUNS_TABLE: [
        {"name": "run_key", "type": "singleLineText"},
        {"name": "source", "type": "singleLineText"},
        {"name": "week_start", "type": "date", "options": {"dateFormat": {"name": "iso"}}},
        {"name": "status", "type": "singleLineText"},
        {"name": "started_at", "type": "singleLineText"},
        {"name": "finished_at", "type": "singleLineText"},
        {"name": "records_fetched", "type": "number", "options": {"precision": 0}},
        {"name": "error", "type": "multilineText"},
        {"name": "note", "type": "multilineText"},
    ],
}


def headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {config.require('AIRTABLE_API_KEY')}",
        "Content-Type": "application/json",
    }


def existing_tables(base_id: str) -> dict[str, dict]:
    response = requests.get(f"{META}/{base_id}/tables", headers=headers(), timeout=30)
    response.raise_for_status()
    return {t["name"]: t for t in response.json().get("tables", [])}


def create_table(base_id: str, name: str, fields: list[dict]) -> dict:
    response = requests.post(
        f"{META}/{base_id}/tables",
        headers=headers(),
        json={"name": name, "fields": fields},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def create_field(base_id: str, table_id: str, field: dict) -> dict:
    response = requests.post(
        f"{META}/{base_id}/tables/{table_id}/fields",
        headers=headers(),
        json=field,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-seed", action="store_true", help="tables only, no registry rows")
    args = parser.parse_args(argv)

    base_id = config.require("AIRTABLE_WAREHOUSE_BASE_ID")
    present = existing_tables(base_id)
    print(f"base {base_id}: {len(present)} tables already there")

    for table_name, fields in SCHEMA.items():
        table = present.get(table_name)
        if table is None:
            print(f"  + create table {table_name} ({len(fields)} fields)")
            if not args.dry_run:
                create_table(base_id, table_name, fields)
            continue
        have = {f["name"] for f in table.get("fields", [])}
        for field in fields:
            if field["name"] in have:
                continue
            print(f"  + add field {table_name}.{field['name']}")
            if not args.dry_run:
                create_field(base_id, table["id"], field)
        print(f"  = table {table_name} present")

    if args.skip_seed:
        return 0
    specs = list(registry.default().kpis.values())
    print(f"seeding {len(specs)} KPI registry rows from config/kpis.yaml")
    if args.dry_run:
        for spec in specs:
            print(f"  - {spec.id} ({spec.department}, {spec.owner})")
        return 0
    written = Warehouse().seed_metrics(specs)
    print(f"  {len(written)} registry rows written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
