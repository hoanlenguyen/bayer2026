"""The approved build streams its real checkpoints: each one is announced before its operation and completed with that
operation's facts, success comes only from the committed draft binding, and retries converge on one dashboard."""
import asyncio
import json
import threading

from fastapi.testclient import TestClient

from app import dashboard_routes
from app.main import app
from tests.test_guided_examples import guided_run

STREAM = {"Accept": "text/event-stream"}


def frames(res):
    assert res.status_code == 200 and res.headers["content-type"].startswith("text/event-stream"), res.text
    return [json.loads(line[6:]) for line in res.text.splitlines() if line.startswith("data: ")]


def ready(c, example="nubeqa-sales-shipments"):
    cid, run_id, _, _ = guided_run(c, example, "a", "all")
    path = f"/api/conversations/{cid}/runs/{run_id}/dashboard"
    state = c.get(path).json()
    assert state["status"] == "ready"
    return path, {"version": state["version"], "review_token": state["review_token"]}


def test_stream_reports_each_checkpoint_around_its_operation_and_ends_with_one_result(monkeypatch):
    order = []
    for name in ("select_source", "calculate"):
        real = getattr(dashboard_routes, name)
        monkeypatch.setattr(dashboard_routes, name, lambda *a, _r=real, _n=name, **k: order.append("op:" + _n) or _r(*a, **k))
    with TestClient(app) as c:
        path, body = ready(c)
        store = app.state.pipeline.store
        real_publish = store.publish_dashboard_once

        async def publishing(doc):
            order.append("op:publish")
            return await real_publish(doc)
        monkeypatch.setattr(store, "publish_dashboard_once", publishing)
        order.clear()  # the review read prepared its own preview; only the build's own work counts below
        cid, rid = path.split("/")[3], path.split("/")[5]
        evs = []

        async def run():
            async for e in dashboard_routes.build_events(cid, rid, body["version"], body["review_token"], store, {"name": "t"}):
                evs.append(e)
                order.append(f"{e['type']}:{e.get('phase', '')}:{e.get('status', '')}")
        asyncio.run(run())
    i = order.index
    assert order.count("op:select_source") == 1 and order.count("op:calculate") == 1  # one snapshot, one calculation
    assert i("build_stage:source:running") < i("op:select_source") < i("build_stage:source:complete")
    assert i("build_stage:calculate:running") < i("op:calculate") < i("build_stage:calculate:complete")
    assert i("build_stage:save:running") < i("op:publish") < i("build_stage:save:complete") < i("build_result::")
    assert [e["type"] for e in evs].count("build_result") == 1 and evs[-1]["type"] == "build_result"
    source = next(e for e in evs if e.get("phase") == "source" and e["status"] == "complete")["facts"]
    assert source["rows"] == 20 and source["months"] == 10 and source["first"] == "January 2026"
    result = evs[-1]["state"]
    assert result["status"] == "built" and result["dashboard_id"].startswith("dash_")


def test_json_and_stream_build_the_same_dashboard_and_a_committed_retry_replays_without_work():
    with TestClient(app) as c:
        path, body = ready(c)
        built = c.post(path + "/build", json=body).json()  # default contract: plain JSON
        assert built["status"] == "built"
        again = frames(c.post(path + "/build", json=body, headers=STREAM))
        assert [e["type"] for e in again] == ["build_stage", "build_result"]  # only the brief check ran
        assert again[-1]["replayed"] is True and again[-1]["state"]["dashboard_id"] == built["dashboard_id"]


def test_a_stale_approval_ends_the_stream_with_a_review_error_and_json_keeps_409(monkeypatch):
    with TestClient(app) as c:
        path, body = ready(c)
        stale = {**body, "review_token": "0" * 16}
        evs = frames(c.post(path + "/build", json=stale, headers=STREAM))
        assert evs[-1]["type"] == "build_error" and evs[-1]["kind"] == "review" and evs[-1]["status"] == 409
        assert not any(e.get("phase") == "source" and e.get("status") == "complete" for e in evs)
        assert c.post(path + "/build", json=stale).status_code == 409


def test_a_held_source_check_is_shown_running_until_it_returns():
    gate, started = threading.Event(), threading.Event()
    real = dashboard_routes.select_source

    def held(req):
        started.set()
        assert gate.wait(5)
        return real(req)

    async def run(path, body):
        dashboard_routes.select_source = held
        try:
            store = app.state.pipeline.store
            agen = dashboard_routes.build_events(path[0], path[1], body["version"], body["review_token"], store, {"name": "t"})
            seen = []
            async for e in agen:
                seen.append((e.get("phase"), e.get("status")))
                if seen[-1] == ("source", "running"):
                    break
            nxt = asyncio.ensure_future(agen.__anext__())
            await asyncio.to_thread(started.wait, 5)
            await asyncio.sleep(0.05)
            assert not nxt.done()  # the source row is running and no evidence was reported for it
            gate.set()
            e = await nxt
            assert (e["phase"], e["status"]) == ("source", "complete")
            async for _ in agen:
                pass
        finally:
            dashboard_routes.select_source = real

    with TestClient(app) as c:
        p, body = ready(c)
        cid, rid = p.split("/")[3], p.split("/")[5]
        asyncio.run(run((cid, rid), body))
        assert c.get(p).json()["status"] == "built"


def test_a_published_but_unbound_dashboard_is_not_built_and_a_retry_binds_the_same_one(monkeypatch):
    with TestClient(app) as c:
        path, body = ready(c)
        store = app.state.pipeline.store
        real = store.advance_dashboard

        async def losing_binding(doc, previous):
            if doc.get("built_id"):
                return False  # the publication happened, the binding did not commit
            return await real(doc, previous)
        monkeypatch.setattr(store, "advance_dashboard", losing_binding)
        evs = frames(c.post(path + "/build", json=body, headers=STREAM))
        assert evs[-1]["type"] == "build_error" and not any(e["type"] == "build_result" for e in evs)
        assert not any(e.get("phase") == "save" and e.get("status") == "complete" for e in evs)
        state = c.get(path).json()
        assert state["status"] == "ready" and state["dashboard_id"] is None  # an artifact alone never counts as built
        published = [d["id"] for d in c.get("/api/dashboards").json()["items"]]
        assert len(published) == 1
        monkeypatch.setattr(store, "advance_dashboard", real)
        retry = c.post(path + "/build", json=body).json()  # the same approval, at the version the visitor reviewed
        assert retry["status"] == "built" and retry["dashboard_id"] == published[0]
        assert [d["id"] for d in c.get("/api/dashboards").json()["items"]] == published  # still one dashboard


def test_two_concurrent_approvals_of_one_run_converge_on_one_dashboard():
    with TestClient(app) as c:
        path, body = ready(c)
        store = app.state.pipeline.store
        cid, rid = path.split("/")[3], path.split("/")[5]

        async def both():
            async def one():
                out = None
                async for e in dashboard_routes.build_events(cid, rid, body["version"], body["review_token"], store, {"name": "t"}):
                    if e["type"] == "build_result":
                        out = e["state"]["dashboard_id"]
                return out
            return await asyncio.gather(one(), one())
        a, b = asyncio.run(both())
        assert a == b and len(c.get("/api/dashboards").json()["items"]) == 1
