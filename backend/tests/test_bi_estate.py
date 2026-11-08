"""BI Portfolio: inventory, precise facts, findings, opens, ownership and owner-review cases."""
import pytest
from fastapi.testclient import TestClient

from app import bi_estate
from app.main import app
from app.store import MongoStore
from .fakes import AsyncMockDB
from .test_dashboard_builder import build, seed

STEWARD = {"X-AnalytIQ-Actor": "DEMO-BI-STEWARD"}
NINA = {"X-AnalytIQ-Actor": "OWN-053"}    # owner of AST-0022
SOFIA = {"X-AnalytIQ-Actor": "OWN-022"}   # owner of AST-0089
OTHER = {"X-AnalytIQ-Actor": "OWN-001"}   # a different Nina Garcia, owner of AST-0286 only


def rows(c, **params):
    return c.get("/api/bi-estate", params={"size": 100, **params}).json()


def test_inventory_counts_each_stable_id_once_and_names_its_sources():
    with TestClient(app) as c:
        r = rows(c)
        assert r["total"] == 363 and r["sources"]["origins"] == {"workbook": 360, "app_report": 3, "generated": 0}
        assert r["sources"]["workbook"]["sha256"].startswith("962b3993")
        assert "No Power BI or Tableau tenant is connected" in r["sources"]["note"]
        # Two teams pin BR-SHIPMENTS: still one row.
        assert sum(x["id"] == "BR-SHIPMENTS" for x in rows(c, origin="app_report")["rows"]) == 1
        assert r["counts"]["consolidation"] == {"assets": 4, "pairs": 2}
        assert r["counts"]["definition"]["assets"] == 221


def test_built_dashboard_appears_once_with_its_creator_and_no_owner():
    with TestClient(app) as c:
        path = seed(c, "bi-build")
        built, request = build(c, path)
        did = built["dashboard_id"]
        again = c.post(path + "/build", json=request)  # retry keeps the original record and attribution
        assert again.status_code == 200
        r = rows(c, origin="generated")
        assert r["total"] == 364 and [x["id"] for x in r["rows"]] == [did]
        assert [x["id"] for x in r["recent_from_ask"]] == [did]  # shown first, whatever the sort
        row = r["rows"][0]
        assert row["creator"]["recorded"] and row["creator"]["name"] == "Demo employee"
        assert row["owner"] is None and row["owner_state"] == "absent" and "needs_owner" in row["issues"]
        assert row["data_through"] == "2026-10"
        dash = c.get(f"/api/dashboards/{did}").json()
        assert dash["groups"][0]["points"][-1]["values"] == {"net_sales": 37.58, "units_shipped": 33941, "sales_forecast": 39.2}
        assert dash["source_records"][-1]["row"] == 21


def test_pre_feature_dashboard_without_attribution_stays_readable():
    with TestClient(app) as c:
        store = app.state.pipeline.store
        c.portal.call(store.save_artifact, "dashboards", {"_id": "dash_old", "id": "dash_old", "title": "Older dashboard",
                                                          "created_at": "2026-11-01T09:00:00+00:00", "period": {"end": "2026-10"}})
        row = next(x for x in rows(c, origin="generated")["rows"] if x["id"] == "dash_old")
        assert row["creator"] == {"name": None, "source": "Creator unrecorded: built before attribution was captured", "recorded": False}


def test_opens_are_counted_only_from_rendered_views_and_deduplicated():
    with TestClient(app) as c:
        did = build(c, seed(c, "bi-opens"))[0]["dashboard_id"]
        rows(c), c.get(f"/api/bi-estate/{did}"), c.get(f"/api/dashboards/{did}")  # listing and fetching are not opens
        assert rows(c, origin="generated")["rows"][0]["app_opens"]["count"] == 0
        first = c.post(f"/api/bi-estate/{did}/opens", json={"view_id": "view-aaaaaaaa"})
        retry = c.post(f"/api/bi-estate/{did}/opens", json={"view_id": "view-aaaaaaaa"})
        second = c.post(f"/api/bi-estate/{did}/opens", json={"view_id": "view-bbbbbbbb"})
        assert first.json()["recorded"] and not retry.json()["recorded"] and second.json()["recorded"]
        opens = rows(c, origin="generated")["rows"][0]["app_opens"]
        assert opens["count"] == 2 and opens["last_at"] == second.json()["event"]["at"]
        assert c.post("/api/bi-estate/AST-9999/opens", json={"view_id": "view-cccccccc"}).status_code == 404


def test_activity_and_ownership_precision_for_ast_0009():
    with TestClient(app) as c:
        d = c.get("/api/bi-estate/AST-0009").json()
        assert d["owner"]["id"] == "OWN-044" and d["owner_state"] == "inactive" and "needs_owner" in d["issues"]
        assert d["usage"]["last_view_month"] == "2026-10" and d["modified"]["value"] == "2026-10-13"
        assert d["creator"]["recorded"] is False and d["refresh"]["last_success"] is None
        # Three different people are called Nina Garcia: joins go by owner ID, never by name.
        ninas = {x["owner"]["id"] for x in rows(c, q="Nina Garcia")["rows"] if x["owner"] and x["owner"]["name"] == "Nina Garcia"}
        assert {"OWN-001", "OWN-053"} <= ninas


def test_kpi_conflict_model_conflict_and_lineage_direction():
    with TestClient(app) as c:
        d = c.get("/api/bi-estate/AST-0013").json()
        kpis = {k["id"]: k for k in d["kpis"]}
        assert kpis["KPI-001"]["approved_canonical"] and kpis["KPI-001"]["binding"] == "Asset_KPI_Map row 41"
        assert kpis["KPI-002"]["definition_status"] == "definition_conflict" and kpis["KPI-002"]["evidence"] == "KPI_Catalog row 3"
        assert "definition" in d["issues"] and "KPI-002" in d["variant_kpi_ids"]
        e = c.get("/api/bi-estate/AST-0079").json()
        assert e["scope"]["product"] == "mismatch" and e["model"]["id"] == "SM-040" and e["model"]["refresh_status"] == "healthy"
        assert "scope" in e["issues"] and e["upstream"][0]["evidence"] == "Lineage_Edges row 89"
        assert e["owner"]["id"] == "OWN-045" and e["owner_state"] == "active"
        up = c.get("/api/bi-estate/AST-0008").json()["upstream"]
        down = c.get("/api/bi-estate/AST-0074").json()["downstream"]
        assert {"id": "AST-0074", "evidence": "Lineage_Edges row 10"}.items() <= next(x for x in up if x["id"] == "AST-0074").items()
        assert any(x["id"] == "AST-0008" and x["evidence"] == "Lineage_Edges row 10" for x in down)


def test_pair_rule_finds_finland_and_spain_and_rejects_false_positives():
    with TestClient(app) as c:
        fi = c.get("/api/bi-estate/pairs/AST-0089/AST-0022").json()
        assert fi["id"] == "AST-0022~AST-0089" and fi["qualifies"] and fi["shared_approved_ids"] == ["KPI-023", "KPI-027"]
        assert fi["a"]["owner"]["id"] == "OWN-053" and fi["b"]["owner"]["id"] == "OWN-022"
        assert fi["a"]["model"]["id"] == "SM-007" and fi["b"]["model"]["id"] == "SM-002" and fi["b"]["model"]["region"] == "North America"
        assert fi["a"]["usage"]["last_view_count"] == 283 and fi["b"]["usage"]["last_view_count"] == 1032
        assert fi["only_a"] and fi["only_b"]
        assert set(bi_estate.projection()["pairs"]) == {"AST-0022~AST-0089", "AST-0277~AST-0286"}
        for a, b in (("AST-0001", "AST-0067"), ("AST-0117", "AST-0210")):
            assert not c.get(f"/api/bi-estate/pairs/{a}/{b}").json()["qualifies"]


def test_source_chronology_anomaly_is_flagged_without_changing_dates():
    with TestClient(app) as c:
        d = c.get("/api/bi-estate/AST-0286").json()
        assert "chronology" in d["issues"] and (d["created"]["value"], d["modified"]["value"]) == ("2026-08-28", "2026-01-10")


def test_filters_sort_unknowns_last_and_paginate():
    with TestClient(app) as c:
        r = c.get("/api/bi-estate", params={"sort": "last_use", "direction": "desc", "size": 400 // 4}).json()
        months = [x["last_view_month"] for x in r["rows"]]
        assert months == sorted(months, reverse=True)
        tail = c.get("/api/bi-estate", params={"sort": "last_use", "page": 4, "size": 100}).json()["rows"]
        assert tail[-1]["last_view_month"] is None  # app reports have no imported usage: last, not first
        assert c.get("/api/bi-estate", params={"sort": "nonsense"}).status_code == 422
        fi = rows(c, market="FI", issue="consolidation")
        assert fi["matching"] == 2 and fi["pairs_in_view"] == 1


def test_owner_review_is_one_case_per_pair_with_attributable_responses_and_a_decision():
    with TestClient(app) as c:
        body = {"asset_a": "AST-0022", "asset_b": "AST-0089", "question": "Which decisions need separate reports?"}
        assert c.post("/api/bi-reviews", json=body).status_code == 401
        assert c.post("/api/bi-reviews", json=body, headers=NINA).status_code == 403
        assert c.post("/api/bi-reviews", json=body, headers={"X-AnalytIQ-Actor": "OWN-044"}).status_code == 403  # inactive
        first = c.post("/api/bi-reviews", json=body, headers=STEWARD).json()
        again = c.post("/api/bi-reviews", json={**body, "asset_a": "AST-0089", "asset_b": "AST-0022"}, headers=STEWARD).json()
        assert first["id"] == again["id"] and first["status"] == "awaiting_responses"
        assert first["id"] in rows(c, q="AST-0022")["rows"][0]["case_ids"]
        response = {"kind": "response", "proposal": "keep_both", "purpose": "Market access tracking for Finland"}
        assert c.post(f"/api/bi-reviews/{first['id']}/events", json={**response, "expected_seq": 1}, headers=OTHER).status_code == 403
        assert c.post(f"/api/bi-reviews/{first['id']}/events", json={**response, "expected_seq": 1, "asset_id": "AST-0089"},
                      headers=NINA).status_code == 403  # Nina owns AST-0022, not AST-0089
        one = c.post(f"/api/bi-reviews/{first['id']}/events", json={**response, "expected_seq": 1}, headers=NINA).json()
        stale = c.post(f"/api/bi-reviews/{first['id']}/events", json={**response, "expected_seq": 1}, headers=SOFIA)
        assert stale.status_code == 409
        two = c.post(f"/api/bi-reviews/{first['id']}/events",
                     json={**response, "proposal": "consolidate", "expected_seq": one["seq"]}, headers=SOFIA).json()
        assert two["status"] == "ready_for_decision"
        assert two["responses"]["AST-0022"]["actor_id"] == "OWN-053" and two["responses"]["AST-0089"]["actor_id"] == "OWN-022"
        decision = {"kind": "decision", "outcome": "keep_both", "reason": "Different audiences", "expected_seq": two["seq"]}
        assert c.post(f"/api/bi-reviews/{first['id']}/events", json=decision, headers=SOFIA).status_code == 403
        done = c.post(f"/api/bi-reviews/{first['id']}/events", json=decision, headers=STEWARD).json()
        assert done["status"] == "closed" and done["decision"]["owner_disagreement"]
        assert "Not executed" in done["decision"]["execution"]
        # Reopening the pair starts a new case that links the earlier decision.
        reopened = c.post("/api/bi-reviews", json=body, headers=STEWARD).json()
        assert reopened["generation"] == 2 and reopened["reopened_from"] == first["id"]
        assert c.get(f"/api/bi-reviews/{first['id']}").json()["decision"]["outcome"] == "keep_both"
        # Both reports and their evidence still resolve.
        assert c.get("/api/bi-estate/AST-0022").status_code == 200 and c.get("/api/bi-estate/AST-0089").status_code == 200


def test_consolidation_plan_needs_a_survivor_owner_and_checkpoint():
    with TestClient(app) as c:
        case = c.post("/api/bi-reviews", json={"asset_a": "AST-0277", "asset_b": "AST-0286",
                                               "question": "Can one Spain report serve both needs?"}, headers=STEWARD).json()
        owners = {o["asset_id"]: o["owner"]["id"] for o in case["owners"]}
        seq = case["seq"]
        for aid, oid in owners.items():
            seq = c.post(f"/api/bi-reviews/{case['id']}/events", json={"kind": "response", "proposal": "consolidate",
                         "purpose": "Spain launch tracking", "asset_id": aid, "expected_seq": seq},
                         headers={"X-AnalytIQ-Actor": oid}).json()["seq"]
        bad = c.post(f"/api/bi-reviews/{case['id']}/events", json={"kind": "decision", "outcome": "consolidation_plan",
                     "reason": "One report covers both", "expected_seq": seq}, headers=STEWARD)
        assert bad.status_code == 422
        plan = c.post(f"/api/bi-reviews/{case['id']}/events", json={"kind": "decision", "outcome": "consolidation_plan",
                      "reason": "One report covers both", "survivor": "AST-0277", "accountable_owner_id": owners["AST-0277"],
                      "checkpoint": "2026-12-01", "expected_seq": seq}, headers=STEWARD).json()
        assert plan["decision"]["plan"]["survivor"] == "AST-0277"


def test_owner_assignment_is_a_steward_overlay_that_keeps_the_imported_fact():
    with TestClient(app) as c:
        body = {"owner_id": "OWN-045", "reason": "Julia covers this market", "expected_seq": 0}
        assert c.post("/api/bi-estate/AST-0009/owner", json=body, headers=NINA).status_code == 403
        assert c.post("/api/bi-estate/AST-0009/owner", json={**body, "owner_id": "OWN-044"}, headers=STEWARD).status_code == 422
        d = c.post("/api/bi-estate/AST-0009/owner", json=body, headers=STEWARD).json()
        assert d["owner"]["id"] == "OWN-045" and d["owner"]["via"] == "assignment" and d["owner_state"] == "active"
        assert d["imported_owner"]["id"] == "OWN-044" and "needs_owner" not in d["issues"]
        assert c.post("/api/bi-estate/AST-0009/owner", json=body, headers=STEWARD).status_code == 409  # stale


def test_cases_and_opens_survive_a_mongodb_restart():
    db = AsyncMockDB()
    with TestClient(app) as c:
        app.state.pipeline.store = MongoStore(db)
        case = c.post("/api/bi-reviews", json={"asset_a": "AST-0022", "asset_b": "AST-0089",
                                               "question": "Which decisions need separate reports?"}, headers=STEWARD).json()
        c.post("/api/bi-estate/AST-0022/opens", json={"view_id": "view-mongo-1"})
        app.state.pipeline.store = MongoStore(db)  # a new connection to the same database
        again = c.post("/api/bi-reviews", json={"asset_a": "AST-0089", "asset_b": "AST-0022",
                                                "question": "Which decisions need separate reports?"}, headers=STEWARD).json()
        assert again["id"] == case["id"]
        assert c.post("/api/bi-estate/AST-0022/opens", json={"view_id": "view-mongo-1"}).json()["recorded"] is False
        assert rows(c, q="AST-0022")["rows"][0]["app_opens"]["count"] == 1


def test_unknown_demo_identity_grants_nothing():
    with TestClient(app) as c:
        assert c.get("/api/bi-identity").json()["personas"][0]["id"] == "DEMO-BI-STEWARD"
        res = c.post("/api/bi-reviews", json={"asset_a": "AST-0022", "asset_b": "AST-0089", "question": "Anything to merge here?"},
                     headers={"X-AnalytIQ-Actor": "Anyone at all"})
        assert res.status_code == 403
