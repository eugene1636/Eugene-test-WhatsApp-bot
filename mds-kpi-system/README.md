# MDS KPI System

Automated 13-KPI weekly scoreboard for Million Dollar Sellers. Replaces the
109-row manual spreadsheet. Pulls from Stripe, GoHighLevel, Luma, ClickUp,
Hootsuite, Intercom and our WhatsApp/app data, computes weekly snapshots into a
Supabase warehouse, and sends Claude-written Monday recaps per department.

## Status

**Phase 1 of `docs/roadmap.md` is built.** The growth department runs end to end:
Stripe and GoHighLevel pulls, the three cleanest metrics, append-only snapshots,
the pre-send checks, and the Monday recap in the CLAUDE.md voice. Phases 2 to 5
are still stubs.

| Piece | State |
|---|---|
| Warehouse schema + registry seed | `db/schema.sql`, applied by `scripts/bootstrap_warehouse.py` |
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

1. Create a Supabase project. Copy Project settings -> Database -> Connection
   string -> URI into `SUPABASE_DB_URL`.
2. `python scripts/bootstrap_warehouse.py --dry-run` to see what it will do.
3. `python scripts/bootstrap_warehouse.py` to apply `db/schema.sql` and seed the
   13 registry rows from `config/kpis.yaml`.

Idempotent, so re-run it whenever `kpis.yaml` changes. It creates what is missing
and never drops or retypes anything holding data. `psql "$SUPABASE_DB_URL" -f
db/schema.sql` does the schema half if you would rather run it yourself.

### What the database guarantees

These are constraints in `db/schema.sql`, not conventions in Python, so a stray
script or somebody in the Supabase table editor cannot break them either:

- `kpi.snapshots` is append-only. UPDATE and DELETE raise. A correction is a new
  row with revision + 1, and the database picks the revision.
- A snapshot cannot be available with no value, or unavailable with no reason.
- A snapshot cannot reference a metric_id that is not in `kpi.metrics`, which is
  seeded from `config/kpis.yaml`.

Dashboards read two views: `kpi.snapshots_current` (latest revision per
metric-week) and `kpi.board` (every KPI with its latest value and 4 week
average).

## Before the first real run

```bash
python scripts/preflight.py
```

Small read-only calls against every configured system, reporting what each one
actually answered. Where a setting is ambiguous it probes the options and prints
the `.env` line to use, which matters most for GoHighLevel: it finds the Version
header your token answers to and whether contact lookup is the current
`POST /contacts/search` or the older `GET /contacts/`. Anything unconfigured is
reported as skipped, never as passing.

## Running a week

```bash
python -m src.run_weekly                       # last full week, dry run, nothing written
python -m src.run_weekly --week 2026-08-17     # a specific week (any day in it)
python -m src.run_weekly --send                # write snapshots and deliver recaps
python -m src.run_weekly --no-llm              # skip Claude, deterministic recap
python -m src.run_weekly --json                # machine readable, for n8n
```

Dry run is the default. Nothing reaches Supabase or Slack without `--send`.

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
config/kpis.yaml        the only place a metric_id may be invented
  src/connectors/*      one module per source system, plain dicts out
    src/context.py      lazily builds clients, logs every pull to source_runs
      src/metrics/*     one module per department, compute(week, ctx)
        src/models.py   MetricResult: value, sub_metrics, source_refs, error
          warehouse.py  append-only snapshot, revision + 1 for a correction
            recap/      Claude writes it, sender.py delivers it
```

Nothing converts a failed pull into a zero. A source failure becomes a failed
`source_runs` row, a `MetricResult` with `value=None` and a reason, and a line in
the recap naming the source.

## Notes on the tricky bits

- **Stripe MRR is never read.** New member counts and dollars come from invoices.
  A payment counts when it *settled* inside the week (Stripe can only filter on
  `created`, so the pull reaches back a week and then filters on `paid_at`) and
  when it is the earliest invoice that customer has ever paid. Comparing on
  paid_at rather than created is what makes a card retry land in the right week.
- **Plan interval survives every Stripe API version.** Stripe removed
  `line.price` in the 2025 versions, so `_plan_interval` tries `price.recurring`,
  then the legacy `plan`, then derives it from the length of the line period,
  which needs no expansion and works everywhere.
- **Weeks are Monday 00:00 to Sunday 23:59:59 US Eastern**, DST included. The
  169-hour November week is covered by a test.
- **Discovery calendars are config, not code.** Set `GHL_DISCOVERY_CALENDAR_IDS`,
  or leave it blank and every calendar whose name contains
  `GHL_DISCOVERY_CALENDAR_MATCH` (default `discovery`) is used. If nothing
  matches, the pull fails loudly rather than reporting zero calls.
- **GoHighLevel has two live API generations.** The Version header and the
  contact search endpoint both changed. `GHL_API_VERSION` (default `v3`) and
  `GHL_CONTACT_SEARCH` (default `post`) pick which one, and preflight tells you
  which your token wants rather than making you guess.
- **The trailing 4-week conversion rate is a floor.** Calls late in the window
  have not had time to convert yet.
- **If Claude is unreachable** the recap still goes out, auto-formatted from the
  same facts, and says so.

## Tests

```bash
pip install -r requirements.txt
pytest                                            # 74 tests, no database
TEST_DATABASE_URL=postgresql://... pytest         # all 97, warehouse included
```

No network. Source systems are fixture doubles in `tests/fakes.py`.

The warehouse is *not* faked. The rules above live in `db/schema.sql`, so testing
them against a stub would test nothing. Point `TEST_DATABASE_URL` at any empty
database (a local Postgres, or a Supabase branch) and those tests run against it;
without it they skip rather than pretending to pass, so CI should always set it.
`tests/test_run_weekly.py` runs the whole Monday flow, fixture sources into a
real database.

## Working on this with Claude Code

This repo is designed to be built out by Claude Code. CLAUDE.md carries the
context. Good next prompts, in roadmap order:

- "Implement Phase 2: the renewal cohort builder per the
  renewal_collection_rate_21d spec in config/kpis.yaml, with tests using
  fixture invoices. Follow the pattern in src/metrics/growth.py, and add the
  renewal_cohorts table to db/schema.sql."
- "Backfill the last 12 weeks of snapshots for the Phase 1 metrics."
- "Add the Luma connector and the member_weeks engagement union (Phase 3)."
