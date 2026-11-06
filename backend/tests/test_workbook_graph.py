import copy
import hashlib
from fastapi.testclient import TestClient
from app import catalog as cat
from app.datapack import workbook_path
from app.graph import build_graph
from app.main import app
from app.workbook_source import metadata, records, snapshot


def test_complete_source_with_exact_excel_rows():
    assert metadata()["sheet_count"] == 24
    assert metadata()["sha256"] == hashlib.sha256(workbook_path().read_bytes()).hexdigest()
    assert len(records("START_HERE")) == 12
    assert len(records("Package_Overview")) == 21
    assert len(records("Asset_Usage")) == 3600
    assert len(records("Business_Requests")) == 150
    for name in snapshot()["sheets"]:
        rows = records(name)
        start = 1 if snapshot()["sheets"][name]["layout"] == "document" else 2
        assert [r["_source"]["row"] for r in rows] == list(range(start, start + len(rows)))
    assert records("Analytics_Assets")[0]["synthetic_record"] is True


def test_directed_lineage_and_unapproved_candidates_keep_every_source_row():
    cat.reset_catalog()
    g = build_graph()
    ids = {n["id"] for n in g["entities"]}
    assert len(ids) == len(g["entities"]) == 787
    assert all(e["s"] in ids and e["t"] in ids for e in g["edges"])
    supplied = [e for e in g["edges"] if e["basis"] == "lineage"]
    for r in records("Lineage_Edges"):
        assert any(e["s"] == r["source_id"] and e["t"] == r["target_id"] and r["_source"] in e["sources"] for e in supplied)
    assert sum(len(e["sources"]) for e in supplied) == 438
    candidates = [e for e in g["edges"] if e["basis"] == "candidate"]
    assert len(candidates) == 94 and all(e["rel"] == "candidate_target" for e in candidates)
    assert not any(e["rel"] in ("equivalent_to", "duplicate_of") for e in g["edges"])


def test_duplicate_names_and_usage_keep_their_meaning():
    cat.reset_catalog()
    nodes = {n["id"]: n for n in build_graph()["entities"]}
    assert nodes["OWN-022"]["name"] == nodes["OWN-048"]["name"] == "Sofia Rossi"
    assert nodes["SM-001"]["trust"] is None
    a = nodes["AST-0001"]
    assert a["views"] == sum(r["views"] for r in records("Asset_Usage") if r["asset_id"] == a["id"])
    assert a["usage_period"] == "January–October 2026"
    assert "Computed" in a["props"]["Governance score basis"]
    assert a["props"]["Access"] == "Not established by workbook"


def test_current_catalog_changes_and_new_assets_remain_visible():
    cat.reset_catalog()
    try:
        a = cat.CATALOG["assets"][0]
        a["owner_id"] = "OWN-022"
        cat.CATALOG["assets"].append({**copy.deepcopy(a), "id": "NEW-X", "name": "New session report"})
        g = build_graph()
        assert "NEW-X" in {n["id"] for n in g["entities"]}
        assert any(e["s"] == "OWN-022" and e["t"] == a["id"] and e["basis"] == "runtime" for e in g["edges"])
        assert not any(e["s"] == "OWN-019" and e["t"] == a["id"] and e["rel"] == "owns" for e in g["edges"])
        assert any(e["t"] == "NEW-X" and e["basis"] == "runtime" for e in g["edges"])
    finally:
        cat.reset_catalog()


def test_source_api_pagination_and_existing_action_links():
    with TestClient(app) as client:
        assert client.get("/api/source").json()["sheet_count"] == 24
        assert client.get("/api/source/Analytics_Assets?row=2").json()["rows"][0]["asset_id"] == "AST-0001"
        assert "columns" in client.get("/api/source/Analytics_Assets?row=1").json()["rows"][0]
        page = client.get("/api/source/Asset_Usage?offset=3550&limit=50").json()
        assert page["total"] == 3600 and page["rows"][-1]["_source"]["row"] == 3601
        assert client.get("/api/source/Owners?limit=201").status_code == 400
        assert client.get("/api/source/missing").status_code == 404
        assert client.get("/api/source/Owners?row=900").status_code == 404
        a = client.post("/api/actions", json={"title": "Inspect original lineage", "owner": "Sofia Rossi", "asset_id": "AST-0001"}).json()
        g = client.get("/api/graph").json()
        assert any(e["s"] == a["_id"] and e["t"] == "AST-0001" and e["basis"] == "runtime" for e in g["edges"])
        assert not any(e["t"] == a["_id"] and e["rel"] == "owns" for e in g["edges"])
