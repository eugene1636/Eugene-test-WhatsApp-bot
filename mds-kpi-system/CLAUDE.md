# MDS KPI System

## What this project is

Million Dollar Sellers (MDS) is a ~700 member community of 7-9 figure ecommerce founders.
We are replacing a 109-row manual spreadsheet with a 13-KPI automated weekly scoreboard.
Every KPI must be pullable automatically every Monday with zero manual data entry.
The hard rule: if a metric can't be pulled automatically from a source system, it is not
a KPI, it's a report, and it does not go on the board.

The system does three things:
1. Pulls raw data weekly from source systems into the Supabase KPI warehouse
2. Computes the 13 KPIs + their sub-metrics and writes weekly snapshots
3. Generates department-specific weekly recaps (with callouts on issues and suggested
   actions) using the Claude API, delivered via Slack and/or WhatsApp

The single source of truth for KPI definitions is `config/kpis.yaml`. Read it before
implementing any metric. `docs/kpi-definitions.md` is the human-readable version.

## Stack and source systems

- Python 3.11+, plain scripts, cron/n8n-triggered. No framework. Keep it boring.
- Supabase (Postgres) = the KPI warehouse. Schema in `db/schema.sql`, access in
  `src/warehouse.py`. The append-only rule and the no-value-no-reason rule are
  database constraints, not conventions, so nothing can quietly break them.
- Airtable = member system of record (ScoreCard base already exists). A source
  for the phase 3 activation and engagement metrics, not the warehouse.
- Stripe = payments/subscriptions (WARNING: Stripe MRR is known-broken for us due to
  discounts, changed subscription dates and tier changes. NEVER compute MRR from
  Stripe subscription objects. Renewal collection is computed from invoices/charges
  against a due-date cohort instead. See kpis.yaml -> renewal_collection_rate.)
- GoHighLevel = CRM/pipeline (discovery calls, lead attribution)
- Luma = event registrations and check-ins
- ClickUp = tasks (event budgets live here per event list)
- Hootsuite = social publishing (posts published count)
- ESP (via GoHighLevel) = emails/newsletters sent
- Intercom = member support
- WhatsApp (via existing n8n/Coexistence setup, same infra as our member assistant) =
  engagement signal + recap delivery channel

## Conventions

- One connector module per source system in `src/connectors/`. Each exposes
  `fetch_<thing>(week_start, week_end)` returning plain dicts. No pandas in connectors.
- One metric module per department in `src/metrics/`. Each exposes
  `compute(week: Week, ctx: RunContext) -> list[MetricResult]`. The context is
  what makes the modules testable: it builds source clients lazily, memoizes
  shared trailing windows via `ctx.pull_once`, and writes a `source_runs` row for
  every pull. Metric modules never construct a client themselves.
- Every metric writes: metric_id, week_start, value, sub_metrics (json), source_refs
  (json of record ids used), computed_at. Snapshots are append-only. Never overwrite
  a prior week; corrections are new rows with a `revision` increment.
- Weeks run Monday 00:00 to Sunday 23:59 US Eastern.
- All secrets from env vars, listed in `.env.example`. Never hardcode keys.
- Fail loud: if a source pull fails, the recap must say "metric unavailable this week,
  source X failed" rather than silently showing a stale or zero value. In code that
  means `SourceError` -> a failed `source_runs` row -> `MetricResult(value=None,
  error=...)`. Nothing catches a source failure and returns 0.
- A failed pull warns, it does not hold the send (the recap carries the bad news).
  A metric moving more than 5x week over week does hold the send, because that is
  nearly always a source change. `--require-all-green` and `--acknowledge-anomalies`
  flip each of those. See `src/validation.py`.

## Recap voice (important)

Recaps go to real team members. Write them like a text from a sharp friend, not a
corporate report. Casual, direct, short sentences. No em-dashes ever. No "per our
analysis". Lead with what changed, flag what needs attention, suggest one concrete
action. Example tone: "Discovery shows dropped to 4 this week, lowest since March.
Two of the cancels were reschedules so not panic time, but worth watching Monday's
calendar."

## Definitions of tricky terms

- "Renewal cohort": all members whose subscription renewal was DUE in a given week,
  regardless of when/whether they paid. Collection is measured 14 and 21 days after
  the due date. A member who lapses and pays on day 16 counts as collected at day 21.
- "Engaged" (member-week): did at least ONE of: Luma registration or check-in,
  WhatsApp group activity, app session, Facebook post/comment. It's a union across
  channels. Imperfect per-channel data is fine, the union trend is the metric.
- "Activated" (new member): hit ALL THREE within 60 days of join: onboarding call,
  value-add completed, registered for an in-person event.
- "Event closed": event end date has passed and the event lead marked the ClickUp
  budget task complete with committed costs logged.

## What NOT to build

- No MRR calculations from Stripe subscriptions (known broken, see above)
- No task-completion-rate metrics from ClickUp (tried before, never worked)
- No attendance-rate metric (static, no financial meaning for us)
- No paid-media attribution metrics (delayed attribution, quarterly analysis only)
- No app WAU/MAU on the main board (app is no longer a focus)
- No dashboards inside this repo for v1. Dashboards read the warehouse views
  `kpi.board` and `kpi.snapshots_current` (Supabase table views first, a BI tool
  later). This repo is pull + compute + recap.

## Build order

Follow `docs/roadmap.md`. Phase 1 is the warehouse schema + the three metrics whose
data is cleanest (new members paid, cash collected, discovery calls showed). Get one
real Monday recap in Eugene's hands before building the rest.

Phase 1 is built. `src/metrics/growth.py` is the reference implementation, copy its
shape for the next department: pull through `ctx`, catch `SourceError` per source so
one dead API only takes down the metrics that need it, degrade sub-metrics to
`{"unavailable": reason}` rather than dropping them. Tests use fixture doubles in
`tests/fakes.py`, never the network.
