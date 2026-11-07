import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.report_register import _append, _events, _linked_actions, published_revisions
from app.store import MongoStore
from fastapi import HTTPException
from .fakes import AsyncMockDB

BASE = "/api/report-register"


def test_register_usage_scope_and_source_evidence():
    with TestClient(app) as client:
        rows = client.get(BASE).json()["reports"]
        assert len([r for r in rows if r["origin"] == "Estate"]) == 360
        assert len([r for r in rows if r["origin"] == "Employee"]) == 3
        report = client.get(f"{BASE}/AST-0009").json()
        assert (report["owner"]["name"], report["owner"]["status"]) == ("Felix Andersson", "inactive")
        assert (report["views"], report["last_use_month"], report["modified"]) == (47, "2026-10", "2026-10-13")
        assert "Ownership" in report["issues"] and "Retirement review" in report["issues"]
        mismatch = client.get(f"{BASE}/AST-0079").json()
        assert "Product scope mismatch" in mismatch["issues"]
        assert (mismatch["product"], mismatch["model_product"]) == ("Eylea", "Nubeqa")
        assert "Eylea" in mismatch["evidence"]["Analytics_Assets row 80"]
        assert "Nubeqa" in mismatch["evidence"]["Semantic_Models row 41"]
        shared = client.get(f"{BASE}/BR-SHIPMENTS").json()
        assert (shared["product"], shared["market"], shared["teams"]) == ("Nubeqa", "Germany", ["Commercial", "Supply"])
        client.put("/api/briefings/supply/selection", json={"view_ids": ["otif"]}).raise_for_status()
        assert client.get(f"{BASE}/BR-SHIPMENTS").json()["teams"] == ["Commercial"]


def test_independent_review_and_explicit_publication():
    with TestClient(app) as client:
        path = f"{BASE}/BR-SHIPMENTS"
        initial = client.get(path).json()
        owner = initial["owner"]["id"]
        source = "KPI_Catalog row 15"
        def step(kind, actor, seq, **kwargs):
            return client.post(path + "/changes", json={
                "kind": kind, "actor_id": actor, "expected_seq": seq, "note": "Use exact month comparisons",
                "evidence_ref": source, **kwargs,
            })
        def shared():
            return next(v for v in client.get("/api/briefings/supply").json()["views"] if v["id"] == "shipments")
        briefing = client.get("/api/briefings/supply").json()
        action = client.post("/api/briefings/supply/actions", json={
            "version": briefing["version"], "owner_id": "OWN-001", "due_date": "2026-11-30"
        }).json()
        assert action["_id"] in [a["_id"] for a in client.get(path).json()["linked_actions"]]
        assert step("requested", owner, 0).status_code == 403
        assert step("requested", "OWN-001", 0, evidence_ref="invented").status_code == 422
        assert step("requested", "OWN-001", 0).status_code == 201
        assert step("prepared", "OWN-002", 1, display_mode="table").status_code == 403
        proposal = step("prepared", owner, 1, title="German shipment review", display_mode="table")
        assert proposal.status_code == 201
        assert proposal.json()["title"] == initial["title"]
        assert shared()["display_mode"] == "chart"
        assert step("approved", "OWN-002", 2, title="Changed after owner review").status_code == 422
        assert step("approved", owner, 2).status_code == 403
        assert step("approved", "OWN-001", 2).status_code == 403
        assert step("returned", "OWN-002", 2).status_code == 201
        assert step("approved", "OWN-002", 3).status_code == 409
        assert step("prepared", owner, 3, title="Nubeqa shipment comparison", display_mode="table").status_code == 201
        assert step("approved", "OWN-002", 4).status_code == 201
        assert step("approved", "OWN-002", 4).status_code == 409
        assert client.get(BASE + "/titles").json() == {"titles": {"BR-SHIPMENTS": "Nubeqa shipment comparison"}}
        reviewed = shared()
        assert (reviewed["report"], reviewed["display_mode"], reviewed["revision"], reviewed["current"]) == (
            "Nubeqa shipment comparison", "table", 1, 12635)
        register = client.get(path).json()
        linked = register["linked_actions"][0]
        assert (linked["owner_id"], linked["created_by_id"], linked["due_date"]) == ("OWN-001", "OWN-005", "2026-11-30")
        original = next(v for v in linked["briefing_snapshot"]["views"] if v["id"] == "shipments")
        assert (original["report"], original["display_mode"], original["revision"]) == (initial["title"], "chart", 0)
        assert original["evidence"]["rows"] == [10, 11]
        assert not client.get(f"{BASE}/BR-SALES").json()["linked_actions"]
        history = register["history"]
        assert [e["kind"] for e in history] == ["requested", "prepared", "returned", "prepared", "approved"]
        assert len({e["request_id"] for e in history}) == 1
        assert all(e["previous"] == p["_id"] for p, e in zip(history, history[1:]))
        assert "KPI-014" in history[-1]["evidence_value"]


@pytest.mark.asyncio
async def test_event_log_survives_store_recreation_and_rejects_sequence_collision():
    db = AsyncMockDB()
    row = {"_id": "BR-OTIF:3", "report_id": "BR-OTIF", "seq": 3, "kind": "approved",
           "title": "Delivery review", "display_mode": "table", "revision": 1}
    await _append(MongoStore(db), row)
    with pytest.raises(HTTPException) as exc:
        await _append(MongoStore(db), {**row, "title": "Stale change"})
    assert exc.value.status_code == 409
    assert (await _events(MongoStore(db), "BR-OTIF"))[0]["title"] == "Delivery review"
    assert (await published_revisions(MongoStore(db)))["BR-OTIF"]["revision"] == 1

    await db["actions"].insert_many([
        {"_id": "direct", "asset_id": "BR-OTIF", "created_at": "2026-10-01"},
        {"_id": "team", "briefing_snapshot": {"views": [{"report_id": "BR-OTIF"}]}, "created_at": "2026-10-02"},
        {"_id": "unrelated", "asset_id": "BR-SALES", "created_at": "2026-10-03"},
    ])
    assert [a["_id"] for a in await _linked_actions(MongoStore(db), "BR-OTIF")] == ["team", "direct"]
    assert [a["_id"] for a in await _linked_actions(MongoStore(db), "BR-OTIF", limit=1)] == ["team"]
