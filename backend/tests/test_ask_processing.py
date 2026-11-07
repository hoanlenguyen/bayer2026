"""Ask's processing signals follow the real work: a phase is announced before its operation runs, results follow it,
nothing waits on purpose, and guided period answers resolve against the dates offered for that run."""
import asyncio
import json
import os
import time

from fastapi.testclient import TestClient

from app import catalog, guided_examples, pipeline as pipeline_module
from app.main import app


def events(res):
    return [json.loads(line[6:]) for line in res.text.splitlines() if line.startswith("data: ")]


def test_catalog_phase_is_yielded_before_the_assessment_runs(monkeypatch):
    order = []
    real = pipeline_module.analyse

    def recording(intent):
        order.append("analyse ran")
        return real(intent)

    monkeypatch.setattr(pipeline_module, "analyse", recording)

    async def run():
        with TestClient(app):
            p = app.state.pipeline
            async for e in p.chat(None, "", "scn_reuse_lynkuet_es"):
                order.append(e["type"] + (":" + e["phase"] if e["type"] == "processing" else "")
                             + (":" + e["stage"] + ":" + e["status"] if e["type"] == "stage" else ""))
    asyncio.run(run())
    assert order.index("processing:catalog") < order.index("analyse ran") < order.index("stage:kpis:done")
    assert order.index("stage:decision:done") < order.index("done")
    # completed evidence follows the work: no catalog step is reported done before the assessment ran
    assert all(order.index(s) > order.index("analyse ran") for s in order if s.startswith("stage:") and s.endswith(":done")
               and s.split(":")[1] in ("kpis", "discovery", "lineage", "governance", "migration"))


def test_a_deployed_stage_delay_does_not_slow_ask(monkeypatch):
    monkeypatch.setenv("STAGE_DELAY", "5")
    with TestClient(app) as c:
        start = time.perf_counter()
        evs = events(c.post("/api/chat", json={"message": "", "preset_id": "scn_reuse_lynkuet_es"}))
        assert time.perf_counter() - start < 3
        assert any(e["type"] == "stage" and e["stage"] == "decision" for e in evs)
        conv = c.get(f"/api/conversations/{evs[0]['id']}").json()
        assert not any(e["type"] == "processing" for run in conv["runs"] for e in run["events"])  # signals are not stored


def test_guided_turns_signal_their_work_and_return_the_verified_scope():
    with TestClient(app) as c:
        first = events(c.post("/api/chat", json={"message": "", "guided_id": "kerendia-access-shipments"}))
        assert [e["phase"] for e in first if e["type"] == "processing"] == ["scope"]
        q1 = next(e for e in first if e["type"] == "message")
        assert q1["facts"] == {"product": "Kerendia", "markets": ["Italy", "Spain"], "measures": ["Market Access Coverage", "Units Shipped"]}
        second = events(c.post("/api/chat", json={"conversation_id": first[0]["id"], "message": "", "choice_id": "b"}))
        kinds = [e["type"] + (":" + e.get("phase", "") if e["type"] == "processing" else "") for e in second]
        assert kinds.index("processing:periods") < kinds.index("message")
        q2 = next(e for e in second if e["type"] == "message")
        assert [(o["start"], o["end"], o["count"]) for o in q2["choices"]] == [("2026-01", "2026-10", 10), ("2026-05", "2026-10", 6)]


def test_a_period_answer_never_silently_changes_the_offered_dates(monkeypatch):
    rows = catalog.SHEETS["product_market_monthly"]
    with TestClient(app) as c:
        cid = events(c.post("/api/chat", json={"message": "", "guided_id": "nubeqa-sales-shipments"}))[0]["id"]
        events(c.post("/api/chat", json={"conversation_id": cid, "message": "", "choice_id": "a"}))
        # after the dates were offered, the workbook loses January for France (row 12): "all" no longer means Jan to Oct
        monkeypatch.setitem(rows[10], "units_shipped_syn", None)
        evs = events(c.post("/api/chat", json={"conversation_id": cid, "message": "", "choice_id": "all"}))
        msg = [e for e in evs if e["type"] == "message"][-1]
        assert "coverage changed" in msg["content"] and not any(e["type"] == "stage" and e["stage"] == "decision" for e in evs)
        assert [(o["id"], o["start"], o["count"]) for o in msg["choices"]] == [("all", "2026-02", 9), ("last6", "2026-05", 6)]
        conv = c.get(f"/api/conversations/{cid}").json()
        assert conv["state"] == "clarifying" and conv["runs"][-1]["guided"]["step"] == "period"
        # the re-offered dates are the ones used
        done = events(c.post("/api/chat", json={"conversation_id": cid, "message": "", "choice_id": "all"}))
        assert any(e["type"] == "stage" and e["stage"] == "decision" for e in done)
        assert c.get(f"/api/conversations/{cid}").json()["runs"][-1]["guided"]["window"] == {"id": "all", "start": "2026-02", "end": "2026-10", "count": 9}


def test_a_coverage_gap_after_the_offer_ends_the_example_with_a_way_out(monkeypatch):
    rows = catalog.SHEETS["product_market_monthly"]
    with TestClient(app) as c:
        cid = events(c.post("/api/chat", json={"message": "", "guided_id": "nubeqa-sales-shipments"}))[0]["id"]
        events(c.post("/api/chat", json={"conversation_id": cid, "message": "", "choice_id": "b"}))
        monkeypatch.setitem(rows[14], "units_shipped_syn", None)  # May, France: a gap inside both windows
        evs = events(c.post("/api/chat", json={"conversation_id": cid, "message": "", "choice_id": "last6"}))
        msg = [e for e in evs if e["type"] == "message"][-1]
        assert "New question" in msg["content"] and not any(e["type"] == "stage" and e["stage"] == "decision" for e in evs)


def test_an_older_saved_run_without_offered_dates_gets_a_fresh_period_question():
    with TestClient(app) as c:
        cid = events(c.post("/api/chat", json={"message": "", "guided_id": "lynkuet-stock-delivery"}))[0]["id"]
        events(c.post("/api/chat", json={"conversation_id": cid, "message": "", "choice_id": "b"}))
        store = app.state.pipeline.store
        conv = c.portal.call(store.get, cid)
        conv["runs"][-1]["guided"].pop("offered")  # the format saved before offered dates were stored
        c.portal.call(store.save, conv)
        evs = events(c.post("/api/chat", json={"conversation_id": cid, "message": "", "choice_id": "all"}))
        msg = [e for e in evs if e["type"] == "message"][-1]
        assert "checked again" in msg["content"] and [o["id"] for o in msg["choices"]] == ["all", "last6"]
        done = events(c.post("/api/chat", json={"conversation_id": cid, "message": "", "choice_id": "all"}))
        decision = next(e for e in done if e["type"] == "stage" and e["stage"] == "decision")["data"]
        assert decision["decision"] == "new_build"
        assert c.get(f"/api/conversations/{cid}").json()["runs"][-1]["guided"]["window"]["start"] == "2026-01"
