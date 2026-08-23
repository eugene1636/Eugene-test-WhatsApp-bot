# Build roadmap

Ship value every phase. Do not build all 13 before the first recap goes out.

## Phase 1: Warehouse + cleanest metrics (week 1-2)

- [x] Create the Supabase KPI warehouse: schema `kpi` with `metrics` (the
      registry, seeded from config/kpis.yaml), `snapshots` (append-only weekly
      values) and `source_runs` (pull logs with status, for the fail-loud rule),
      plus the `snapshots_current` and `board` views dashboards read.
      -> `db/schema.sql` + `scripts/bootstrap_warehouse.py`. Still needs running
      once against a real project (see README, Standing up).
- [x] Stripe connector: new member first payments (count + dollars)
- [x] GoHighLevel connector: discovery calls booked/canceled/showed
- [x] Compute + snapshot: new_members_paid, new_member_cash_collected,
      discovery_calls_showed
- [x] Minimal recap: one Slack message to Eugene every Monday 8am ET with those 3
      metrics vs prior 4-week avg. Claude API writes the callout in the recap voice.
- [ ] MILESTONE: first automated Monday recap received. Nothing else matters until this.
      Blocked only on credentials and the n8n schedule, the code path is done and
      covered by tests. `python scripts/demo_recap.py` shows what lands.

## Phase 2: Retention cohorts (week 2-4)

- [ ] Renewal cohort builder: for each week, the set of members with renewal due
      (from Stripe invoices/upcoming invoices, NOT subscription MRR fields)
- [ ] Collection checker: 14d and 21d collection status per cohort, dollars open,
      member names for the open list
- [ ] Backfill last 12 weeks of cohorts so trend exists on day one
- [ ] Add to recap for Tina/Anita

## Phase 3: Engagement union (week 3-6)

- [ ] Per-channel weekly activity pulls: Luma (reg/check-in), WhatsApp (existing
      n8n data), app sessions, Facebook (posts/comments only, lurkers accepted)
- [ ] Member-week union table in warehouse -> weekly_engaged_members
- [ ] Trailing 90-day zero-activity scan -> unengaged_members_90d, cross-ref
      renewal dates for the "approaching renewal" sub-metric
- [ ] new_member_activation_60d composite from Airtable fields + Luma
- NOTE: this is the highest-leverage phase for retention. Same pipe feeds three KPIs.

## Phase 4: Events + marketing + ops (week 5-8)

- [ ] ClickUp connector: read budget tasks per event list (Events space,
      Past Events folder), committed cost custom fields
- [ ] Event template change (human task for Courtney): budget task with committed
      costs required at event close
- [ ] Luma qualified-lead cross-ref with GoHighLevel for qualified_leads_registered
- [ ] NPS ingestion, stored as decimals
- [ ] Hootsuite connector: posts published, follower counts
- [ ] ESP pull: emails sent + open rate
- [ ] Intercom connector: resolution medians, volume, reopens
- [ ] Full 13-metric board live

## Phase 5: Department recaps + dashboards (week 7-10)

- [ ] Per-department Monday recaps (Slack and/or WhatsApp), each showing only that
      team's 2-4 KPIs and sub-metrics, with one suggested action
- [ ] Eugene/Ian exec recap: all 13, one screen, biggest mover flagged
- [ ] Dashboards on the warehouse views: one board view (13 KPIs, RAG vs 4-week
      trend) off `kpi.board`, one drill-down per KPI off `kpi.snapshots_current`
      reading the sub_metrics json
- [ ] Kill the old spreadsheet. Announce at L10.

## Parked (explicitly not in scope until later)

- Lead validation process -> qualified_pipeline_adds KPI (Sashani project first)
- Custom dashboard app (Airtable interfaces are fine for v1)
- Monthly finance pack automation (event profit, tech spend) separate effort
