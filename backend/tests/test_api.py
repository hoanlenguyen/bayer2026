import json
import os

os.environ["STAGE_DELAY"] = "0"
os.environ["LLM_PROVIDER"] = "mock"
os.environ["MONGODB_URI"] = ""

import pytest
from fastapi.testclient import TestClient

from app.catalog import reset_catalog
from app.main import app


def events(resp):
    out = []
    for block in resp.text.strip().split("\n\n"):
        data = [l[6:] for l in block.splitlines() if l.startswith("data: ")]
        if data:
            out.append(json.loads(data[0]))
    return out


@pytest.fixture()
def client():
    reset_catalog()
    with TestClient(app) as c:
        yield c


def stage_status(evs, stage):
    return [e["status"] for e in evs if e["type"] == "stage" and e["stage"] == stage]


def test_preset_reuse_flow(client):
    evs = events(client.post("/api/chat", json={"preset_id": "prod_shift_start"}))
    assert any(e["type"] == "message" and e.get("kind") == "question" for e in evs)
    conv = evs[0]["id"]
    evs = events(client.post("/api/chat", json={"conversation_id": conv, "message": "All lines"}))
    decision = next(e for e in evs if e["type"] == "stage" and e["stage"] == "decision")
    assert decision["data"]["decision"] == "reuse"
    assert stage_status(evs, "deliver") == ["done"]


def test_create_flow_with_approval_and_reuse_after(client):
    evs = events(client.post("/api/chat", json={"preset_id": "sc_stockout_risk"}))
    conv = evs[0]["id"]
    assert stage_status(evs, "approval") == ["waiting"]
    evs = events(client.post("/api/approve", json={"conversation_id": conv, "approver": "Data steward"}))
    render = next(e for e in evs if e["type"] == "stage" and e["stage"] == "render" and e["status"] == "done")
    assert any(f["path"].endswith(".pbip") for f in render["data"]["files"])
    assert stage_status(evs, "register") == ["done"]
    # Same request again is now answered by reuse.
    evs = events(client.post("/api/chat", json={"preset_id": "sc_stockout_risk"}))
    decision = next(e for e in evs if e["type"] == "stage" and e["stage"] == "decision")
    assert decision["data"]["decision"] == "reuse"


def test_free_text_grill_me(client):
    evs = events(client.post("/api/chat", json={"message": "I need a late deliveries dashboard"}))
    q = next(e for e in evs if e["type"] == "message")
    assert q["kind"] == "question"
    conv = evs[0]["id"]
    evs = events(client.post("/api/chat", json={"conversation_id": conv, "message": "Act on today's issues"}))
    evs += events(client.post("/api/chat", json={"conversation_id": conv, "message": "By carrier and priority"}))
    decision = next(e for e in evs if e["type"] == "stage" and e["stage"] == "decision")
    assert decision["data"]["decision"] == "extend"


def test_not_feasible(client):
    evs = events(client.post("/api/chat", json={"preset_id": "it_system_health"}))
    decision = next(e for e in evs if e["type"] == "stage" and e["stage"] == "decision")
    assert decision["data"]["decision"] == "not_feasible"
