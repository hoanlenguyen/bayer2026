import pytest

from app import catalog as cat
from app.decision import freshness, governance, scope_match

from .helpers import plan, preset_intent


@pytest.fixture(autouse=True)
def _catalog():
    cat.reset_catalog()


@pytest.mark.parametrize("preset_id, expected, asset", [
    ("scn_reuse_eylea_jp", "reuse", "AST-0079"),
    ("scn_repair_xarelto_mx", "repair", "AST-0217"),
    ("scn_repair_canada_budget", "repair", "AST-0016"),
    ("req_migrate_xarelto", "migrate", "AST-0070"),
    ("req_finance_gtn", "new_build", None),
    ("req_supply_risk", "new_build", None),
    ("scn_out_of_scope", "not_feasible", None),
])
def test_decisions(preset_id, expected, asset):
    _, d = plan(preset_id)
    assert d["decision"] == expected
    if asset:
        assert d["candidate"]["asset_id"] == asset
    assert d["rules_applied"]


def test_new_build_targets_a_shared_model_and_flags_sprawl():
    _, d = plan("req_finance_gtn")
    assert d["target_model_id"] in cat.CATALOG["models"]
    assert d["flags"] and all("retir" in f["message"] or "consolidat" in f["message"] for f in d["flags"])


def test_migration_does_not_migrate_waste():
    _, d = plan("req_migrate_xarelto")
    tableau = [a["id"] for a in cat.CATALOG["assets"] if a["platform"] == "Tableau" and a["product_scope"] == "Xarelto"]
    assert set(d["replaces"]) == set(tableau)
    assert any("retire, do not migrate" in f["message"] for f in d["flags"])


def test_repair_lists_fixes():
    _, d = plan("scn_repair_xarelto_mx")
    assert d["change_type"] == "maintenance" and "owner" in d["reason"]


def test_scope_match():
    asset = {"product_scope": "Eylea", "market_scope": "JP"}
    assert scope_match(preset_intent("scn_reuse_eylea_jp"), asset, cat.CATALOG)[0] == 1.0
    assert scope_match(preset_intent("req_finance_gtn"), asset, cat.CATALOG)[0] == 0.0


def test_governance_is_relative_to_requested_kpis():
    a = cat.asset_by_id("AST-0001")
    with_conflict, _ = governance(a, {"measures": ["demand_forecast_accuracy"]})
    without, _ = governance(a, {"measures": ["net_sales_growth"]})
    assert without > with_conflict
    assert freshness({"refresh_status": "failed"}) < freshness({"refresh_status": "healthy"})


def test_country_outside_the_catalog_fits_no_report():
    cat.reset_catalog()
    asset = next(a for a in cat.CATALOG["assets"] if a["market_scope"] == "Global" and a["product_scope"] == "Kerendia")
    known = {"measures": ["net_sales"], "dimensions": [], "filters": {"product": ["Kerendia"], "market": ["JP"]}}
    assert scope_match(known, asset, cat.CATALOG)[0] == 1.0  # Global covers a market it holds data for
    unknown = {"measures": ["net_sales"], "dimensions": [], "filters": {"product": ["Kerendia"]}, "other_markets": ["Vietnam"]}
    assert scope_match(unknown, asset, cat.CATALOG)[0] == 0.5


def test_places():
    from app.geo import other_markets, same_place, split_other_markets

    assert other_markets("sales in vietnam and South Sudan") == ["South Sudan", "Vietnam"]
    assert other_markets("Net sales in Germany, Indiana") == []
    assert split_other_markets("report", ["Vietnam", "churn"]) == (["Vietnam"], ["churn"])
    assert same_place("in Germany", "across EMEA") and same_place("Show sales", "in Japan")
    assert not same_place("in Vietnam", "in EMEA and North America") and not same_place("in Japan", "in Mexico")
