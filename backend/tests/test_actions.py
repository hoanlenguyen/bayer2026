import pytest
from fastapi.testclient import TestClient

from app import actions as act
from app import catalog as cat
from app.main import app

from .helpers import plan, sse, stage


@pytest.fixture(autouse=True)
def _catalog():
    cat.reset_catalog()


def test_new_build_proposals():
    intent, d = plan("req_finance_gtn")
    props = act.propose(intent, d, [])
    biz = [p for p in props if p["kind"] == "business"]
    assert len(biz) == 1 and biz[0]["verify"]["metric_id"] == "net_sales" and biz[0]["verify"]["direction"] == "increase"
    assert any(p["key"].startswith("maint:retire:") for p in props)


def test_migration_and_out_of_scope_proposals():
    intent, d = plan("req_migrate_xarelto")
    assert sum(1 for p in act.propose(intent, d, []) if p["key"].startswith("maint:retire:")) >= 5
    intent, d = plan("scn_out_of_scope")
    assert act.propose(intent, d, []) == []   # patient-level data is out of scope, not a data gap


def test_status_rules_and_done_vs_verified():
    a = act.create({"title": "Review Nubeqa forecast", "owner": "A", "verify": act.verify_target("forecast_variance")}, by="You")
    assert a["verify"]["direction"] == "decrease"
    with pytest.raises(ValueError, match="blocking"):
        act.apply_update(a, {"status": "blocked"}, "A")
    with pytest.raises(ValueError, match="Cannot move"):
        act.apply_update(a, {"status": "verified"}, "A")
    a = act.apply_update(a, {"outcome": "Reviewed with DE team", "status": "done"}, "A")
    assert a["verify"]["result"] is None
    a = act.apply_update(a, {"status": "verified", "verification": {"result": "improved", "note": "11.8% to 3%"}}, "B")
    assert a["verify"]["checked_by"] == "B"


def test_samples_link_to_live_proposals():
    samples = act.sample_actions()
    owner_key = next(s["key"] for s in samples if s["key"].startswith("maint:owner:"))
    assert all(s["sample"] for s in samples) and owner_key


def test_actions_api_flow():
    with TestClient(app) as c:
        start = c.get("/api/actions").json()
        assert start["summary"]["active"] >= 3 and any(a["overdue"] for a in start["items"])
        evs = sse(c.post("/api/chat", json={"preset_id": "req_finance_gtn"}))
        prop = next(p for p in stage(evs, "actions")["data"]["proposals"] if p["kind"] == "business")
        r = c.post("/api/actions", json={**prop, "conversation_id": evs[0]["id"], "by": "Planner"})
        assert r.status_code == 201 and r.json()["allowed"]
        assert c.post("/api/actions", json=prop).status_code == 409
        bad = c.patch(f"/api/actions/{r.json()['_id']}", json={"status": "verified"})
        assert bad.status_code == 400
