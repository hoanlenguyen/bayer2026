import pytest
from fastapi.testclient import TestClient

from app import catalog as cat
from app.main import app

from .helpers import sse, stage


@pytest.fixture()
def client():
    cat.reset_catalog()
    with TestClient(app) as c:
        yield c


def test_datapack_endpoints(client):
    s = client.get("/api/datapack").json()
    assert s["assets"] == 360 and s["sheets"]["governance_signals"] == 410
    assert len(client.get("/api/requests").json()) == 150


def test_reuse_flow_with_preview(client):
    evs = sse(client.post("/api/chat", json={"preset_id": "scn_reuse_eylea_jp"}))
    d = stage(evs, "decision")["data"]
    assert d["decision"] == "reuse" and d["preview"]["rows"]
    assert stage(evs, "deliver")


@pytest.mark.parametrize("preset_id", ["req_finance_gtn", "req_migrate_xarelto", "scn_repair_xarelto_mx"])
def test_build_flows_approve_then_reuse(client, preset_id):
    evs = sse(client.post("/api/chat", json={"preset_id": preset_id}))
    assert stage(evs, "approval")["status"] == "waiting"
    evs = sse(client.post("/api/approve", json={"conversation_id": evs[0]["id"], "approver": "Data steward"}))
    assert stage(evs, "register")
    files = stage(evs, "render")["data"]["files"]
    assert (files == []) == (preset_id.startswith("scn_repair"))
    if files:
        assert any(f["path"].endswith("definition.pbir") for f in files)
    evs = sse(client.post("/api/chat", json={"preset_id": preset_id}))
    assert stage(evs, "decision")["data"]["decision"] == "reuse"


def test_free_text_grill_me(client):
    evs = sse(client.post("/api/chat", json={"message": "I need net sales and gross-to-net"}))
    conv = evs[0]["id"]
    assert next(e for e in evs if e["type"] == "message")["kind"] == "question"
    evs = sse(client.post("/api/chat", json={"conversation_id": conv, "message": "All products, all markets"}))
    evs += sse(client.post("/api/chat", json={"conversation_id": conv, "message": "Monthly performance review"}))
    assert stage(evs, "decision")["data"]["decision"] in ("new_build", "consolidate", "reuse")


def test_not_feasible(client):
    evs = sse(client.post("/api/chat", json={"preset_id": "scn_out_of_scope"}))
    assert stage(evs, "decision")["data"]["decision"] == "not_feasible"
