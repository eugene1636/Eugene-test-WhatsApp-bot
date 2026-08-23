# Architecture

```
 Stripe  GoHighLevel  Luma  ClickUp  Hootsuite  Intercom  WhatsApp/App/FB
    \        |          |       |        |          |          /
     \       |          |       |        |          |         /
      +------+----------+-------+--------+----------+--------+
      |             src/connectors/*  (weekly pulls)          |
      +------------------------------+------------------------+
                                     |
                          src/metrics/*  (compute 13 KPIs)
                                     |
                    Supabase (Postgres) "kpi" schema
                     - metrics (registry from kpis.yaml)
                     - snapshots (append-only weekly values)
                     - member_weeks (engagement union)
                     - renewal_cohorts
                     - source_runs (pull logs, fail-loud)
                     - views: snapshots_current, board
                                     |
                +--------------------+--------------------+
                |                                         |
     Dashboards read the views                src/recap/* (Claude API)
     (board + per-KPI drill-downs)            Monday recaps -> Slack/WhatsApp
```

## Key design decisions

1. Supabase is the warehouse, not the compute layer. Python computes, Postgres
   stores and serves. Airtable stays the member system of record and is a source
   for the phase 3 metrics whose inputs already live in the ScoreCard base.
2. Snapshots are append-only, enforced by a trigger in `db/schema.sql` rather
   than by convention. History never mutates. Corrections = new revision. The
   same file refuses a snapshot that is available with no value, unavailable
   with no reason, or attached to a metric_id that is not in the registry.
3. Renewal collection is cohort-based on invoice due dates. We never read Stripe's
   MRR or subscription amount fields as truth (discounts, date changes and tier
   changes have made them unreliable for us).
4. Engagement is a union. Each channel pull can be lossy; the union trend is the
   signal. member_weeks has one row per member per week with boolean per channel.
5. Fail loud. Every pull writes a source_runs row. Recap generator checks it and
   says "unavailable, source X failed" instead of showing stale/zero numbers.
6. Recaps are generated, not templated. Claude API gets the snapshot + 8 weeks of
   history + the sub-metrics and writes 5-8 sentences per department in the voice
   defined in CLAUDE.md. One suggested action max per recap.

## Scheduling

n8n (already in our stack) triggers `python src/run_weekly.py` Mondays 6am ET.
Recaps send 8am ET after human-free validation checks pass. Implemented in
`src/validation.py` at two severities: a >5x week over week move blocks the send
(release it with `--acknowledge-anomalies`), while a failed pull only warns, so the
recap still goes out carrying the "unavailable, source X failed" line the fail-loud
rule requires. Pass `--require-all-green` to hold the send on any failed pull.
