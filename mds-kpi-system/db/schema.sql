-- MDS KPI warehouse, Supabase (Postgres).
--
-- Idempotent: safe to run against a live warehouse on every deploy. It creates
-- what is missing and never drops or retypes anything that holds data.
--
--     psql "$SUPABASE_DB_URL" -f db/schema.sql
--     python scripts/bootstrap_warehouse.py     (does the same, then seeds metrics)
--
-- The append-only rule from CLAUDE.md is enforced here rather than in Python, so
-- a stray script or somebody in the Supabase table editor cannot rewrite a week
-- that already went out. Corrections are a new row with revision + 1.

create schema if not exists kpi;

-- The registry, seeded from config/kpis.yaml. Nothing may snapshot a metric_id
-- that is not in this table.
create table if not exists kpi.metrics (
    metric_id         text primary key,
    name              text        not null,
    department        text        not null,
    owner             text        not null default 'unassigned',
    type              text        not null check (type in ('predictive', 'responsive')),
    sources           text[]      not null default '{}',
    definition        text        not null default '',
    sub_metric_specs  text[]      not null default '{}',
    updated_at        timestamptz not null default now()
);

-- Append-only weekly values. One row per (metric, week, revision).
create table if not exists kpi.snapshots (
    id           bigint generated always as identity primary key,
    metric_id    text        not null references kpi.metrics (metric_id),
    week_start   date        not null,
    revision     integer     not null default 0 check (revision >= 0),
    value        double precision,
    available    boolean     not null,
    sub_metrics  jsonb       not null default '{}'::jsonb,
    source_refs  jsonb       not null default '{}'::jsonb,
    error        text,
    computed_at  timestamptz not null default now(),
    unique (metric_id, week_start, revision),
    -- fail loud: an available metric has a value, an unavailable one has a reason
    constraint snapshots_available_has_value
        check ((available and value is not null) or (not available and error is not null))
);

create index if not exists snapshots_metric_week_idx
    on kpi.snapshots (metric_id, week_start desc, revision desc);
create index if not exists snapshots_week_idx
    on kpi.snapshots (week_start desc);

-- Every source pull, success or failure. This is what makes the fail-loud rule
-- auditable after the fact.
create table if not exists kpi.source_runs (
    id               bigint generated always as identity primary key,
    source           text        not null,
    week_start       date        not null,
    status           text        not null check (status in ('success', 'failed')),
    started_at       timestamptz not null,
    finished_at      timestamptz not null,
    records_fetched  integer     not null default 0,
    error            text,
    note             text
);

create index if not exists source_runs_week_source_idx
    on kpi.source_runs (week_start desc, source);

-- History never mutates.
create or replace function kpi.reject_snapshot_mutation()
returns trigger
language plpgsql
as $$
begin
    raise exception
        'kpi.snapshots is append-only. Write a new row with revision + 1 instead of a %.',
        lower(tg_op);
end;
$$;

drop trigger if exists snapshots_append_only on kpi.snapshots;
create trigger snapshots_append_only
    before update or delete on kpi.snapshots
    for each row execute function kpi.reject_snapshot_mutation();

-- What dashboards read: the latest revision of every metric-week.
create or replace view kpi.snapshots_current as
select distinct on (metric_id, week_start)
       id, metric_id, week_start, revision, value, available,
       sub_metrics, source_refs, error, computed_at
from kpi.snapshots
order by metric_id, week_start desc, revision desc;

-- The board: every KPI with its most recent week and its 4 week average.
create or replace view kpi.board as
select m.metric_id,
       m.name,
       m.department,
       m.owner,
       m.type,
       latest.week_start,
       latest.value,
       latest.available,
       latest.error,
       avg4.avg_4w
from kpi.metrics m
left join lateral (
    select s.week_start, s.value, s.available, s.error
    from kpi.snapshots_current s
    where s.metric_id = m.metric_id
    order by s.week_start desc
    limit 1
) latest on true
left join lateral (
    select round(avg(s.value)::numeric, 2) as avg_4w
    from (
        select s2.value
        from kpi.snapshots_current s2
        where s2.metric_id = m.metric_id
          and s2.available
          and s2.week_start < latest.week_start
        order by s2.week_start desc
        limit 4
    ) s
) avg4 on true;
