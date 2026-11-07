"""Evidence & governance in the BI Portfolio: fixtures, scope, document access, the steward's register-map-review path,
versioned reassessment, exceptions, review events and persistence."""
from fastapi.testclient import TestClient

from app import governance
from app.main import app
from app.store import MongoStore
from .fakes import AsyncMockDB

STEWARD = {"X-AnalytIQ-Actor": "DEMO-BI-STEWARD"}
REVIEWER = {"X-AnalytIQ-Actor": "DEMO-GOV-REVIEWER"}
AUDITOR = {"X-AnalytIQ-Actor": "DEMO-AUDITOR"}
NEW_OWNER = {"X-AnalytIQ-Actor": "OWN-001"}  # active; becomes owner of AST-0009 at handover
G = "/api/bi-governance"


def register(c, rev=1, expected=0, **over):
    src = governance.sources()[f"demo/DEMO-POL-001/r{rev}"]
    body = {"source_ref": src["ref"], "doc_id": src["doc_id"], "title": src["title"], "issuer": src["issuer"],
            "accountable_team": src["accountable_team"], "version": src["version"], "effective_from": src["effective_from"],
            "clause_id": "2", "excerpt": src["clauses"]["2"]["text"], "expected_revision": expected, **over}
    return c.post(f"{G}/documents", json=body, headers=STEWARD)


def map_demo(c, asset="AST-0009"):
    m = c.post(f"{G}/documents/DEMO-POL-001/mappings", json={"asset_id": asset, "clause_id": "2",
               "reason": "Production ownership note for this supply report"}, headers=STEWARD).json()
    res = c.post(f"{G}/mappings/{m['id']}/decision", json={"decision": "accepted", "reason": "Production report, explicit request"},
                 headers=REVIEWER)
    assert res.status_code == 200, res.text
    return m


def policy(g, doc_id):
    return next((p for p in g["policies"] + g["not_applicable"] if p["doc_id"] == doc_id), None)


def test_the_four_fixture_dashboards_reproduce_their_source_facts():
    with TestClient(app) as c:
        g = c.get(f"{G}/assets/AST-0013").json()
        ev = {i["id"]: i for i in g["evidence"]}
        assert {"ev-analytics_assets-14", "ev-asset_kpi_map-41", "ev-asset_kpi_map-44", "ev-kpi_catalog-2", "ev-kpi_catalog-3",
                "ev-governance_signals-18", "ev-governance_signals-19"} <= set(ev)
        assert ev["ev-asset_kpi_map-44"]["source"] | {} and ev["ev-asset_kpi_map-44"]["source"]["sheet"] == "Asset_KPI_Map"
        definition = next(x for x in g["risks"] if x["code"] == "definition")
        assert definition["observation"].startswith("2 Net Sales definitions are bound to this report (KPI-001, KPI-002)")
        assert "does not quantify" in definition["consequence"] and definition["rule_ids"] == ["RULE-002"]
        detail = c.get(f"{G}/evidence/ev-check-DEF-1-AST-0013", params={"asset": "AST-0013"}).json()
        assert {l["id"] for l in detail["linked"]} == {"ev-asset_kpi_map-41", "ev-asset_kpi_map-44", "ev-kpi_catalog-2", "ev-kpi_catalog-3"}
        rule2 = policy(g, "RULE-002")
        assert rule2["status"] == "applies" and rule2["result"] == "finding" and rule2["authority_label"] == "Challenge workbook"
        assert rule2["clause"]["text"].startswith("Use approved KPI definitions") and rule2["clause"]["source"]["row"] == 3
        assert g["finding_map"]["definition"] == [definition["id"]]
        # separate high-reach and migration signals, each its own source observation
        assert {x["signal_id"] for x in g["risks"] if x["signal_id"]} == {"SIG-00017", "SIG-00018"}

        g = c.get(f"{G}/assets/AST-0234").json()
        assert g["asset"]["issues"] == ["signal"]  # the tracker no longer says "No open finding"
        risk = c.get(f"{G}/risks/RISK-AST-0234-SIG-00258").json()
        assert risk["source_severity"] == "high" and risk["source_status"] == "open" and risk["rule_priority"] == "medium"
        assert risk["guidance"][0]["text"].startswith("High-audience content") and risk["evidence"][0]["source"]["row"] == 259
        assert policy(g, "RULE-005")["result"] == "finding"
        listed = c.get(G, params={"tab": "risks", "q": "SIG-00258", "size": 100}).json()
        assert listed["total"] == 1 and listed["distinct_assets"] == 1  # counted once

        g = c.get(f"{G}/assets/AST-0079").json()
        scope = next(x for x in g["risks"] if x["code"] == "scope")
        assert "Eylea / Japan" in scope["observation"] and "Nubeqa / Global" in scope["observation"]
        assert scope["origin_label"] == "AnalytIQ check" and scope["checks"][0]["id"] == "SCOPE-1" and not scope["rule_ids"]
        linked = {l["id"] for l in c.get(f"{G}/evidence/ev-check-SCOPE-1-AST-0079", params={"asset": "AST-0079"}).json()["linked"]}
        assert {"ev-analytics_assets-80", "ev-semantic_models-41", "ev-lineage_edges-89"} <= linked
        assert not any(x["signal_id"] for x in g["risks"])

        g = c.get(f"{G}/assets/AST-0009").json()
        assert policy(g, "RULE-006")["status"] == "not_applicable"  # a lifecycle flag on Power BI is not a migration
        assert {"ev-analytics_assets-10", "ev-workspaces-3"} <= {i["id"] for i in g["evidence"]}


def test_absent_rule_missing_evidence_and_assessed_clear_are_distinct():
    with TestClient(app) as c:
        g = c.get(f"{G}/assets/AST-0234").json()
        assert policy(g, "RULE-003")["result"] == "clear"           # applies, assessed, no finding
        assert policy(g, "RULE-007")["status"] == "not_applicable"  # guidance does not apply
        assert policy(g, "RULE-001")["status"] == "undetermined"    # cannot be checked from the record
        assert policy(c.get(f"{G}/assets/AST-0013").json(), "RULE-006")["result"] == "needs_evidence"


def test_document_register_map_review_supersede_and_reopen():
    with TestClient(app) as c:
        assert register(c, excerpt="Owners may hand over whenever they like.").status_code == 422
        assert c.post(f"{G}/documents", json={}, headers=NEW_OWNER).status_code in (403, 422)
        assert register(c).json() == {"document": "DEMO-POL-001", "revision": 1, "created": True}
        assert register(c).json()["created"] is False  # retry is harmless
        # proposed is not yet applicable; the proposer cannot confirm
        m = c.post(f"{G}/documents/DEMO-POL-001/mappings", json={"asset_id": "AST-0009", "clause_id": "2", "reason": "Ownership note"},
                   headers=STEWARD).json()
        assert c.post(f"{G}/mappings/{m['id']}/decision", json={"decision": "accepted", "reason": "self approval"}, headers=STEWARD).status_code == 403
        assert policy(c.get(f"{G}/assets/AST-0009").json(), "DEMO-POL-001")["status"] == "undetermined"
        map_demo(c)
        g = c.get(f"{G}/assets/AST-0009", headers=STEWARD).json()
        p = policy(g, "DEMO-POL-001")
        assert p["status"] == "applies" and p["result"] == "needs_evidence" and p["authority_label"] == "Demo document"
        assert {"ev-analytics_assets-10", "ev-workspaces-3"} <= {f["evidence_id"] for f in p["facts"]}
        assert "accepted by Governance reviewer" in p["facts"][0]["text"]
        # one entry, one affected dashboard; not present for an unaffected scope
        idx = c.get(G, params={"tab": "policies", "q": "DEMO-POL"}).json()
        assert [(r["id"], r["affected"]) for r in idx["rows"]] == [("DEMO-POL-001", 1)]
        assert not [r for r in c.get(G, params={"tab": "policies", "product": "Eylea"}).json()["rows"] if r["id"] == "DEMO-POL-001"]
        none = c.get(G, params={"tab": "policies", "product": "Eylea", "q": "DEMO-POL"}).json()
        assert none["total"] == 0 and none["distinct_assets"] == 0  # counts follow the same scoped rows
        doc = c.get(f"{G}/documents/DEMO-POL-001").json()
        assert [a["id"] for a in doc["affected"]] == ["AST-0009"] and doc["current"]["version"] == "1"
        assert "incoming accountable person" in c.get(f"{G}/documents/DEMO-POL-001/revisions/1/original").json()["text"]

        # handover: the steward assigns an active owner, who adds evidence for the clause
        c.post("/api/bi-estate/AST-0009/owner", json={"owner_id": "OWN-001", "reason": "Handover from inactive owner", "expected_seq": 0},
               headers=STEWARD).raise_for_status()
        body = {"expected_seq": 0, "record_evidence_id": "ev-analytics_assets-10", "revision_or_section": "Clause 2, revision 1",
                "supports": "Incoming accountable person OWN-001 recorded before the handover", "clause_ref": "DEMO-POL-001#2"}
        assert c.post(f"{G}/assets/AST-0009/evidence", json=body, headers=STEWARD).status_code == 403
        first = c.post(f"{G}/assets/AST-0009/evidence", json=body, headers=NEW_OWNER).json()
        again = c.post(f"{G}/assets/AST-0009/evidence", json=body, headers=NEW_OWNER).json()
        assert first["id"] == again["id"] == "EVS-AST-0009-0001" and first["authority_label"] == "Owner statement"
        assert c.post(f"{G}/evidence/{first['id']}/reviews", json={"decision": "verified", "note": "Matches the handover record",
                      "expected_reviews": 0}, headers=AUDITOR).status_code == 403
        verified = c.post(f"{G}/evidence/{first['id']}/reviews", json={"decision": "verified", "note": "Matches the handover record",
                          "expected_reviews": 0}, headers=REVIEWER).json()
        assert verified["authority_label"] == "Owner statement, verified"
        path = f"{G}/documents/DEMO-POL-001/clauses/2/assets/AST-0009/events"
        assert c.post(path, json={"kind": "assessment", "expected_seq": 0, "judgment": "clear", "reason": "Handover recorded",
                                  "evidence_ids": []}, headers=REVIEWER).status_code == 422  # closing needs evidence
        judged = c.post(path, json={"kind": "assessment", "expected_seq": 0, "judgment": "clear", "reason": "Handover recorded before change",
                                    "evidence_ids": [first["id"], "ev-workspaces-3"]}, headers=REVIEWER).json()
        assert policy(c.get(f"{G}/assets/AST-0009").json(), "DEMO-POL-001")["result"] == "clear"

        # revision 2 supersedes from 2026-11-01; the earlier assessment keeps its clause
        assert register(c, rev=2, expected=0).status_code == 409
        assert register(c, rev=2, expected=1).json()["revision"] == 2
        before = c.get(f"{G}/assets/AST-0009", params={"at": "2026-10-15"}).json()
        after = c.get(f"{G}/assets/AST-0009", params={"at": "2026-11-07"}).json()
        assert "effective handover date" not in policy(before, "DEMO-POL-001")["clause"]["text"]
        assert "effective handover date" in policy(after, "DEMO-POL-001")["clause"]["text"]
        reopened = c.get(f"{G}/assessments/{judged['assessment']}", headers=AUDITOR).json()
        assert reopened["snapshot"]["clause"]["revision"] == 1 and "effective handover date" not in reopened["snapshot"]["clause"]["text"]
        assert reopened["snapshot"]["evidence"][0]["value"]["revision_or_section"] == "Clause 2, revision 1"
        assert any("revision 2" in ch for ch in reopened["changes_since"]) and reopened["actor_name"] == "Governance reviewer (demo)"
        revs = c.get(f"{G}/documents/DEMO-POL-001").json()["revisions"]
        assert [r["effective_to"] for r in revs] == ["2026-11-01", None]


def test_unrelated_and_inaccessible_documents_leave_no_trace():
    with TestClient(app) as c:
        store = app.state.pipeline.store
        src = governance.sources()["demo/DEMO-HR-001/r1"]
        c.post(f"{G}/documents", json={"source_ref": src["ref"], "doc_id": "DEMO-HR-001", "title": src["title"], "issuer": src["issuer"],
               "accountable_team": src["accountable_team"], "version": "1", "effective_from": src["effective_from"], "clause_id": "4",
               "excerpt": src["clauses"]["4"]["text"], "expected_revision": 0}, headers=STEWARD).raise_for_status()
        # a confidential document mapped to the same dashboard, readable by nobody in this demo
        store.artifacts.setdefault(governance.DOCS, {})["CONF-001"] = {"_id": "CONF-001", "title": "Confidential pricing guidance",
            "authority": "company_document", "access": "restricted", "access_roles": ["pricing_committee"]}
        store.artifacts.setdefault(governance.REVS, {})["CONF-001:r1"] = {"_id": "CONF-001:r1", "doc_id": "CONF-001", "revision": 1,
            "version": "3", "effective_from": "2026-01-01", "clauses": {"1": {"title": "Secret", "text": "Hidden text"}}, "source_ref": "x"}
        store.artifacts.setdefault(governance.MAPS, {})["MAP-CONF-001-1-AST-0009"] = {"_id": "MAP-CONF-001-1-AST-0009", "doc_id": "CONF-001",
            "clause_id": "1", "asset_id": "AST-0009", "status": "accepted", "reason": "x", "actor_id": "x", "actor_name": "x",
            "at": "2026-01-01", "decided_by": "y"}
        for who in ({}, STEWARD, REVIEWER):
            g = c.get(f"{G}/assets/AST-0009", headers=who).json()
            text = str(g)
            assert "CONF-001" not in text and "Confidential pricing" not in text and "DEMO-HR-001" not in text
            idx = str(c.get(G, params={"tab": "policies", "size": 100}, headers=who).json())
            assert "CONF-001" not in idx and "DEMO-HR-001" not in idx  # unrelated: no dashboard in scope
            assert c.get(f"{G}/documents/CONF-001", headers=who).status_code == 404
            assert c.get(f"{G}/documents/CONF-001/revisions/1/original", headers=who).status_code == 404
            assert c.get(f"{G}/documents/NOPE-404", headers=who).json() == c.get(f"{G}/documents/CONF-001", headers=who).json()
        assert c.post(f"{G}/documents/CONF-001/mappings", json={"asset_id": "AST-0013", "clause_id": "1", "reason": "guessing"},
                      headers=STEWARD).status_code == 404
        assert c.post(f"{G}/exceptions", json={"asset_ids": ["AST-0009"], "rule_ref": "CONF-001#1", "rationale": "guessing an id here",
                      "expires": "2027-01-01", "reference": "none"}, headers=STEWARD).status_code == 404
        assert c.get(f"{G}/assets/NOT-AN-ASSET").status_code == 404


def test_exception_covers_the_conflict_until_it_expires():
    with TestClient(app) as c:
        e = c.post(f"{G}/exceptions", json={"asset_ids": ["AST-0013"], "rule_ref": "RULE-002", "kpi_id": "KPI-002",
                   "rationale": "Local net sales used until the China ledger migrates", "expires": "2026-12-31",
                   "reference": "Finance steering minutes 2026-10 (demo)"}, headers=STEWARD).json()
        assert policy(c.get(f"{G}/assets/AST-0013", params={"at": "2026-11-10"}).json(), "RULE-002")["result"] == "finding"  # proposed only
        assert c.post(f"{G}/exceptions/{e['id']}/decision", json={"decision": "accepted", "reason": "Documented and time bounded"},
                      headers=STEWARD).status_code == 403
        c.post(f"{G}/exceptions/{e['id']}/decision", json={"decision": "accepted", "reason": "Documented and time bounded"},
               headers=REVIEWER).raise_for_status()
        during = policy(c.get(f"{G}/assets/AST-0013", params={"at": "2026-11-10"}).json(), "RULE-002")
        after = policy(c.get(f"{G}/assets/AST-0013", params={"at": "2027-01-05"}).json(), "RULE-002")
        assert during["result"] == "exception" and during["exception"]["state"] == "active"
        assert after["result"] == "expired_exception" and after["exception"]["state"] == "expired"


def test_risk_review_is_attributable_conflict_safe_and_keeps_the_source_status():
    with TestClient(app) as c:
        rid = "RISK-AST-0234-SIG-00258"
        path = f"{G}/risks/{rid}/events"
        assert c.post(path, json={"kind": "assign", "expected_seq": 0, "assignee_id": "DEMO-GOV-REVIEWER"}).status_code == 401
        assert c.post(path, json={"kind": "assign", "expected_seq": 0, "assignee_id": "DEMO-GOV-REVIEWER"}, headers=REVIEWER).status_code == 403
        one = c.post(path, json={"kind": "assign", "expected_seq": 0, "assignee_id": "DEMO-GOV-REVIEWER"}, headers=STEWARD).json()
        two = c.post(path, json={"kind": "assign", "expected_seq": 0, "assignee_id": "DEMO-GOV-REVIEWER"}, headers=STEWARD).json()
        assert one["id"] == two["id"]  # double submit records one event
        assert c.post(path, json={"kind": "request_evidence", "expected_seq": 0, "note": "Show the trust review"},
                      headers=STEWARD).status_code == 409  # stale
        assert c.get("/api/bi-estate/AST-0234").json()["owner"]["id"] == "OWN-054"  # reviewing does not change ownership
        c.post(path, json={"kind": "assessment", "expected_seq": 1, "judgment": "clear", "reason": "Reviewed with the owner; audience is internal",
                           "evidence_ids": ["ev-governance_signals-259"]}, headers=REVIEWER).raise_for_status()
        risk = c.get(f"{G}/risks/{rid}").json()
        assert risk["review"]["status"] == "closed" and risk["source_status"] == "open"  # imported status preserved
        assert policy(c.get(f"{G}/assets/AST-0234").json(), "RULE-005")["result"] == "clear"
        assert [h["kind"] for h in risk["history"]] == ["assign", "assessment"]


def test_material_change_mid_review_needs_confirmation():
    with TestClient(app) as c:
        rid = "RISK-AST-0079-scope"
        c.post(f"{G}/risks/{rid}/events", json={"kind": "assign", "expected_seq": 0, "assignee_id": "DEMO-GOV-REVIEWER"},
               headers=STEWARD).raise_for_status()
        c.post("/api/bi-estate/AST-0079/owner", json={"owner_id": "OWN-001", "reason": "Reorganisation", "expected_seq": 0},
               headers=STEWARD).raise_for_status()
        body = {"kind": "assessment", "expected_seq": 1, "judgment": "needs_action", "reason": "Owner must confirm the model",
                "evidence_ids": ["ev-check-SCOPE-1-AST-0079"]}
        assert c.post(f"{G}/risks/{rid}/events", json=body, headers=REVIEWER).status_code == 409
        ok = c.post(f"{G}/risks/{rid}/events", json={**body, "acknowledge_changes": True}, headers=REVIEWER).json()
        assert c.get(f"{G}/assessments/{ok['assessment']}").json()["snapshot"]["acknowledged_changes"] is True


def test_index_scope_paging_and_no_effect_on_report_opens():
    with TestClient(app) as c:
        p1 = c.get(G, params={"tab": "risks", "size": 10, "page": 1}).json()
        p2 = c.get(G, params={"tab": "risks", "size": 10, "page": 2}).json()
        assert p1["total"] == p2["total"] and p1["distinct_assets"] == p2["distinct_assets"]
        assert not {r["id"] for r in p1["rows"]} & {r["id"] for r in p2["rows"]}
        narrow = c.get(G, params={"tab": "policies", "product": "Eylea"}).json()
        assert narrow["scope_assets"] < p1["portfolio_assets"] and narrow["distinct_assets"] <= narrow["scope_assets"]
        c.get(f"{G}/assets/AST-0013")
        c.get(f"{G}/evidence/ev-analytics_assets-14", params={"asset": "AST-0013"})
        assert c.get("/api/bi-estate/AST-0013").json()["app_opens"]["count"] == 0
        assert c.get(f"{G}/evidence/ev-analytics_assets-14", params={"asset": "AST-0013"}).json()["record"]["asset_name"] == "Beyonttra Budget Final"


def test_governance_records_survive_a_mongodb_restart():
    db = AsyncMockDB()
    with TestClient(app) as c:
        app.state.pipeline.store = MongoStore(db)
        register(c).raise_for_status()
        map_demo(c)
        app.state.pipeline.store = MongoStore(db)
        assert policy(c.get(f"{G}/assets/AST-0009").json(), "DEMO-POL-001")["status"] == "applies"
        assert register(c).json()["created"] is False
