import asyncio

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


def await_all(coro):
    return asyncio.run(coro)


def test_datapack_endpoints(client):
    s = client.get("/api/datapack").json()
    assert s["assets"] == 360 and s["sheets"]["governance_signals"] == 410
    assert len(client.get("/api/requests").json()) == 150


def test_v2_chat_shows_the_input(client):
    typed = client.post("/api/v2/chat", json={"message": "  Show net sales  ", "conversation_id": "c1"})
    assert typed.status_code == 200
    assert typed.json() == {
        "received": {"conversation_id": "c1", "message": "  Show net sales  ", "preset_id": None, "guided_id": None, "choice_id": None},
        "question": "Show net sales", "source": "message", "length": 14, "new_conversation": False,
    }

    preset = client.post("/api/v2/chat", json={"preset_id": "scn_reuse_eylea_jp", "guided_id": None, "choice_id": None}).json()
    assert preset["source"] == "preset" and "Eylea" in preset["question"] and preset["new_conversation"] is True

    both = client.post("/api/v2/chat", json={"message": "Typed wins", "preset_id": "scn_reuse_eylea_jp", "guided_id": None, "choice_id": None}).json()
    assert both["source"] == "message" and both["question"] == "Typed wins"

    assert client.post("/api/v2/chat", json={"message": "   "}).status_code == 400
    unknown = client.post("/api/v2/chat", json={"preset_id": "nope", "guided_id": None, "choice_id": None})
    assert unknown.status_code == 400 and unknown.json()["detail"] == "Unknown preset: nope"

    assert client.get("/api/conversations").json() == []  # nothing was saved


def test_classify_business_request(client):
    r = client.post("/api/v2/classify", json={
        "request": "Please build a new report for market access coverage and reimbursement status by product."})
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {"urgency", "domain", "market", "product", "governed_kpis", "semantic_model", "existing_report"}
    assert body["domain"] == "Market Access"
    assert "market_access_coverage" in [k["id"] for k in body["governed_kpis"]]
    assert body["product"] == [] and body["market"] == []  # the request names neither
    assert body["semantic_model"]["id"].startswith("SM-")
    assert body["existing_report"] in ("yes", "no")

    # SinceAI's rows with this exact text vote: their labels are mixed, so the result reports the votes.
    urgency = body["urgency"]
    assert urgency["source"] == "vector_vote" and urgency["match"] == "same"
    assert sum(urgency["votes"].values()) == urgency["neighbours_used"] == 16
    assert urgency["votes"][urgency["value"]] == max(urgency["votes"].values())

    assert client.get("/api/conversations").json() == []  # nothing was saved


def test_classify_reads_product_market_and_deadline_from_the_words(client):
    body = client.post("/api/v2/classify", json={
        "request": "We need Xarelto on-time-in-full and market access coverage for Mexico by end of day."}).json()
    assert body["product"] == ["Xarelto"] and body["market"] == ["Mexico"]
    assert body["urgency"]["value"] == "urgent" and body["urgency"]["source"] == "stated_in_request"
    assert body["urgency"]["evidence"].lower() == "end of day"


def test_classify_existing_report_yes_and_out_of_scope(client):
    reuse = client.post("/api/v2/classify", json={
        "request": "Show monthly inventory coverage and OTIF for Lynkuet in Spain."}).json()
    assert reuse["existing_report"] == "yes" and reuse["existing_report_detail"]["status"] == "usable"
    assert reuse["existing_report_detail"]["report"]["id"]

    out = client.post("/api/v2/classify", json={"request": "Can we see Nubeqa patient adherence by prescriber?"}).json()
    assert out["existing_report"] == "no" and "patient" in out["not_available"]


def test_classify_rejects_blank_and_oversized_requests(client):
    assert client.post("/api/v2/classify", json={"request": "   "}).status_code == 400
    assert client.post("/api/v2/classify", json={"request": "x" * 2001}).status_code == 422
    assert client.post("/api/v2/classify", json={}).status_code == 422


def test_classify_survives_vector_search_failure(client, monkeypatch):
    from app.main import pipeline

    async def boom(*args, **kwargs):
        raise RuntimeError("vector store down")

    monkeypatch.setattr(pipeline().vectors, "search", boom)
    r = client.post("/api/v2/classify", json={"request": "Show market access coverage."})
    assert r.status_code == 200
    body = r.json()
    assert body["urgency"]["source"] == "default" and "vector store down" in body["retrieval"]["error"]
    assert body["governed_kpis"]


def test_reuse_flow_with_preview(client):
    evs = sse(client.post("/api/chat", json={"preset_id": "scn_reuse_lynkuet_es", "guided_id": None, "choice_id": None}))
    d = stage(evs, "decision")["data"]
    assert d["decision"] == "reuse" and d["preview"]["rows"]
    assert stage(evs, "deliver")


@pytest.mark.parametrize("preset_id,value", [("req_finance_gtn", "new_build"), ("req_migrate_xarelto", "migration"),
                                             ("scn_repair_xarelto_mx", "review"), ("scn_reuse_eylea_jp", "review")])
def test_flow_ends_in_a_recommendation_and_builds_nothing(client, preset_id, value):
    assets_before = len(cat.CATALOG["assets"])
    evs = sse(client.post("/api/chat", json={"preset_id": preset_id}))
    stages = [e["stage"] for e in evs if e["type"] == "stage"]
    for gone in ("evidence", "spec", "approval", "render", "register"):
        assert gone not in stages
    assert [s for s in dict.fromkeys(stages) if s not in ("actions", "deliver")] == [
        "intent", "kpis", "discovery", "lineage", "governance", "migration", "decision"]
    assert evs[-1]["type"] == "done" and evs[-1]["state"] == "idle"
    rec = stage(evs, "decision")["data"]["recommendation"]
    assert rec["value"] == value and rec["reason"] and rec["rules_applied"]
    assert [e["step"] for e in rec["evidence"]] == [1, 2, 3, 4, 5, 6] and all(e["summary"] for e in rec["evidence"])
    assert len(cat.CATALOG["assets"]) == assets_before
    assert client.post("/api/approve", json={"conversation_id": evs[0]["id"]}).status_code in (404, 405)


def test_retirement_needs_evidence(client):
    low = min((a for a in cat.CATALOG["assets"] if a["lifecycle"] == "active"), key=lambda a: a["views_90d"])
    body = client.post("/api/v2/classify", json={"request": f"Can we retire {low['name']}?"}).json()
    assert body["recommendation"]["value"] == "retirement" and "low usage" in body["recommendation"]["reason"]
    assert body["existing_report_detail"]["report"]["id"]

    from app.decision import governance
    used = next(a for a in cat.CATALOG["assets"] if a["lifecycle"] == "active" and a["views_90d"] > 1000
                and governance(a)[0] >= 0.5 and sum(a["name"] == b["name"] for b in cat.CATALOG["assets"]) == 1)
    kept = client.post("/api/v2/classify", json={"request": f"Please retire {used['name']}."}).json()
    assert kept["recommendation"]["value"] == "reuse" and "does not support" in kept["recommendation"]["reason"]

    evs = sse(client.post("/api/chat", json={"message": f"Can we retire {low['name']}?"}))
    if any(e.get("stage") == "decision" for e in evs):
        assert stage(evs, "decision")["data"]["recommendation"]["value"] == "retirement"


def test_tableau_with_nothing_worth_moving_is_retirement():
    from app.decision import Decision, data_availability, decide, rank_candidates

    catalog = {**cat.CATALOG, "assets": [{**a, "lifecycle": "candidate_retire"} if a["platform"] == "Tableau" else a for a in cat.CATALOG["assets"]]}
    intent = {"question": "Replace our Xarelto Tableau workbook", "measures": ["net_sales"], "dimensions": [], "filters": {"product": ["Xarelto"]},
              "migration": {"from": "Tableau"}, "unmatched_terms": []}
    candidates = [c for c in rank_candidates(intent, catalog) if c.platform == "Tableau"]
    assert decide(candidates, data_availability(intent, catalog), intent, catalog).decision == Decision.RETIRE


def test_free_text_grill_me(client):
    evs = sse(client.post("/api/chat", json={"message": "I need net sales and gross-to-net"}))
    conv = evs[0]["id"]
    assert next(e for e in evs if e["type"] == "message")["kind"] == "question"
    evs = sse(client.post("/api/chat", json={"conversation_id": conv, "message": "All products, all markets"}))
    evs += sse(client.post("/api/chat", json={"conversation_id": conv, "message": "Monthly performance review"}))
    assert stage(evs, "decision")["data"]["decision"] in ("new_build", "consolidate", "reuse")


def test_not_feasible(client):
    evs = sse(client.post("/api/chat", json={"preset_id": "scn_out_of_scope", "guided_id": None, "choice_id": None}))
    assert stage(evs, "decision")["data"]["decision"] == "not_feasible"


def test_understand_step_carries_the_classification(client):
    text = "How are Eylea net sales and digital engagement developing in Japan?"
    evs = sse(client.post("/api/chat", json={"preset_id": "scn_reuse_eylea_jp", "guided_id": None, "choice_id": None}))
    tags = stage(evs, "intent")["data"]["classification"]
    assert "semantic_model" not in tags  # known from the assessment on: the discovery stage completes the classification
    tags = {**tags, **stage(evs, "discovery")["data"]["classification"]}
    assert tags["domain"] == "Commercial"
    assert tags["market"] == ["JP"] or tags["market"] == ["Japan"]
    assert tags["product"] == ["Eylea"]
    assert [k["name"] for k in tags["governed_kpis"]] == ["Net Sales", "Digital Engagement Index"]
    assert tags["semantic_model"]["id"] == "SM-040"
    assert tags["existing_report"] == "yes"
    # The Ask flow's own decision agrees with what the step showed.
    assert stage(evs, "decision")["data"]["decision"] == tags["existing_report_detail"]["decision"] == "review"
    # And the standalone route gives the same tags for the same words.
    direct = client.post("/api/v2/classify", json={"request": text}).json()
    assert direct["existing_report"] == tags["existing_report"] and direct["domain"] == tags["domain"]


def test_classification_shows_while_a_follow_up_is_open(client):
    text = "Please build a new report for market access coverage and reimbursement status by product."
    evs = sse(client.post("/api/chat", json={"message": text}))
    waiting = next(e for e in evs if e.get("stage") == "intent" and e.get("status") == "waiting")
    tags = waiting["data"]["classification"]
    assert tags["domain"] == "Market Access"
    assert [k["kpi_id"] for k in tags["governed_kpis"]] == ["KPI-027", "KPI-031"]
    # The model is the assessment's result: a clarification shows the known scope without running it early.
    assert tags["breakdown"] == ["Product"] and "semantic_model" not in tags


def test_classify_returns_the_six_analysis_steps(client):
    steps = client.post("/api/v2/classify", json={
        "request": "Please build a new report for market access coverage and reimbursement status by product."}).json()["steps"]
    assert [s["step"] for s in steps] == [1, 2, 3, 4, 5, 6]
    assert [s["output"] for s in steps] == [
        "structured intent", "governed metric set", "reuse / consolidate candidates", "impact & lineage explanation",
        "risk / repair actions", "migrate / retire / consolidate recommendation"]

    assert steps[0]["data"]["domain"] == "Market Access"
    kpi = next(k for k in steps[1]["data"]["kpis"] if k["kpi_id"] == "KPI-027")
    assert kpi["canonical"] == "Market Access Coverage" and "Market Access Coverage Legacy" in kpi["conflicts"]
    assert kpi["aliases"]

    # Lineage counts come from the Lineage_Edges sheet.
    model_id = steps[3]["data"]["model"]["id"]
    edges = [e for e in cat.SHEETS["lineage_edges"] if e["source_id"] == model_id and e["edge_type"] == "MODEL_TO_ASSET"]
    assert steps[3]["data"]["downstream_count"] == len(edges) > 0


def test_steps_handle_tableau_and_trust(client):
    migration = client.post("/api/v2/classify", json={
        "request": "Please create a Power BI replacement for our legacy Tableau Xarelto commercial workbook."}).json()["steps"][5]["data"]
    assert migration["applies"] is True
    tableau = [a for a in cat.CATALOG["assets"] if a["platform"] == "Tableau" and a["product_scope"] == "Xarelto"]
    assert {a["id"] for a in migration["assets"]} >= {a["id"] for a in tableau}
    assert set(migration["counts"]) <= {"migrate", "retire", "consolidate", "review"}

    none = client.post("/api/v2/classify", json={
        "request": "How are Eylea net sales and digital engagement developing in Japan?"}).json()["steps"]
    assert none[5]["data"]["applies"] is False
    assert none[4]["data"]["subject"]["kind"] == "report" and none[4]["data"]["sensitivity"]

    empty = client.post("/api/v2/classify", json={"request": "Can we see Nubeqa patient adherence by prescriber?"}).json()["steps"]
    assert empty[1]["data"]["kpis"] == [] and empty[3]["data"]["model"] is None and empty[4]["data"]["subject"] is None


def test_ask_flow_shows_the_same_steps(client):
    evs = sse(client.post("/api/chat", json={"preset_id": "scn_reuse_eylea_jp", "guided_id": None, "choice_id": None}))
    assert "steps" not in stage(evs, "intent")["data"]["classification"]
    found = stage(evs, "discovery")["data"]["step"]
    assert found["step"] == 3 and found["data"]["reuse_count"] == 0
    assert found["data"]["scope_review_count"] >= 1
    assert any(c["id"] == "AST-0079" and c["role"] == "scope review" for c in found["data"]["candidates"])
    trust = stage(evs, "governance")["data"]["step"]["data"]
    assert [(s["sheet"], s["row"]) for s in trust["scope_sources"]] == [("Analytics_Assets", 80), ("Semantic_Models", 41)]
    assert "Eylea" in trust["risks"][0] and "Nubeqa" in trust["risks"][0]
    assert stage(evs, "lineage")["data"]["step"]["step"] == 4 and stage(evs, "migration")["data"]["step"]["data"]["applies"] is False



def test_every_backlog_path_gets_the_right_recommendation():
    from app.steps import _recommend

    expected = {"RETIRE": "retire", "CONSOLIDATE_BEFORE_MIGRATION": "consolidate", "HUMAN_REVIEW": "review",
                "MIGRATE": "migrate", "REBUILD_ON_SHARED_MODEL": "migrate"}
    assert {r["recommended_path_candidate"] for r in cat.SHEETS["migration_backlog"]} == set(expected)
    for path, action in expected.items():
        used = {"views_90d": 5000, "lifecycle": "active", "migration": {"recommended_path_candidate": path}}
        assert _recommend(used)[0] == action
    # Unused or retiring reports are retired whatever the backlog says.
    assert _recommend({"views_90d": 3, "lifecycle": "active", "migration": {"recommended_path_candidate": "MIGRATE"}})[0] == "retire"
    assert _recommend({"views_90d": 5000, "lifecycle": "candidate_retire", "migration": {"recommended_path_candidate": "MIGRATE"}})[0] == "retire"


def test_conversation_can_be_reopened_and_continued(client):
    evs = sse(client.post("/api/chat", json={"message": "I need net sales and gross-to-net"}))
    conv_id = evs[0]["id"]
    listed = client.get("/api/conversations").json()
    assert listed[0]["_id"] == conv_id and listed[0]["title"] == "I need net sales and gross-to-net"

    # Coming back later: everything needed to carry on is stored, including the open follow-up.
    saved = client.get(f"/api/conversations/{conv_id}").json()
    assert saved["state"] == "clarifying" and saved["asked"] == 1 and saved["messages"][-1]["kind"] == "question"
    assert [e["stage"] for e in saved["runs"][-1]["events"] if e["type"] == "stage"]
    measures = set(saved["intent"]["measures"])
    assert measures

    evs = sse(client.post("/api/chat", json={"conversation_id": conv_id, "message": "All products, all markets"}))
    evs += sse(client.post("/api/chat", json={"conversation_id": conv_id, "message": "Monthly performance review"}))
    assert all(e["id"] == conv_id for e in evs if e["type"] == "conversation")
    assert stage(evs, "decision")
    final = client.get(f"/api/conversations/{conv_id}").json()
    assert final["state"] == "idle" and len(client.get("/api/conversations").json()) == 1
    assert [m["role"] for m in final["messages"]].count("user") == 3
    assert measures <= set(final["intent"]["measures"])


def test_conversation_is_saved_before_the_answer_finishes(client):
    stream = client.stream("POST", "/api/chat", json={"preset_id": "scn_reuse_eylea_jp", "guided_id": None, "choice_id": None})
    with stream as r:
        for line in r.iter_lines():
            if '"user_message"' in line:
                break
        listed = client.get("/api/conversations").json()
    assert listed and listed[0]["title"]


def test_conversation_list_limit_and_unknown_id(client):
    for i in range(3):
        client.post("/api/chat", json={"message": f"Show net sales {i}"})
    assert len(client.get("/api/conversations", params={"limit": 2}).json()) == 2
    assert client.get("/api/conversations", params={"limit": 0}).status_code == 422
    assert client.get("/api/conversations/nope").status_code == 404


def test_delete_conversation_removes_it_and_what_it_produced(client):
    from app.main import pipeline

    keep = sse(client.post("/api/chat", json={"preset_id": "scn_reuse_eylea_jp", "guided_id": None, "choice_id": None}))[0]["id"]
    gone_evs = sse(client.post("/api/chat", json={"preset_id": "req_finance_gtn", "guided_id": None, "choice_id": None}))
    gone = gone_evs[0]["id"]
    store = pipeline().store
    vectors = pipeline().vectors
    sinceai_before = sum(1 for d, _ in vectors._mem.get("requests", []) if d.get("source") != "live")
    assert await_all(store.list_artifacts("agent_runs", gone)) and await_all(store.list_artifacts("intents", gone))
    action = client.post("/api/actions", json={"title": "Check the numbers", "owner": "Data steward", "conversation_id": gone})
    assert action.status_code == 201
    assert any(d.get("conversation_id") == gone for d in await_all(vectors.live_requests()))

    assert client.delete(f"/api/conversations/{gone}").status_code == 204

    assert client.get(f"/api/conversations/{gone}").status_code == 404
    assert [c["_id"] for c in client.get("/api/conversations").json()] == [keep]
    for kind in ("intents", "evidence", "specs", "agent_runs"):
        assert await_all(store.list_artifacts(kind, gone)) == []
    assert await_all(store.list_artifacts("agent_runs", keep))  # the other chat is untouched
    assert client.get(f"/api/conversations/{keep}").status_code == 200
    # An accepted action outlives the chat; SinceAI's rows stay; the chat's request no longer counts as asked before.
    assert await_all(store.list_artifacts("actions", gone))
    assert not any(d.get("conversation_id") == gone for d in await_all(vectors.live_requests()))
    assert not any(d.get("conversation_id") == gone for d, _ in vectors._mem.get("requests", []))
    assert sum(1 for d, _ in vectors._mem.get("requests", []) if d.get("source") != "live") == sinceai_before

    assert client.delete(f"/api/conversations/{gone}").status_code == 404  # already gone
    assert client.delete("/api/conversations/nope").status_code == 404



def test_ok_after_a_result_is_rejected_and_keeps_the_result(client):
    evs = sse(client.post("/api/chat", json={"preset_id": "scn_reuse_eylea_jp", "guided_id": None, "choice_id": None}))
    conv = evs[0]["id"]
    before = client.get(f"/api/conversations/{conv}").json()

    evs = sse(client.post("/api/chat", json={"conversation_id": conv, "message": "ok"}))
    assert not [e for e in evs if e["type"] == "stage"]  # no new run started
    msg = next(e for e in evs if e["type"] == "message")
    assert msg["kind"] == "retry" and msg["verdict"] == "meaningless" and msg["suggestions"]
    assert evs[-1] == {**evs[-1], "type": "done", "state": "idle"}

    after = client.get(f"/api/conversations/{conv}").json()
    assert len(after["runs"]) == len(before["runs"]) and after["intent"] == before["intent"] and after["plan"] == before["plan"]
    assert after["title"] == before["title"]


@pytest.mark.parametrize("text,verdict", [("thanks", "meaningless"), ("asdfgh", "meaningless"), ("???", "meaningless"),
                                          ("What is the weather in Germany?", "off_topic"), ("Tell me a joke", "off_topic"),
                                          ("Who won the match yesterday", "off_topic")])
def test_new_chat_rejects_unusable_messages_and_stays_out_of_history(client, text, verdict):
    evs = sse(client.post("/api/chat", json={"message": text}))
    assert next(e for e in evs if e["type"] == "message")["verdict"] == verdict
    assert client.get("/api/conversations").json() == []
    audit = client.get("/api/agent-runs", params={"conversation_id": evs[0]["id"]}).json()
    assert [a["stage"] for a in audit] == ["relevance"]

    # Trying again in the same chat works, and the rejected message is not part of it.
    evs = sse(client.post("/api/chat", json={"conversation_id": evs[0]["id"], "message": "I need net sales and gross-to-net"}))
    saved = client.get(f"/api/conversations/{evs[0]['id']}").json()
    assert saved["title"] == "I need net sales and gross-to-net" and saved["state"] == "clarifying"


@pytest.mark.parametrize("answer,verdict", [("ok", "meaningless"), ("I don't know", "meaningless"), ("Mars", "not_enough"),
                                            ("Tell me a joke", "off_topic")])
def test_bad_answer_asks_the_same_question_again(client, answer, verdict):
    evs = sse(client.post("/api/chat", json={"message": "I need net sales and gross-to-net"}))
    conv, question = evs[0]["id"], next(e for e in evs if e["type"] == "message")
    saved = client.get(f"/api/conversations/{conv}").json()

    evs = sse(client.post("/api/chat", json={"conversation_id": conv, "message": answer}))
    retry = next(e for e in evs if e["type"] == "message")
    assert retry["verdict"] == verdict and retry["content"].endswith(question["content"])
    assert retry["suggestions"] == question["suggestions"] and evs[-1]["state"] == "clarifying"
    again = client.get(f"/api/conversations/{conv}").json()
    assert again["asked"] == saved["asked"] and again["intent"] == saved["intent"]

    # A real answer then carries on, and the rejected one never reaches the intent.
    evs = sse(client.post("/api/chat", json={"conversation_id": conv, "message": "Germany"}))
    assert next(e for e in evs if e["type"] == "message").get("kind") != "retry"
    final = client.get(f"/api/conversations/{conv}").json()
    assert answer not in final["intent"].get("unmatched_terms", []) and final["intent"]["filters"]["market"] == ["DE"]


KERENDIA = "I need a new Kerendia management report for monthly performance in {}"


def answer_until_decided(client, text, answers=("Track sales performance", "Normal: no fixed deadline")):
    evs = sse(client.post("/api/chat", json={"message": text}))
    for answer in answers:
        if any(e.get("stage") == "decision" for e in evs):
            break
        evs = sse(client.post("/api/chat", json={"conversation_id": evs[0]["id"], "message": answer}))
    return evs


def test_country_outside_the_catalog_recommends_a_new_report(client):
    evs = answer_until_decided(client, KERENDIA.format("Vietnam"))
    d = stage(evs, "decision")["data"]
    assert d["decision"] == "new_build" and d["recommendation"]["value"] == "new_build"
    assert "Vietnam" in d["reason"] and d["target_model_id"]
    assert d["replaces"] == [] and d["flags"] == []  # it replaces nobody's report in another country
    assert "preview" not in d  # other countries' numbers must not stand in for Vietnam
    assert "Vietnam" in next(e for e in evs if e["type"] == "message" and e.get("kind") == "result")["content"]

    # No report is said to fit, not even a Global one.
    assert all(c["scope_score"] < 0.75 for c in stage(evs, "discovery")["data"]["candidates"])
    # An earlier request for other places is not "similar".
    assert not [g for g in d["triage"]["similar"]["similar"] if "EMEA" in g["text"]]

    body = client.post("/api/v2/classify", json={"request": KERENDIA.format("Vietnam")}).json()
    assert body["market"] == ["Vietnam"] and body["recommendation"]["value"] == "new_build" and body["not_available"] == []


def test_country_in_the_catalog_still_uses_its_report(client):
    d = stage(answer_until_decided(client, KERENDIA.format("Japan"), ("Track sales performance", "All available workbook months")), "decision")["data"]
    assert d["decision"] != "not_feasible" and "Japan" not in d["reason"]
    assert d["decision"] == "new_build" or "JP" in d["candidate"]["scope_note"] or "Global" in d["candidate"]["scope_note"]


def test_a_country_can_be_given_as_the_answer(client):
    evs = sse(client.post("/api/chat", json={"message": "I need net sales and gross-to-net"}))
    evs = sse(client.post("/api/chat", json={"conversation_id": evs[0]["id"], "message": "Vietnam"}))
    assert next(e for e in evs if e["type"] == "message").get("kind") != "retry"


def test_a_report_held_for_human_review_is_not_picked_to_migrate(client):
    d = stage(sse(client.post("/api/chat", json={"preset_id": "req_migrate_xarelto", "guided_id": None, "choice_id": None})), "decision")["data"]
    chosen = cat.asset_by_id(d["candidate"]["asset_id"])
    assert d["decision"] == "migrate" and chosen["migration"]["recommended_path_candidate"] != "HUMAN_REVIEW"
    assert d["candidate"]["owner"] == chosen["owner"]
    # The step beside the card agrees with the card about this report.
    rows = {r["id"]: r for r in stage(sse(client.post("/api/chat", json={"preset_id": "req_migrate_xarelto", "guided_id": None, "choice_id": None})), "migration")["data"]["step"]["data"]["assets"]}
    assert rows[chosen["id"]]["recommendation"] != "review"


def test_recommendation_is_human_review_when_nothing_else_can_move():
    from app.decision import Decision, data_availability, decide, rank_candidates
    from app.steps import RECOMMENDATIONS

    cat.reset_catalog()
    assets = [{**a, "migration": {**(a.get("migration") or {}), "recommended_path_candidate": "HUMAN_REVIEW"}, "lifecycle": "active", "views_90d": 2000}
              if a["platform"] == "Tableau" else a for a in cat.CATALOG["assets"]]
    catalog = {**cat.CATALOG, "assets": assets}
    intent = {"question": "Replace our Xarelto Tableau workbook", "measures": ["net_sales"], "dimensions": [], "filters": {"product": ["Xarelto"]},
              "migration": {"from": "Tableau"}, "unmatched_terms": []}
    result = decide(rank_candidates(intent, catalog), data_availability(intent, catalog), intent, catalog)
    if result.decision != Decision.REUSE:  # a governed Power BI report, when there is one, still comes first
        assert result.decision == Decision.REVIEW and result.candidate and result.replaces == []
    assert RECOMMENDATIONS["review"][1] == "Human review"


def test_new_build_names_the_shared_model_and_its_owner(client):
    d = stage(sse(client.post("/api/chat", json={"preset_id": "req_finance_gtn", "guided_id": None, "choice_id": None})), "decision")["data"]
    assert d["decision"] == "new_build"
    model = cat.model_by_id(d["target_model_id"])
    assert d["target_model"] == {"id": model["id"], "name": model["name"], "owner": model["owner"], "owner_status": model["owner_status"]}


def test_only_saved_accepted_messages_carry_their_history_summary():
    import json
    from fastapi.testclient import TestClient
    from app.main import app

    def events(res):
        return [json.loads(line[6:]) for line in res.text.splitlines() if line.startswith("data: ")]

    with TestClient(app) as c:
        rejected = events(c.post("/api/chat", json={"message": "asdf qwer"}))
        assert [e for e in rejected if e["type"] == "user_message"] and not any("history" in e for e in rejected)
        cid = rejected[0]["id"]
        assert c.get(f"/api/conversations/{cid}").status_code == 404  # a chat holding only rejected input is not saved
        accepted = events(c.post("/api/chat", json={"message": "Show monthly net sales for Nubeqa in Germany."}))
        msg = next(e for e in accepted if e["type"] == "user_message")
        saved = c.get(f"/api/conversations/{accepted[0]['id']}").json()
        assert msg["history"] == {"_id": saved["_id"], "title": "Show monthly net sales for Nubeqa in Germany.",
                                  "updated_at": msg["history"]["updated_at"]}
        assert all("history" not in e for run in saved["runs"] for e in run["events"])  # the stored transcript is unchanged
        guided = events(c.post("/api/chat", json={"message": "", "guided_id": "nubeqa-sales-shipments"}))
        assert next(e for e in guided if e["type"] == "user_message")["history"]["_id"] == guided[0]["id"]
        answer = events(c.post("/api/chat", json={"conversation_id": guided[0]["id"], "message": "", "choice_id": "a"}))
        assert next(e for e in answer if e["type"] == "user_message")["history"]["_id"] == guided[0]["id"]
        wrong = events(c.post("/api/chat", json={"conversation_id": guided[0]["id"], "message": "nonsense"}))
        assert not any("history" in e for e in wrong)
