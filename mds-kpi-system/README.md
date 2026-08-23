# MDS KPI System

Automated 13-KPI weekly scoreboard for Million Dollar Sellers. Replaces the
109-row manual spreadsheet. Pulls from Stripe, GoHighLevel, Luma, ClickUp,
Hootsuite, Intercom and our WhatsApp/app data, computes weekly snapshots into
an Airtable warehouse, and sends Claude-written Monday recaps per department.

## Status

**Phase 1 of `docs/roadmap.md` is built.** The growth department runs end to end:
Stripe and GoHighLevel pulls, the three cleanest metrics, append-only snapshots,
the pre-send checks, and the Monday recap in the CLAUDE.md voice. Phases 2 to 5
are still stubs.

| Piece | State |
|---|---|
| Warehouse schema + registry seed | `scripts/bootstrap_warehouse.py`, run once per base |
| Stripe connector (new member first payments) | done |
| GoHighLevel connector (discovery calls, lead source) | done |
| `new_members_paid`, `new_member_cash_collected`, `discovery_calls_showed` | done |
| Snapshots, revisions, source_runs | done |
| Validation (failed pulls, >5x moves) | done |
| Recap generation + Slack / n8n delivery | done |
| Retention, community, events, marketing, ops | stubs, phases 2 to 4 |

## Quick start

1. `cp .env.example .env` and fill in keys
2. `pip install -r requirements.txt`
3. Read `CLAUDE.md`, `config/kpis.yaml`, `docs/roadmap.md`
4. See a Monday recap right now, no credentials needed:
   `python scripts/demo_recap.py --no-llm`

## Standing up the warehouse

1. Create an empty Airtable base called **KPI Warehouse** and put its id in
   `AIRTABLE_WAREHOUSE_BASE_ID`. The API key needs `schema.bases:write`.
2. `python scripts/bootstrap_warehouse.py --dry-run` to see what it will do.
3. `python scripts/bootstrap_warehouse.py` to create `metrics`, `snapshots` and
   `source_runs` and seed the 13 registry rows from `config/kpis.yaml`.

The script is idempotent. It creates missing tables and missing fields and never
deletes or retypes anything, so re-run it whenever `kpis.yaml` changes.

## Running a week

```bash
python -m src.run_weekly                       # last full week, dry run, nothing written
python -m src.run_weekly --week 2026-08-17     # a specific week (any day in it)
python -m src.run_weekly --send                # write snapshots and deliver recaps
python -m src.run_weekly --no-llm              # skip Claude, deterministic recap
python -m src.run_weekly --json                # machine readable, for n8n
```

Dry run is the default. Nothing reaches Airtable or Slack without `--send`.

n8n calls `python -m src.run_weekly --send` Mondays 6am ET. It exits `0` on a
clean run, `1` when a check held the send, `2` on a config mistake.

### The two pre-send checks

- **A source pull failed.** Warning, not a block. The recap goes out and says
  "unavailable this week, source X failed", which is the fail-loud rule in
  CLAUDE.md. Pass `--require-all-green` to hold the send instead.
- **A metric moved more than 5x week over week.** Blocks the send, because that
  is nearly always a source change or a bug. The snapshot is still written, we
  hold the message not the history. Release it with `--acknowledge-anomalies`.

## How a metric gets built

```
config/kpis.yaml         the only place a metric_id may be invented
  src/connectors/*       one module per source system, plain dicts out
    src/context.py       lazily builds clients, logs every pull to source_runs
      src/metrics/*      one module per department, compute(week, ctx)
        src/models.py    MetricResult: value, sub_metrics, source_refs, error
          airtable_wh    append-only snapshot, revision + 1 for a correction
            recap/       Claude writes it, sender.py delivers it
```

Nothing converts a failed pull into a zero. A source failure becomes a failed
`source_runs` row, a `MetricResult` with `value=None` and a reason, and a line in
the recap naming the source.

## Notes on the tricky bits

- **Stripe MRR is never read.** New member counts and dollars come from invoices,
  filtered to customers with no earlier paid invoice. That first-payment check is
  what makes it a new member number rather than a payments number.
- **Weeks are Monday 00:00 to Sunday 23:59:59 US Eastern**, DST included. The
  169-hour November week is covered by a test.
- **Discovery calendars are config, not code.** Set `GHL_DISCOVERY_CALENDAR_IDS`,
  or leave it blank and every calendar whose name contains
  `GHL_DISCOVERY_CALENDAR_MATCH` (default `discovery`) is used. If nothing
  matches, the pull fails loudly rather than reporting zero calls.
- **The trailing 4-week conversion rate is a floor.** Calls late in the window
  have not had time to convert yet.
- **If Claude is unreachable** the recap still goes out, auto-formatted from the
  same facts, and says so.

## Tests

```bash
pip install -r requirements.txt
pytest
```

62 tests, no network. Source systems are fixture doubles in `tests/fakes.py`, and
`tests/test_run_weekly.py` runs the whole Monday flow against them.

## Working on this with Claude Code

This repo is designed to be built out by Claude Code. CLAUDE.md carries the
context. Good next prompts, in roadmap order:

- "Implement Phase 2: the renewal cohort builder per the
  renewal_collection_rate_21d spec in config/kpis.yaml, with tests using
  fixture invoices. Follow the pattern in src/metrics/growth.py."
- "Backfill the last 12 weeks of snapshots for the Phase 1 metrics."
- "Add the Luma connector and the member_weeks engagement union (Phase 3)."
