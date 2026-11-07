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


def test_each_ask_stage_starts_before_its_operation_and_completes_with_its_result(monkeypatch):
    """Spies on the real helpers: every stage's running event comes before its own operation, its done after it, and
    the catalog ranking, availability and decision run exactly once for the turn."""
    from app import assessment
    order, calls = [], {"rank": 0, "availability": 0, "decide": 0}

    def spy(name, fn, counter=None):
        def wrapped(*a, **k):
            order.append("op:" + name)
            if counter:
                calls[counter] += 1
            return fn(*a, **k)
        return wrapped

    for name, attr in (("kpis", "resolve_kpis"), ("lineage", "trace_lineage"), ("governance", "check_trust"),
                       ("migration", "handle_migration"), ("discovery", "find_analytics")):
        monkeypatch.setattr(assessment, attr, spy(name, getattr(assessment, attr)))
    monkeypatch.setattr(assessment, "rank_candidates", spy("rank", assessment.rank_candidates, "rank"))
    monkeypatch.setattr(assessment, "data_availability", spy("availability", assessment.data_availability, "availability"))
    monkeypatch.setattr(assessment, "decide", spy("decide", assessment.decide, "decide"))
    real_explain = pipeline_module.explain

    async def explaining(*a, **k):
        order.append("op:explain")
        return await real_explain(*a, **k)
    monkeypatch.setattr(pipeline_module, "explain", explaining)

    async def run():
        with TestClient(app):
            async for e in app.state.pipeline.chat(None, "", "scn_reuse_lynkuet_es"):
                if e["type"] == "stage":
                    order.append(f"{e['stage']}:{e['status']}")
                elif e["type"] == "done":
                    order.append("done")
    asyncio.run(run())
    i = order.index
    for stage in ("kpis", "lineage", "governance", "migration"):
        assert i(f"{stage}:running") < i("op:" + stage) < i(f"{stage}:done"), stage
    assert i("discovery:running") < i("op:rank") < i("op:decide") < i("op:discovery") < i("discovery:done")
    assert i("kpis:done") < i("discovery:running") and i("migration:done") < i("decision:running") < i("op:explain") < i("decision:done")
    assert i("decision:done") < i("actions:running") < i("actions:done") < i("done")
    assert calls == {"rank": 1, "availability": 1, "decide": 1}  # one shared assessment, no repeated catalog scans


def test_a_live_stage_reaches_the_client_before_its_work_finishes(monkeypatch):
    """A held operation: the discovery stage's running event is already out while the ranking is still blocked."""
    import threading
    from app import assessment
    gate, started = threading.Event(), threading.Event()
    real = assessment.rank_candidates

    def held(*a, **k):
        started.set()
        assert gate.wait(5)
        return real(*a, **k)
    monkeypatch.setattr(assessment, "rank_candidates", held)

    async def run():
        seen = []
        with TestClient(app):
            agen = app.state.pipeline.chat(None, "", "scn_reuse_lynkuet_es")
            async for e in agen:
                seen.append((e["type"], e.get("stage"), e.get("status")))
                if e.get("stage") == "discovery" and e.get("status") == "running":
                    break
            nxt = asyncio.ensure_future(agen.__anext__())
            await asyncio.to_thread(started.wait, 5)
            await asyncio.sleep(0.05)
            assert not nxt.done()  # the stage is shown running; its result has not been produced
            gate.set()
            e = await nxt
            assert (e["stage"], e["status"]) == ("discovery", "done")
            async for _ in agen:
                pass
        return seen
    seen = asyncio.run(run())
    assert ("stage", "kpis", "done") in seen and ("stage", "discovery", "done") not in seen


def test_a_clarification_does_not_run_the_assessment(monkeypatch):
    from app import assessment
    ran = []
    monkeypatch.setattr(assessment, "rank_candidates", lambda *a, **k: ran.append(1) or [])
    with TestClient(app) as c:
        evs = events(c.post("/api/chat", json={"message": "Please build a new report for market access coverage and reimbursement status by product."}))
    assert any(e.get("stage") == "intent" and e.get("status") == "waiting" for e in evs)
    assert not ran and not any(e.get("stage") in ("kpis", "discovery") for e in evs)


def test_done_is_sent_only_after_the_run_is_saved(monkeypatch):
    with TestClient(app) as c:
        store = app.state.pipeline.store
        real = store.save
        log = []

        async def saving(conv):
            evs_ = conv["runs"][-1]["events"] if conv.get("runs") else []
            log.append(("save", evs_[-1]["type"] if evs_ else None))
            return await real(conv)
        monkeypatch.setattr(store, "save", saving)
        evs = events(c.post("/api/chat", json={"message": "", "preset_id": "scn_reuse_lynkuet_es"}))
    assert evs[-1]["type"] == "done"
    assert ("save", "done") in log  # the saved run already holds its terminal event when the client receives it


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
        decision = next(e for e in done if e["type"] == "stage" and e["stage"] == "decision" and e["status"] == "done")["data"]
        assert decision["decision"] == "new_build"
        assert c.get(f"/api/conversations/{cid}").json()["runs"][-1]["guided"]["window"]["start"] == "2026-01"
