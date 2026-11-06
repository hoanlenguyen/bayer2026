import pytest
from fastapi.testclient import TestClient

from app import catalog as cat
from app.main import app

from .helpers import sse, stage, login


@pytest.fixture()
def client():
    cat.reset_catalog()
    with TestClient(app) as c:
        login(c)
        yield c


def test_datapack_endpoints(client):
    s = client.get("/api/datapack").json()
    assert s["assets"] == 360 and s["sheets"]["governance_signals"] == 410
    assert len(client.get("/api/requests").json()) == 150


def test_reuse_flow_with_preview(client):
    evs = sse(client.post("/api/chat", json={"preset_id": "demo_reuse_brazil"}))
    d = stage(evs, "decision")["data"]
    assert d["decision"] == "reuse" and d["preview"]["rows"]
    assert stage(evs, "deliver")


@pytest.mark.parametrize("preset_id", ["req_finance_gtn", "req_migrate_xarelto", "scn_repair_xarelto_mx"])
def test_review_does_not_execute_unsupported_work(client, preset_id):
    before = cat.seed_catalog()
    evs = sse(client.post("/api/chat", json={"preset_id": preset_id}))
    approval = stage(evs, "approval")
    assert approval["status"] == "waiting"
    login(client, "OWN-022")
    evs = sse(client.post("/api/approve", json={"conversation_id": evs[0]["id"], "spec_hash": approval["data"]["spec_hash"]}))
    output = stage(evs, "render")["data"]
    assert output["artifact_state"] == "execution_blocked" and not output["files"]
    assert not stage(evs, "register")
    assert cat.CATALOG == before  # No manufactured ownership, refresh or endorsement.


def test_free_text_grill_me(client):
    evs = sse(client.post("/api/chat", json={"message": "I need net sales and gross-to-net"}))
    conv = evs[0]["id"]
    assert next(e for e in evs if e["type"] == "message")["kind"] == "question"
    evs = sse(client.post("/api/chat", json={"conversation_id": conv, "expected_revision": 1, "message": "All products, all markets"}))
    evs += sse(client.post("/api/chat", json={"conversation_id": conv, "expected_revision": 1, "message": "Monthly performance review"}))
    assert stage(evs, "decision")["data"]["decision"] in ("new_build", "consolidate", "reuse")


def test_not_feasible(client):
    evs = sse(client.post("/api/chat", json={"preset_id": "scn_out_of_scope"}))
    assert stage(evs, "decision")["data"]["decision"] == "not_feasible"
