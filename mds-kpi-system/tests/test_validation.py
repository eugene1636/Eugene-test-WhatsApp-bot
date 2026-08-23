from datetime import date, datetime, timezone

from src.models import MetricResult, Snapshot, SourceRun
from src.validation import BLOCK, WARN, blocked, validate

WEEK = date(2026, 8, 17)
PRIOR = date(2026, 8, 10)


def snapshot(value, week=PRIOR):
    return Snapshot(metric_id="new_members_paid", week_start=week, value=value)


def failed_run():
    now = datetime.now(timezone.utc)
    return SourceRun("stripe", WEEK, "failed", now, now, error="401 invalid key")


def test_a_normal_week_produces_no_findings():
    results = [MetricResult("new_members_paid", WEEK, 4.0)]
    history = {"new_members_paid": [snapshot(3.0)]}
    assert validate(results, history, []) == []


def test_a_move_over_5x_blocks_the_send():
    results = [MetricResult("new_members_paid", WEEK, 40.0)]
    history = {"new_members_paid": [snapshot(3.0)]}
    findings = validate(results, history, [])

    assert [f.code for f in findings] == ["move_over_5x"]
    assert findings[0].level == BLOCK
    assert blocked(findings)


def test_a_collapse_over_5x_blocks_too():
    results = [MetricResult("new_members_paid", WEEK, 1.0)]
    history = {"new_members_paid": [snapshot(30.0)]}
    assert blocked(validate(results, history, []))


def test_acknowledging_an_anomaly_releases_the_send():
    results = [MetricResult("new_members_paid", WEEK, 40.0)]
    history = {"new_members_paid": [snapshot(3.0)]}
    findings = validate(results, history, [], acknowledge_anomalies=True)

    assert findings[0].level == WARN
    assert not blocked(findings)


def test_a_failed_source_warns_so_the_recap_can_say_unavailable():
    findings = validate([], {}, [failed_run()])
    assert findings[0].code == "source_failed"
    assert findings[0].level == WARN
    assert not blocked(findings)


def test_require_all_green_promotes_a_failed_source_to_blocking():
    findings = validate([], {}, [failed_run()], require_all_green=True)
    assert blocked(findings)


def test_an_unavailable_metric_is_never_compared_against_history():
    results = [MetricResult.unavailable("new_members_paid", WEEK, "stripe 503")]
    history = {"new_members_paid": [snapshot(3.0)]}
    findings = validate(results, history, [])

    assert [f.code for f in findings] == ["metric_unavailable"]
    assert not blocked(findings)


def test_no_prior_week_means_no_anomaly_check():
    results = [MetricResult("new_members_paid", WEEK, 99.0)]
    assert validate(results, {"new_members_paid": []}, []) == []
