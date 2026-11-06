import json

import pytest
from fastapi.testclient import TestClient

from app import actions as act
from app.catalog import CATALOG, preset_by_id, reset_catalog
from app.decision import data_availability, decide, rank_candidates
from app.main import app


@pytest.fixture(autouse=True)
def _catalog():
    reset_catalog()


def plan(preset_id):
    p = preset_by_id(preset_id)
    intent = {"measures": p["measures"], "dimensions": p["dimensions"], "grain": p["grain"], "decision": p["decision"],
              "unmatched_terms": p.get("requested_terms", []), "preset_id": preset_id}
    avail = data_availability(intent, CATALOG)
    d = decide(rank_candidates(intent, CATALOG["assets"]), avail["available"]).to_dict()
    d["availability"] = avail
    return intent, d


def test_late_deliveries_proposals():
    intent, d = plan("sc_late_deliveries")
    props = act.propose(intent, d, [])
    titles = {p["title"]: p for p in props}
    biz = [p for p in props if p["kind"] == "business"]
    assert len(biz) == 1 and biz[0]["verify"]["metric_id"] == "late_shipments"
    assert biz[0]["verify"]["direction"] == "decrease"
    assert "Assign a new owner for Logistics Weekly KPI (copy)" in titles
    assert any(t.startswith("Merge Logistics Weekly KPI (copy) into Delivery Performance") for t in titles)


def test_maintenance_and_not_feasible_proposals():
    _, d = plan("qa_release_blockers")
    assert any(p["key"] == "maint:refresh:rpt_batch_release" for p in act.propose(plan("qa_release_blockers")[0], d, []))
    intent, d = plan("prod_shift_start")
    assert any(p["title"] == "Fix failing quality tests in mfg.line_events_fact" for p in act.propose(intent, d, []))
    intent, d = plan("it_system_health")
    props = act.propose(intent, d, [])
    assert [p["kind"] for p in props] == ["maintenance"] and "system uptime" in props[0]["title"]


def test_existing_open_action_is_linked():
    intent, d = plan("sc_late_deliveries")
    first = act.propose(intent, d, [])[0]
    existing = [{"_id": "act_1", "key": first["key"], "status": "in_progress"}]
    assert act.propose(intent, d, existing)[0]["existing_action_id"] == "act_1"


def test_status_rules_and_done_vs_verified():
    a = act.create({"title": "Investigate late shipments", "owner": "M. Laine", "kind": "business",
                    "verify": act.verify_target("late_shipments")}, by="You")
    with pytest.raises(ValueError, match="blocking"):
        act.apply_update(a, {"status": "blocked"}, "M. Laine")
    with pytest.raises(ValueError, match="Describe"):
        act.apply_update(a, {"status": "done"}, "M. Laine")
    with pytest.raises(ValueError, match="Cannot move"):
        act.apply_update(a, {"status": "verified"}, "M. Laine")
    a = act.apply_update(a, {"status": "in_progress"}, "M. Laine")
    a = act.apply_update(a, {"outcome": "Escalated with two carriers", "status": "done"}, "M. Laine")
    assert a["status"] == "done" and a["verify"]["result"] is None   # done is not verified
    with pytest.raises(ValueError, match="improved"):
        act.apply_update(a, {"status": "verified"}, "S. Virtanen")
    a = act.apply_update(a, {"status": "verified", "verification": {"result": "improved", "note": "Down from 9 to 3"}}, "S. Virtanen")
    assert a["verify"]["result"] == "improved" and a["verify"]["checked_by"] == "S. Virtanen"
    assert [h["to"] for h in a["history"] if h["change"] in ("created", "status")] == ["open", "in_progress", "done", "verified"]


def sse(resp):
    return [json.loads(l[6:]) for b in resp.text.split("\n\n") for l in b.splitlines() if l.startswith("data: ")]


def test_actions_api_flow():
    with TestClient(app) as c:
        start = c.get("/api/actions").json()
        assert start["summary"]["active"] >= 3 and all(a["sample"] for a in start["items"])
        assert any(a["overdue"] for a in start["items"])

        evs = sse(c.post("/api/chat", json={"preset_id": "sc_stockout_risk"}))
        stage = next(e for e in evs if e["type"] == "stage" and e["stage"] == "actions")
        prop = next(p for p in stage["data"]["proposals"] if p["kind"] == "business")
        conv_id = evs[0]["id"]

        r = c.post("/api/actions", json={**prop, "conversation_id": conv_id, "by": "Planner"})
        assert r.status_code == 201
        action = r.json()
        assert action["run_id"] and action["owner"] == "You (requester)"
        assert c.post("/api/actions", json={**prop}).status_code == 409   # duplicate open action

        bad = c.patch(f"/api/actions/{action['_id']}", json={"status": "verified"})
        assert bad.status_code == 400 and "Cannot move" in bad.json()["detail"]
        r = c.patch(f"/api/actions/{action['_id']}", json={"owner": "P. Koski", "by": "Planner"})
        assert r.json()["owner"] == "P. Koski"
        mine = c.get("/api/actions", params={"owner": "P. Koski"}).json()["items"]
        assert [a["_id"] for a in mine] == [action["_id"]]


def test_sample_actions_link_to_live_proposals():
    samples = act.sample_actions()
    intent, d = plan("sc_late_deliveries")
    props = {p["title"]: p for p in act.propose(intent, d, samples)}
    assert props["Assign a new owner for Logistics Weekly KPI (copy)"]["existing_action_id"]
    intent, d = plan("prod_shift_start")
    tests = next(p for p in act.propose(intent, d, samples) if p["key"] == "maint:tests:line_events_fact")
    assert tests["existing_action_id"]
