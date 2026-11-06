import copy
import io
import json
import zipfile
from dataclasses import replace
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app import catalog as cat
from app.main import app
from app.bindings import rows
from app.decision import rank_candidates
from app.pbip import render_pbip, validate_json_files
from app.settings import settings
from app.store import SQLiteStore
from .helpers import login, sse, stage


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr("app.pipeline.settings", replace(settings, output_dir=tmp_path))
    monkeypatch.setattr("app.main.settings", replace(settings, output_dir=tmp_path))
    cat.reset_catalog()
    with TestClient(app) as c:
        login(c)
        yield c


def request(client, preset="demo_portfolio_sales_units", **extra):
    login(client)
    response = client.post("/api/chat", json={"preset_id": preset, **extra})
    assert response.status_code == 200
    events = sse(response)
    assert not [e for e in events if e["type"] == "error"]
    return events[0]["id"], stage(events, "approval")["data"]["spec_hash"], events


def review(client, cid, spec_hash, **extra):
    login(client, "OWN-022")
    response = client.post("/api/approve", json={"conversation_id": cid, "spec_hash": spec_hash, **extra})
    assert response.status_code == 200, response.text
    events = sse(response)
    assert not [e for e in events if e["type"] == "error"]
    return events


def test_authentication_and_separation_of_review(client, monkeypatch):
    client.headers.pop("Authorization")
    for path in ("/api/catalog", "/api/source", "/api/graph", "/api/agent-runs", "/api/conversations", "/api/audit"):
        assert client.get(path).status_code == 401
    client.headers["Authorization"] = "Bearer fabricated.identity"
    assert client.get("/api/catalog").status_code == 401
    assert client.post("/api/session", json={"actor_id": "OWN-048"}).status_code == 403  # same name, different identity
    cid, sh, _ = request(client)
    assert client.post("/api/approve", json={"conversation_id": cid, "spec_hash": sh}).status_code == 403
    assert client.post("/api/approve", json={"conversation_id": cid, "spec_hash": sh, "approver": "Sofia Rossi"}).status_code == 422
    monkeypatch.setenv("DEMO_MODE", "false")
    assert client.post("/api/session", json={"actor_id": "OWN-022"}).status_code == 503
    assert client.get("/api/source").status_code == 503


def test_exact_version_and_source_required(client):
    cid, sh, _ = request(client)
    login(client, "OWN-022")
    assert client.post("/api/approve", json={"conversation_id": cid, "spec_hash": "old"}).status_code == 409
    cat.CATALOG["models"]["SM-001"]["refresh_status"] = "failed"
    assert client.post("/api/approve", json={"conversation_id": cid, "spec_hash": sh}).status_code == 409
    assert len(cat.CATALOG["assets"]) == 360


def test_superseded_request_and_rejection(client):
    cid, old_hash, _ = request(client)
    _, new_hash, _ = request(client, "demo_nubeqa_sales_units", conversation_id=cid, expected_revision=1)
    assert old_hash != new_hash
    login(client, "OWN-022")
    assert client.post("/api/approve", json={"conversation_id": cid, "spec_hash": old_hash}).status_code == 409
    review(client, cid, new_hash, approved=False)
    assert len(cat.CATALOG["assets"]) == 360
    assert client.get(f"/api/conversations/{cid}").json()["request_state"] == "rejected"
    conflicting = sse(client.post("/api/approve", json={"conversation_id": cid, "spec_hash": new_hash, "approved": True}))
    assert any(e["type"] == "error" for e in conflicting)


def test_two_generated_requests_repeatability_bindings_and_download(client, tmp_path):
    packages = []
    for preset in ("demo_portfolio_sales_units", "demo_nubeqa_sales_units"):
        cid, sh, events = request(client, preset)
        assert stage(events, "decision")["data"]["decision"] == "new_build"
        spec = stage(events, "spec")["data"]
        spec.pop("agent")
        result = review(client, cid, sh)
        package = stage(result, "render")["data"]
        packages.append(package)
        assert all(c["passed"] for c in package["validation"]["schema_checks"])
        assert package["validation"]["layers"]["power_bi_rendering"] == "not_run"
        assert package["validation"]["layers"]["publication"] == "not_run"
        repeated = render_pbip(spec, tmp_path / "repeat", "same-spec")
        assert repeated["validation"]["artifact_hashes"] == package["validation"]["artifact_hashes"]
        response = client.get(package["download_url"])
        assert response.status_code == 200
        archive = zipfile.ZipFile(io.BytesIO(response.content))
        files = {n: archive.read(n).decode() for n in archive.namelist()}
        assert all(c["passed"] for c in validate_json_files(files))
        model = json.loads(files["BayerDemo.SemanticModel/model.bim"])
        table = model["model"]["tables"][0]
        assert {m["name"] for m in table["measures"]} == {"net_sales", "units_shipped"}
        assert "SUM('DemoFacts'[NetSalesEUR])" == table["measures"][0]["expression"]
        for name, text in files.items():
            if name.endswith("/visual.json"):
                assert "DemoFacts" in text and "queryState" in text
        facts = cat.SHEETS["product_market_monthly"]
        if "nubeqa" in preset:
            facts = [r for r in facts if r["product_id"] == "P-NUB"]
            assert any("Nubeqa" in text and "scope_product" in text for name, text in files.items() if name.endswith("/report.json"))
        expected = package["validation"]["expected_values"]
        independent_eur = sum(Decimal(str(r["net_sales_m_eur_syn"])) * 1000000 for r in facts)
        assert Decimal(str(expected["totals"]["net_sales"])) == independent_eur
        assert expected["totals"]["units_shipped"] == sum(r["units_shipped_syn"] for r in facts)
        assert expected["rows"] == len(facts)
        # Identical review retries reuse exactly the persisted results.
        assert stage(review(client, cid, sh), "render")["data"] == package
        entry = stage(result, "register")["data"]
        assert not entry["certified"] and entry["endorsement"] == "none"
        assert entry["artifact_state"] == "validation_pending"
        assert entry["id"] not in {c.asset_id for c in rank_candidates({"measures": ["net_sales"], "filters": {}}, cat.CATALOG)}
    assert len(cat.CATALOG["assets"]) == 362
    assert packages[0]["validation"]["expected_values"] != packages[1]["validation"]["expected_values"]
    # A distinct equivalent request discovers the existing pending package, without claiming trusted reuse.
    cid, sh, _ = request(client)
    repeated = review(client, cid, sh)
    assert stage(repeated, "render")["data"]["download_url"] == packages[0]["download_url"]
    assert len(cat.CATALOG["assets"]) == 362
    graph = client.get("/api/graph").json()
    assert any(e["s"] == "RUN-" + cid and e["t"].startswith("GEN-") for e in graph["edges"])


def test_submission_retry_and_conflicting_edit(client):
    cid, sh, _ = request(client, submission_id="request-key-123")
    same, same_hash, _ = request(client, submission_id="request-key-123")
    assert (cid, sh) == (same, same_hash)
    response = sse(client.post("/api/chat", json={"preset_id": "demo_nubeqa_sales_units", "submission_id": "request-key-123"}))
    assert any(e["type"] == "error" for e in response)
    request(client, "demo_nubeqa_sales_units", conversation_id=cid, expected_revision=1)
    stale = sse(client.post("/api/chat", json={"conversation_id": cid, "expected_revision": 1, "message": "Old edit"}))
    assert any(e["type"] == "error" for e in stale)
    assert client.get(f"/api/conversations/{cid}").json()["revision"] == 2


def test_generation_failure_is_recorded_without_trust(client, monkeypatch):
    cid, sh, _ = request(client)
    def fail(*args):
        raise ValueError("test target error")
    monkeypatch.setattr("app.pipeline.render_pbip", fail)
    login(client, "OWN-022")
    body = {"conversation_id": cid, "spec_hash": sh}
    assert any(e["type"] == "error" for e in sse(client.post("/api/approve", json=body)))
    assert client.get(f"/api/conversations/{cid}").json()["request_state"] == "generation_failed"
    assert len(cat.CATALOG["assets"]) == 360
    assert any(e["event"] == "generation_failed" for e in client.get("/api/audit").json())


def test_action_identity_and_stale_updates(client):
    created = client.post("/api/actions", json={"title": "Confirm model mappings", "owner_id": "OWN-022", "by": "Forged Name"})
    assert created.status_code == 201
    action = created.json()
    assert action["created_by"] == "OWN-008" and action["owner_id"] == "OWN-022"
    assert client.patch("/api/actions/" + action["_id"], json={"version": 1, "status": "in_progress"}).status_code == 200
    assert client.patch("/api/actions/" + action["_id"], json={"version": 1, "status": "dismissed"}).status_code == 409
    inactive = next(oid for oid, o in cat.CATALOG["owners"].items() if o["status"] != "active")
    assert client.post("/api/actions", json={"title": "Invalid ownership", "owner_id": inactive}).status_code == 400
    assert client.post("/api/actions", json={"title": "Name is not identity", "owner": "Sofia Rossi"}).status_code == 422


async def test_sqlite_restart_and_immutable_history(tmp_path):
    path = tmp_path / "state.sqlite"
    first = SQLiteStore(path)
    await cat.init(first)
    await first.save({"_id": "request", "title": "Durable", "revision": 2})
    await first.save_artifact("audit", {"_id": "event", "event": "plan_approved", "actor_id": "OWN-022"})
    await first.save_artifact("outputs", {"_id": "output", "state": "validation_pending"})
    await first.save_artifact("specs", {"_id": "spec", "status": "approved", "version": 2})
    first.connection.close()
    second = SQLiteStore(path)
    await cat.init(second)
    assert (await second.get("request"))["revision"] == 2
    assert (await second.get_artifact("outputs", "output"))["state"] == "validation_pending"
    assert (await second.get_artifact("specs", "spec"))["status"] == "approved"
    assert await second.count_artifacts("actions") == 4
    with pytest.raises(ValueError, match="immutable"):
        await second.save_artifact("audit", {"_id": "event", "event": "forged"})
    with pytest.raises(ValueError, match="immutable"):
        await second.update_artifact("audit", "event", {"actor_id": "attacker"})
    second.connection.close()


def test_bad_schema_and_unsupported_period_fail_closed(client):
    checks = validate_json_files({"bad.pbip": json.dumps({"$schema": "https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/1.0.0/schema.json", "version": 100})})
    assert checks and not checks[0]["passed"]
    result = sse(client.post("/api/chat", json={"message": "Build daily net sales for all products and all markets in 2025"}))
    assert stage(result, "decision")["data"]["decision"] == "not_feasible"
    assert not stage(result, "deliver")
