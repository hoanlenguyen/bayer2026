from copy import deepcopy

from fastapi.testclient import TestClient
import pytest

from app import catalog
from app.main import app
from app.pipeline import analyse
from app.request_handoff import _receipt
from .helpers import sse


def run_url(client, preset, conversation=None):
    events = sse(client.post("/api/chat", json={"preset_id": preset, "conversation_id": conversation}))
    cid = events[0]["id"]
    run = client.get("/api/conversations/" + cid).json()["runs"][-1]
    return cid, run, f"/api/conversations/{cid}/runs/{run['id']}/handoff"


def test_historical_request_and_assignment_are_bound_to_the_saved_run():
    with TestClient(app) as c:
        cid, first, url = run_url(c, "req_migrate_xarelto")
        receipt = c.get(url).json()
        assert receipt["verdict"] == "migrate" and receipt["run_id"] == first["id"]
        assert "Tableau" in receipt["question"] and receipt["evidence"] and receipt["candidates"]
        asset_id = receipt["candidate"]["asset_id"]
        assert any(r["id"] == asset_id and r["sheet"] == "Analytics_Assets" for r in receipt["source_refs"])
        assert "lineage" in {e["stage"] for e in receipt["evidence"]} and receipt["preview"] is None
        _, second, second_url = run_url(c, "req_finance_gtn", cid)
        assert second["id"] != first["id"] and c.get(second_url).json()["verdict"] == "new_build"
        assert c.get(url).json()["question"] == receipt["question"]

        body = {"owner_id": "OWN-017", "due_date": "2026-11-15"}
        assert c.post(url + "/actions", json={**body, "asset_id": "invented"}).status_code == 422
        assert c.post(url + "/actions", json={**body, "owner_id": "OWN-999"}).status_code == 422
        action = c.post(url + "/actions", json=body).json()
        assert action["owner"] == "Leo Weber" and action["created_by_id"] == "OWN-008"
        assert action["asset_id"] == asset_id and action["run_id"] == first["id"] and action["conversation_id"] == cid
        assert c.post(url + "/actions", json=body).json() == action
        assert c.post(url + "/actions", json={**body, "owner_id": "OWN-008"}).status_code == 409
        assert c.get(second_url).json()["action"] is None
        assert c.get("/api/actions/" + action["_id"]).json()["request_snapshot"]["source_refs"] == receipt["source_refs"]
        done = c.patch(url + "/actions", json={"status": "done", "outcome": "Reviewed source and destination with the owner."}).json()
        assert done["history"][-1]["by_id"] == "OWN-008" and done["status"] == "done"
        assert done["request_snapshot"] == action["request_snapshot"]
        assert c.patch(url + "/actions", json={"status": "done", "outcome": "Overwrite."}).status_code == 409
        assert c.patch("/api/actions/" + action["_id"], json={"owner": "Someone else"}).status_code == 409
        assert c.get(url).json()["action"] == done
        built = c.post(second_url + "/actions", json=body).json()
        assert built["asset_id"] is None and built["request_snapshot"]["verdict"] == "new_build"
        assert c.get("/api/conversations/missing/runs/" + first["id"] + "/handoff").status_code == 404


def test_scoped_reuse_preview_matches_the_saved_values_and_source():
    catalog.reset_catalog()
    intent = {"measures": ["inventory_coverage", "on_time_in_full"], "dimensions": ["month"], "grain": "month",
              "filters": {"product": ["Lynkuet"], "market": ["ES"]}}
    plan = analyse(intent)
    run = {"id": "historical", "events": [{"type": "stage", "stage": "intent", "status": "done", "data": intent},
                                           {"type": "stage", "stage": "decision", "status": "done", "data": plan["decision"]}]}
    handoff = _receipt("c", run, "Review Lynkuet supply in Spain")
    assert handoff["verdict"] == "reuse" and handoff["candidate"]["asset_id"] == "AST-0286"
    preview = handoff["preview"]
    assert preview["source_rows"] == [600, 601] and preview["fields"] == ["inventory_weeks_syn", "otif_pct_syn"]
    assert preview["rows"][0]["values"] == {"inventory_coverage": 8.9, "on_time_in_full": 98.5}
    assert handoff["employee_report"] is None
    stale = deepcopy(run)
    stale["events"][1]["data"]["preview"]["rows"][0]["values"]["inventory_coverage"] = 100
    assert _receipt("c", stale, "historic")["preview"] is None
    stale = deepcopy(run)
    stale["events"][0]["data"]["dimensions"] = ["quarter"]
    assert _receipt("c", stale, "unsupported breakdown")["preview"] is None


def test_incomplete_ask_is_not_assignable_and_unavailable_request_only_creates_assessment():
    with TestClient(app) as c:
        events = sse(c.post("/api/chat", json={"message": "Show monthly inventory coverage and OTIF for Lynkuet in Spain."}))
        cid = events[0]["id"]
        run = c.get("/api/conversations/" + cid).json()["runs"][-1]
        url = f"/api/conversations/{cid}/runs/{run['id']}/handoff"
        assert c.get(url).status_code == 409
        body = {"owner_id": "OWN-008", "due_date": "2026-11-15"}
        assert c.post(url + "/actions", json=body).status_code == 409
        _, _, blocked = run_url(c, "scn_out_of_scope")
        result = c.post(blocked + "/actions", json=body).json()
        assert result["asset_id"] is None and result["request_snapshot"]["verdict"] == "not_feasible"
        assert result["request_snapshot"]["preview"] is None and result["title"] == "Review the data gap"


def test_stale_high_scoring_reuse_remains_historical_and_creates_only_review_work():
    with TestClient(app) as c:
        cid, run, url = run_url(c, "scn_reuse_eylea_jp")
        conv = c.get("/api/conversations/" + cid).json()
        historical = next(e["data"] for e in conv["runs"][-1]["events"] if e.get("stage") == "decision" and e.get("status") == "done")
        # Older Ask versions recommended AST-0079 before checking the model's actual product scope.
        historical.update(decision="reuse", reason="Reuse passed the earlier checks.", change_type=None)
        historical["candidate"].update(gates_failed=[], scope_evidence={}, gates_pass=True, coverage=1)
        c.portal.call(app.state.pipeline.store.save, conv)
        view = c.get(url).json()
        assert view["verdict"] == "reuse" and view["handoff_verdict"] == "review" and view["preview"] is None
        assert {"Eylea", "SM-040"}.issubset(set(view["current_review"]["reason"].replace(",", "").split()))
        saved = c.post(url + "/actions", json={"owner_id": "OWN-008", "due_date": "2026-11-18"}).json()
        assert saved["kind"] == "maintenance" and saved["title"].startswith("Verify the saved reuse recommendation")
        assert saved["request_snapshot"]["reason"] == historical["reason"] and saved["reason"] == view["current_review"]["reason"]


def test_native_employee_report_is_the_target_in_the_run_and_in_the_register():
    with TestClient(app) as c:
        out = sse(c.post("/api/chat", json={"message": "Monthly units shipped for Nubeqa in Germany. Needed today."}))
        cid = out[0]["id"]
        if out[-1].get("state") == "clarifying":
            sse(c.post("/api/chat", json={"conversation_id": cid, "message": "Decide where to act this month"}))
        run = c.get("/api/conversations/" + cid).json()["runs"][-1]
        url = f"/api/conversations/{cid}/runs/{run['id']}/handoff"
        h = c.get(url).json()
        assert h["verdict"] == h["handoff_verdict"] == "reuse" and h["candidate"] is None
        report = h["employee_report"]
        assert report["report_id"] == "BR-SHIPMENTS" and h["suggested_owner_id"] == report["owner_id"]
        assert h["estate_assessment"]["decision"] == "new_build"
        assert [r["row"] for r in h["source_refs"] if r["id"] == "BR-SHIPMENTS"] == [10, 11]
        action = c.post(url + "/actions", json={"owner_id": "OWN-008", "due_date": "2026-11-18"}).json()
        assert (action["asset_id"], action["asset_name"]) == (report["report_id"], report["title"])
        assert action["request_snapshot"]["employee_report"] == report
        linked = c.get("/api/report-register/BR-SHIPMENTS").json()["linked_actions"]
        assert any(a["_id"] == action["_id"] for a in linked)


@pytest.mark.parametrize("clarification", ["Decide where to act this month, using an Excel export.",
                                          "Review supply by week.", "Review supply in 2024 and 2025.",
                                          "Review supply by hospital."])
def test_native_reuse_checks_requirements_added_in_clarification(clarification):
    with TestClient(app) as c:
        opening = "Monthly units shipped for Nubeqa in Germany. Needed today."
        first = sse(c.post("/api/chat", json={"message": opening}))
        cid = first[0]["id"]
        assert first[-1]["state"] == "clarifying"
        final = sse(c.post("/api/chat", json={"conversation_id": cid, "message": clarification}))
        decision = next(e["data"] for e in final if e.get("stage") == "decision" and e.get("status") == "done")
        assert decision["decision"] != "reuse" and not decision.get("employee_report")
