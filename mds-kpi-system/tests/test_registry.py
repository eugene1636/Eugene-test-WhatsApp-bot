from src import registry


def test_all_thirteen_kpis_load():
    reg = registry.load()
    assert len(reg) == 13


def test_phase_one_metrics_exist_and_belong_to_growth():
    reg = registry.load()
    for metric_id in (
        "new_members_paid",
        "new_member_cash_collected",
        "discovery_calls_showed",
    ):
        assert reg[metric_id].department == "growth"
        assert reg[metric_id].owner == "Sashani"


def test_unknown_metric_id_is_a_loud_keyerror():
    reg = registry.load()
    try:
        reg["mrr_from_stripe_subscriptions"]
    except KeyError as exc:
        assert "kpis.yaml" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected KeyError")


def test_every_kpi_has_a_department_and_a_definition():
    reg = registry.load()
    for spec in reg.kpis.values():
        assert spec.department
        assert spec.definition
        assert spec.type in {"predictive", "responsive"}
