from datetime import date

import pytest

from app.catalog import CATALOG, preset_by_id
from app.decision import (Decision, coverage, data_availability, decide, freshness, governance,
                          rank_candidates)

TODAY = date(2026, 11, 6)


def intent_for(preset_id: str) -> dict:
    p = preset_by_id(preset_id)
    return {"measures": p["measures"], "dimensions": p["dimensions"], "grain": p["grain"],
            "unmatched_terms": p.get("requested_terms", [])}


def run(preset_id: str):
    intent = intent_for(preset_id)
    cands = rank_candidates(intent, CATALOG["assets"], TODAY)
    return decide(cands, data_availability(intent, CATALOG)["available"])


@pytest.mark.parametrize("preset_id, expected, asset", [
    ("prod_shift_start", Decision.REUSE, "rpt_daily_production"),
    ("fin_month_end", Decision.REUSE, "rpt_plant_cost"),
    ("sc_late_deliveries", Decision.EXTEND, "rpt_delivery_perf"),
    ("qa_release_blockers", Decision.EXTEND, "rpt_batch_release"),
    ("hr_weekly_staffing", Decision.EXTEND, "rpt_hr_monthly"),
    ("sc_stockout_risk", Decision.CREATE, None),
    ("it_system_health", Decision.NOT_FEASIBLE, None),
])
def test_preset_decisions(preset_id, expected, asset):
    result = run(preset_id)
    assert result.decision == expected
    if asset:
        assert result.candidate.asset_id == asset


def test_stale_but_complete_asset_is_maintenance_extend():
    result = run("qa_release_blockers")
    assert result.change_type == "maintenance"


def test_conflicting_copy_is_flagged_not_reused():
    result = run("sc_late_deliveries")
    flagged = {f["asset_id"] for f in result.flags}
    assert "rpt_logistics_weekly" in flagged


def test_freshness_curve():
    assert freshness(10, "day") == 1.0
    assert freshness(48, "day") == 0.5
    assert freshness(72, "day") == 0.0


def test_coverage_weights():
    asset = {"measures": ["a"], "dimensions": ["x"], "grain": "day"}
    value, det = coverage({"measures": ["a", "b"], "dimensions": ["x"], "grain": "day"}, asset)
    assert value == pytest.approx(0.5 * 0.5 + 0.3 + 0.2)
    assert det["measures_missing"] == ["b"]


def test_governance_score_full_and_empty():
    full = {"conflicts": {}, "certified": True, "owner_status": "active", "tests_passing": True,
            "last_review": "2026-10-01", "documented": True}
    assert governance(full, TODAY)[0] == pytest.approx(1.0)
    empty = {"conflicts": {"m": "x"}, "certified": False, "owner_status": "left", "tests_passing": False,
             "last_review": "2020-01-01", "documented": False}
    assert governance(empty, TODAY)[0] == 0.0
