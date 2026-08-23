"""hootsuite connector.

Contract: expose fetch_* functions taking (week_start: date, week_end: date)
and returning plain dicts. No pandas here. Log every run to source_runs.
See CLAUDE.md conventions and config/kpis.yaml for which metrics need what.
"""
