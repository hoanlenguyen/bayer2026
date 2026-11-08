"""Guided dashboard examples on the Ask start screen: all 20 paths through the real streaming chat, the saved
conversation, the builder's review and build, and the saved dashboard; plus the edge cases around them."""
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import catalog, guided_examples
from app.main import app

PERIODS = {"all": [f"2026-{m:02}" for m in range(1, 11)], "last6": [f"2026-{m:02}" for m in range(5, 11)]}
OCTOBER = {  # spot checks from the checked-in workbook: (country, values, row)
    "nubeqa-sales-shipments": [("France", {"net_sales": 37.58, "units_shipped": 33941}, 21),
                               ("Germany", {"net_sales": 13.96, "units_shipped": 12635}, 11)],
    "lynkuet-stock-delivery": [("France", {"inventory_coverage": 3.87, "on_time_in_full": 86.0}, 581),
                               ("Germany", {"inventory_coverage": 9.85, "on_time_in_full": 87.3}, 571)],
    "kerendia-access-shipments": [("Italy", {"market_access_coverage": 92.3, "units_shipped": 68744}, 171),
                                  ("Spain", {"market_access_coverage": 36.4, "units_shipped": 41339}, 181)],
    "eylea-sales-delivery": [("Canada", {"net_sales": 23.22, "on_time_in_full": 83.2}, 371),
                             ("United States", {"net_sales": 33.20, "on_time_in_full": 87.2}, 361)],
    "xarelto-stock-shipments": [("Brazil", {"inventory_coverage": 2.73, "units_shipped": 21458}, 551),
                                ("Mexico", {"inventory_coverage": 4.15, "units_shipped": 76269}, 561)],
}
MATRIX = [(e["id"], p, period) for e in guided_examples.EXAMPLES for p in ("a", "b") for period in ("all", "last6")]


def events(res):
    assert res.status_code == 200, res.text
    return [json.loads(line[6:]) for line in res.text.splitlines() if line.startswith("data: ")]


def questions(evs):
    return [e for e in evs if e["type"] == "message" and e.get("kind") == "question"]


def start(c, example_id):
    evs = events(c.post("/api/chat", json={"message": "", "guided_id": example_id}))
    return evs[0]["id"], evs


def answer(c, cid, choice_id, text=""):
    return events(c.post("/api/chat", json={"conversation_id": cid, "message": text, "choice_id": choice_id}))


def guided_run(c, example_id, purpose, period):
    cid, first = start(c, example_id)
    second = answer(c, cid, purpose)
    third = answer(c, cid, period)
    decision = next(e for e in third if e["type"] == "stage" and e["stage"] == "decision" and e["status"] == "done")["data"]
    return cid, decision["run_id"], (first, second, third), decision


def build(c, cid, run_id):
    path = f"/api/conversations/{cid}/runs/{run_id}/dashboard"
    state = c.get(path).json()
    res = c.post(path + "/build", json={"version": state["version"], "review_token": state["review_token"]})
    assert res.status_code == 200, res.text
    return state, res.json(), path


FRONTEND_LIST = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "guidedExamples.ts"


def test_frontend_chips_match_the_registry():
    """The start screen ships its chips in the bundle (no request); they must be the registry's, in order."""
    found = re.findall(r'id: "([^"]+)", placement: "(visible|more)",\s*text: "([^"]+)"', FRONTEND_LIST.read_text())
    assert found == [(e["id"], e["placement"], e["text"]) for e in guided_examples.EXAMPLES]
    assert all(guided_examples.get(e["id"]) for e in guided_examples.EXAMPLES)  # every shipped chip is offered


def test_guided_examples_endpoint_is_gone():
    with TestClient(app) as c:
        assert c.get("/api/guided-examples").status_code in (404, 405)


def test_registry_feeds_the_start_screen_in_order():
    listed = guided_examples.public()
    assert [e["id"] for e in listed["examples"]] == [e["id"] for e in guided_examples.EXAMPLES]
    assert [e["placement"] for e in listed["examples"]] == ["visible", "visible", "more", "more", "more"]
    assert [e["text"] for e in listed["examples"]] == [e["text"] for e in guided_examples.EXAMPLES]
    assert listed["purpose_question"] == "What decision will you make using this dashboard?"
    for example in listed["examples"]:  # resolved per comparison from the months it fully covers
        assert [p["label"] for p in example["periods"]] == ["All available workbook months", "Last 6 workbook months"]
        assert [p["detail"] for p in example["periods"]] == ["January 2026 to October 2026, 10 months", "May 2026 to October 2026, 6 months"]
        assert [(p["start"], p["end"], p["count"]) for p in example["periods"]] == [("2026-01", "2026-10", 10), ("2026-05", "2026-10", 6)]
    assert all(guided_examples.verify(e) is None for e in guided_examples.EXAMPLES)


@pytest.mark.parametrize("example_id,purpose,period", MATRIX)
def test_every_guided_path_builds_the_reviewed_comparison(example_id, purpose, period):
    ex = guided_examples.BY_ID[example_id]
    _, label, lead = next(p for p in ex["purposes"] if p[0] == purpose)
    C = catalog.CATALOG
    with TestClient(app) as c:
        cid, run_id, (first, second, third), decision = guided_run(c, example_id, purpose, period)
        # exactly two ordered questions, each with its two offered choices
        q1, q2 = questions(first), questions(second)
        assert [q["content"] for q in q1 + q2] == [guided_examples.PURPOSE_QUESTION, guided_examples.PERIOD_QUESTION]
        assert [o["id"] for o in q1[0]["choices"]] == ["a", "b"] and [o["id"] for o in q2[0]["choices"]] == ["all", "last6"]
        assert not questions(third) and decision["decision"] == "new_build"
        conv = c.get(f"/api/conversations/{cid}").json()
        g = conv["runs"][-1]["guided"]
        assert {k: g[k] for k in ("id", "step", "purpose", "period")} == {"id": example_id, "step": "done", "purpose": purpose, "period": period}
        # the run keeps the exact dates it offered, and the answer used those dates
        assert [o["id"] for o in g["offered"]] == ["all", "last6"]
        assert g["window"] == {k: next(o for o in g["offered"] if o["id"] == period)[k] for k in ("id", "start", "end", "count")}
        assert conv["intent"]["decision"] == label and conv["intent"]["dashboard_brief"]["guided"]["lead_measure"] == lead

        # review is ready, reflects this branch, and nothing is published before Build
        path = f"/api/conversations/{cid}/runs/{run_id}/dashboard"
        state = c.get(path).json()
        assert state["status"] == "ready" and state["question"] is None and state["reason"] is None and state["review_token"]
        assert state["requirements"]["period"] == {"start": PERIODS[period][0], "end": PERIODS[period][-1]}
        assert state["requirements"]["lead_measure"] == lead and state["requirements"]["decision_goal"] == label
        assert state["summary"][0] == f"Purpose: {label}" and "lead metric" in state["summary"][2]
        assert c.get("/api/dashboards").json()["items"] == []
        built = c.post(path + "/build", json={"version": state["version"], "review_token": state["review_token"]}).json()
        assert built["status"] == "built" and not built["reused"]
        again = c.post(path + "/build", json={"version": state["version"], "review_token": state["review_token"]}).json()
        assert again["dashboard_id"] == built["dashboard_id"] and len(c.get("/api/dashboards").json()["items"]) == 1

        dash = c.get(f"/api/dashboards/{built['dashboard_id']}").json()
        countries = [C["markets"][m]["name"] for m in ex["markets"]]
        assert dash["presentation"] == "market_comparison" and dash["lead_measure"] == lead and dash["decision_goal"] == label
        assert sorted(g["label"] for g in dash["groups"]) == sorted(countries) and dash["market_order"] == countries
        assert [col["id"] for col in dash["columns"]] == ex["measures"] + (["sales_forecast"] if "net_sales" in ex["measures"] else [])
        rows = catalog.SHEETS["product_market_monthly"]
        for g in dash["groups"]:
            assert [p["period"] for p in g["points"]] == PERIODS[period]
            for p in g["points"]:
                assert len(p["source_rows"]) == 1
                row = rows[p["source_rows"][0] - 2]
                assert row["market_id"] in ex["markets"] and C["markets"][row["market_id"]]["name"] == g["label"]
                assert p["value_types"] == [row["value_type"]]
                for col in dash["columns"]:
                    assert p["values"][col["id"]] == round(row[col["field"]], 4)
        assert len({r["row"] for r in dash["source_records"]}) == 2 * len(PERIODS[period])
        for col in dash["columns"]:  # enough variation to draw a readable chart
            assert all(len({p["values"][col["id"]] for p in g["points"]}) > 1 for g in dash["groups"])
        # October spot check from the source
        for country, values, row_number in OCTOBER[example_id]:
            october = next(p for p in next(g for g in dash["groups"] if g["label"] == country)["points"] if p["period"] == "2026-10")
            assert october["source_rows"] == [row_number]
            assert all(october["values"][k] == pytest.approx(v) for k, v in values.items())


def test_invalid_and_out_of_order_answers_repeat_the_step_and_change_nothing():
    with TestClient(app) as c:
        cid, _ = start(c, "lynkuet-stock-delivery")
        before = c.get(f"/api/conversations/{cid}").json()
        for bad in ({"choice_id": "last6"}, {"choice_id": "z"}, {"choice_id": None, "message": "Show me net sales in Japan"}):
            evs = answer(c, cid, bad["choice_id"], bad.get("message", ""))
            retry = [e for e in evs if e["type"] == "message"][-1]
            assert retry["kind"] == "retry" and [o["id"] for o in retry["choices"]] == ["a", "b"]
        after = c.get(f"/api/conversations/{cid}").json()
        assert after["intent"] == before["intent"] and after["runs"][-1]["guided"] == before["runs"][-1]["guided"]
        assert after["state"] == "clarifying" and after["asked"] == 1
        # the exact label works as well as the ID; free text never reaches KPI or scope extraction
        evs = answer(c, cid, None, "assess delivery reliability by market")
        assert questions(evs)[0]["content"] == guided_examples.PERIOD_QUESTION
        assert c.get(f"/api/conversations/{cid}").json()["intent"]["measures"] == ["inventory_coverage", "on_time_in_full"]


def test_bad_starts_are_rejected_before_anything_is_saved():
    with TestClient(app) as c:
        assert c.post("/api/chat", json={"message": "", "guided_id": "not-an-example"}).status_code == 400
        assert c.post("/api/chat", json={"message": "Something else entirely", "guided_id": "nubeqa-sales-shipments"}).status_code == 400
        assert c.post("/api/chat", json={"message": "", "guided_id": "nubeqa-sales-shipments", "preset_id": "req_exec_view"}).status_code == 400
        assert c.post("/api/chat", json={"message": "x", "choice_id": "a"}).status_code == 400
        assert c.get("/api/conversations").json() == []


def test_refresh_restores_the_pending_question_and_the_review():
    with TestClient(app) as c:
        cid, _ = start(c, "kerendia-access-shipments")
        conv = c.get(f"/api/conversations/{cid}").json()
        last = conv["messages"][-1]
        assert conv["state"] == "clarifying" and last["content"] == guided_examples.PURPOSE_QUESTION and len(last["choices"]) == 2
        answer(c, cid, "b")
        third = answer(c, cid, "all")
        run_id = next(e for e in third if e["type"] == "stage" and e["stage"] == "decision" and e["status"] == "done")["data"]["run_id"]
        path = f"/api/conversations/{cid}/runs/{run_id}/dashboard"
        assert c.get(path).json() == c.get(path).json()  # reloading the review changes nothing
        assert c.get(path).json()["status"] == "ready"


def test_stale_token_after_a_source_change_is_rejected(monkeypatch):
    with TestClient(app) as c:
        cid, run_id, _, _ = guided_run(c, "eylea-sales-delivery", "a", "last6")
        path = f"/api/conversations/{cid}/runs/{run_id}/dashboard"
        state = c.get(path).json()
        monkeypatch.setitem(catalog.SHEETS["product_market_monthly"][369], "net_sales_m_eur_syn", 999.0)  # Canada, October (row 371)
        res = c.post(path + "/build", json={"version": state["version"], "review_token": state["review_token"]})
        assert res.status_code == 409 and c.get("/api/dashboards").json()["items"] == []


def test_a_built_dashboard_is_reused_next_time_and_a_retry_keeps_it():
    with TestClient(app) as c:
        cid, run_id, _, _ = guided_run(c, "xarelto-stock-shipments", "a", "all")
        state, first, path = build(c, cid, run_id)
        retry = c.post(path + "/build", json={"version": state["version"], "review_token": state["review_token"]}).json()
        assert retry["dashboard_id"] == first["dashboard_id"]  # same-run retry: idempotent
        # The same request again: the decision is Reuse of the saved dashboard, with a follow-up to give it an owner.
        cid2, run_id2, _, decision = guided_run(c, "xarelto-stock-shipments", "a", "all")
        assert decision["decision"] == "reuse" and decision["change_type"] == "saved_dashboard_reuse"
        assert decision["saved_dashboard"]["id"] == first["dashboard_id"] and decision["saved_dashboard"]["owner"] is None
        assert decision["saved_dashboard"]["url"] == f"/dashboards/{first['dashboard_id']}"
        discovery = next(e for e in c.get(f"/api/conversations/{cid2}").json()["runs"][-1]["events"]
                         if e.get("stage") == "discovery" and e.get("status") == "done")
        assert discovery["summary"].startswith("Already built in Ask") and discovery["data"]["step"]["data"]["built_in_ask"]["id"] == first["dashboard_id"]
        run = c.get(f"/api/conversations/{cid2}").json()["runs"][-1]
        proposals = next(e for e in run["events"] if e.get("stage") == "actions" and e.get("status") == "done")["data"]["proposals"]
        assert any(p["key"] == f"owner:{first['dashboard_id']}" and p["owner"] == "BI steward" for p in proposals)
        assert c.get(f"/api/conversations/{cid2}/runs/{run_id2}/dashboard").status_code in (200, 409)
        assert c.get(f"/api/conversations/{cid}/runs/{run_id}/dashboard").json()["status"] == "built"  # the first run reopens built
        assert len(c.get("/api/dashboards").json()["items"]) == 1  # nothing was built twice
        handoff = c.get(f"/api/conversations/{cid2}/runs/{run_id2}/handoff")
        assert handoff.status_code == 200, handoff.text
        receipt = handoff.json()["receipt"] if "receipt" in handoff.json() else handoff.json()
        assert receipt["saved_dashboard"]["id"] == first["dashboard_id"] and receipt.get("handoff_verdict") == "reuse"


def test_ordinary_ask_and_estate_scenarios_keep_their_outcomes():
    with TestClient(app) as c:
        outcomes = {}
        for preset in ("scn_reuse_lynkuet_es", "scn_reuse_eylea_jp", "req_migrate_xarelto"):
            evs = events(c.post("/api/chat", json={"message": "", "preset_id": preset}))
            outcomes[preset] = next(e for e in evs if e["type"] == "stage" and e["stage"] == "decision" and e["status"] == "done")["data"]["decision"]
        assert outcomes == {"scn_reuse_lynkuet_es": "reuse", "scn_reuse_eylea_jp": "review", "req_migrate_xarelto": "migrate"}
        # the same sentence typed into the composer is ordinary Ask, not a guided run
        evs = events(c.post("/api/chat", json={"message": guided_examples.BY_ID["nubeqa-sales-shipments"]["text"]}))
        q = questions(evs)
        assert q and "choices" not in q[0]
        conv = c.get(f"/api/conversations/{evs[0]['id']}").json()
        assert "guided" not in conv["runs"][-1]
