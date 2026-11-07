from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from app import catalog
from app.dashboard_builder import assemble, resolve
from app.main import app
from app.store import MemoryStore, MongoStore
from .fakes import AsyncMockDB


def seed(client, cid="conversation", *, intent=None, verdict="new_build", question="Build a monthly Nubeqa dashboard for France."):
    if intent is None:
        intent = {"measures": ["net_sales", "units_shipped"], "dimensions": ["month"], "grain": "month",
                  "decision": "Plan monthly stock allocation", "filters": {"product": ["Nubeqa"], "market": ["FR"]},
                  "dashboard_brief": {"period": {"start": "2026-01", "end": "2026-10"}}}
    run_id = "run"
    events = [{"type": "user_message", "content": question}, {"type": "stage", "stage": "intent", "status": "done", "data": intent},
              {"type": "stage", "stage": "decision", "status": "done", "data": {"decision": verdict}},
              {"type": "done", "state": "idle"}]
    conv = {"_id": cid, "runs": [{"id": run_id, "events": events}], "messages": [], "updated_at": "", "title": question}
    client.portal.call(app.state.pipeline.store.save, conv)
    return f"/api/conversations/{cid}/runs/{run_id}/dashboard"


def build(c, path):
    state = c.get(path).json()
    assert state["status"] in ("ready", "built"), state
    request = {"version": state["version"], "review_token": state["review_token"]}
    res = c.post(path + "/build", json=request)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "built"
    return res.json(), request


def test_source_bound_dashboard_is_immutable_retrievable_and_run_scoped(monkeypatch):
    with TestClient(app) as c:
        path = seed(c)
        ready = c.get(path).json()
        assert ready["status"] == "ready" and ready["question"] is None
        assert c.get("/api/dashboards").json()["items"] == []
        rows = catalog.SHEETS["product_market_monthly"]
        with monkeypatch.context() as mut:
            mut.setitem(rows[19], "net_sales_m_eur_syn", 500)
            assert c.post(path + "/build", json={"version": 0, "review_token": ready["review_token"]}).status_code == 409
        state, approved = build(c, path)
        did = state["dashboard_id"]
        dash = c.get("/api/dashboards/" + did).json()
        assert dash["period"] == {"start": "2026-01", "end": "2026-10"} and dash["scope"]["markets"] == ["France"]
        assert [p["source_rows"] for p in dash["groups"][0]["points"]] == [[n] for n in range(12, 22)]
        assert dash["groups"][0]["points"][-2]["values"] == {"net_sales": 3.85, "units_shipped": 12405}
        assert dash["groups"][0]["points"][-1]["values"] == {"net_sales": 37.58, "units_shipped": 33941}
        assert dash["source_records"][-1]["market_id"] == "FR" and dash["source_records"][-1]["net_sales_m_eur_syn"] == 37.58
        assert dash["source_records"][-1]["month"] == "2026-10-01"
        assert c.post(path + "/build", json=approved).json()["dashboard_id"] == did  # same-run retry: same dashboard
        other = seed(c, "different-chat")  # another run with the identical brief builds its own dashboard
        fresh = c.get(other).json()
        assert fresh["status"] == "ready" and not fresh["reused"] and fresh["dashboard_id"] is None
        assert fresh["review_token"] == approved["review_token"]  # same approved content, so the same review fingerprint
        second = build(c, other)[0]
        assert second["dashboard_id"] != did and not second["reused"] and len(c.get("/api/dashboards").json()["items"]) == 2
        assert c.get("/api/dashboards/" + second["dashboard_id"]).json()["conversation_id"] == "different-chat"
        c.delete("/api/conversations/conversation").raise_for_status()
        monkeypatch.setitem(rows[19], "net_sales_m_eur_syn", 999)
        assert c.get("/api/dashboards/" + did).json() == dash


def test_only_answer_the_current_question_and_require_explicit_kpi_narrowing():
    with TestClient(app) as c:
        intent = {"measures": ["net_sales", "units_shipped", "gross_to_net_rate"], "grain": "month",
                  "filters": {"market": ["FR"]}, "dimensions": ["month"], "decision": "Plan stock"}
        path = seed(c, intent=intent)
        assert c.get(path).json()["question"]["key"] == "metric_scope"
        assert c.post(path + "/build", json={"version": 0, "review_token": "not-reviewed"}).status_code == 409
        assert c.post(path + "/answers", json={"version": 0, "key": "period", "value": "2026-01"}).status_code == 409
        s1 = c.post(path + "/answers", json={"version": 0, "key": "metric_scope", "value": "available_only"}).json()
        assert s1["question"]["key"] == "products"
        assert c.get(path).json()["version"] == s1["version"]  # persisted answer
        assert c.post(path + "/answers", json={"version": 0, "key": "products", "value": ["P-NUB"]}).status_code == 409
        assert c.post(path + "/answers", json={"version": 1, "key": "products", "value": ["P-NUB", "all"]}).status_code == 422
        s2 = c.post(path + "/answers", json={"version": 1, "key": "products", "value": ["P-NUB"]}).json()
        assert s2["question"]["key"] == "period"
        assert c.post(path + "/answers", json={"version": 2, "key": "period", "value": {"start": "2027-01", "end": "2027-02"}}).status_code == 422
        s3 = c.post(path + "/answers", json={"version": 2, "key": "period", "value": {"start": "2026-09", "end": "2026-10"}}).json()
        assert s3["status"] == "ready" and s3["requirements"]["omitted_measures"] == ["gross_to_net_rate"]
        did = build(c, path)[0]["dashboard_id"]
        saved = c.get("/api/dashboards/" + did).json()
        assert saved["requested_measures"] == intent["measures"] and saved["omitted_measures"] == ["gross_to_net_rate"]
        assert [c["id"] for c in saved["columns"]] == ["net_sales", "units_shipped"]


def test_unsafe_verdicts_and_narrowed_reusable_scope_cannot_be_built():
    with TestClient(app) as c:
        for verdict in ["review", "reuse", "repair", "migrate", "consolidate", "retire", "not_feasible"]:
            path = seed(c, cid=verdict, verdict=verdict)
            assert c.get(path).json()["status"] == "blocked"
            assert c.post(path + "/build", json={"version": 0, "review_token": "forced"}).status_code == 409
        scoped = {"measures": ["units_shipped", "digital_engagement_index"], "dimensions": ["month"], "grain": "month",
                  "filters": {"product": ["Nubeqa"], "market": ["DE"]}, "decision": "Plan monthly stock",
                  "dashboard_brief": {"period": {"start": "2026-01", "end": "2026-10"}}}
        path = seed(c, "narrow", intent=scoped)
        result = c.post(path + "/answers", json={"version": 0, "key": "metric_scope", "value": "available_only"}).json()
        assert result["status"] == "blocked" and result["reuse_url"] == "/briefings?view=shipments"
        explicit = seed(c, "format", question="Deliver weekly figures in a Power BI file")
        assert c.get(explicit).json()["status"] == "blocked"
        excluded = seed(c, "excluded", question="Show units for all products except Nubeqa.")
        assert c.get(excluded).json()["status"] == "blocked"


def test_grouped_source_math_tracks_every_observation_and_never_assumes_weights():
    catalog.reset_catalog()
    intent = {"measures": ["net_sales", "units_shipped", "on_time_in_full"], "dimensions": ["month"],
              "grain": "month", "decision": "Compare distribution", "filters": {"product": ["Nubeqa"], "market": ["DE", "FR"]},
              "dashboard_brief": {"period": {"start": "2026-10", "end": "2026-10"}}}
    req, question, error = resolve(intent, "new_build", {}, "Monthly distribution")
    assert question["key"] == "rates" and error is None
    req, q, err = resolve(intent, "new_build", {"rates": "mean"}, "Monthly distribution")
    assert q is None and err is None
    dash = assemble(req, "example", "c", "r", "October distribution")
    point = dash["groups"][0]["points"][0]
    assert point["source_rows"] == [11, 21] and point["values"]["units_shipped"] == 12635 + 33941
    raw = dash["source_records"]
    assert point["values"]["on_time_in_full"] == round(sum(r["otif_pct_syn"] for r in raw) / 2, 4)
    assert point["values"]["net_sales"] == 51.54
    per, _, _ = resolve(intent, "new_build", {"rates": "separate"}, "Monthly distribution")
    assert len(assemble(per, "d", "c", "r", "")["groups"]) == 2


def test_canonical_currency_kpi_cannot_use_a_percentage_field_or_an_unapproved_signed_formula():
    catalog.reset_catalog()
    intent = {"measures": ["forecast_variance", "net_sales"], "grain": "month", "decision": "Compare budget"}
    req, question, reason = resolve(intent, "new_build", {}, "Compare budget")
    assert question["key"] == "metric_scope" and "approved unit EUR, source unit %" in question["prompt"]
    assert req["measures"] == ["net_sales"] and req["omitted_measures"] == ["forecast_variance"]
    intent["measures"] = ["forecast_variance"]
    req, question, reason = resolve(intent, "new_build", {}, "Compare budget")
    assert not question and "approved unit EUR, source unit %" in reason and req["measures"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("make", [MemoryStore, lambda: MongoStore(AsyncMockDB())])
async def test_store_rejects_stale_draft_writes_and_preserves_published_data(make):
    store = make()
    doc = {"_id": "r", "version": 1, "built_id": None}
    assert await store.advance_dashboard(doc, 0)
    assert not await store.advance_dashboard({**doc, "answers": {"changed": True}}, 0)
    assert await store.advance_dashboard({**doc, "version": 2, "built_id": "d"}, 1)
    assert not await store.advance_dashboard({**doc, "version": 3}, 2)
    artifact = {"_id": "d", "id": "d", "title": "First", "created_at": "2026-11-07", "period": {}, "decision_goal": "Review"}
    await store.publish_dashboard_once(deepcopy(artifact))
    assert (await store.publish_dashboard_once({**artifact, "title": "Second"}))["title"] == "First"
    assert len(await store.dashboard_directory()) == 1


def test_build_receipt_describes_the_real_artifact_for_the_handoff():
    catalog.reset_catalog()
    with TestClient(app) as c:
        path = seed(c, "receipt-chat")
        ready = c.get(path).json()
        r = ready["receipt"]
        assert r["products"] == ["Nubeqa"] and r["markets"] == ["France"]
        assert [m["kpi_id"] for m in r["measures"]] == ["KPI-001", "KPI-014"]
        assert r["months"] == 10 and r["observations"] == 10 and r["rows"] == {"first": 12, "last": 21}
        assert r["actual_like"] + r["forecast_like"] == 10 and r["source"] == "Product_Market_Monthly"
        assert r["groups"] == 1 and r["charted_measures"] == 2
        assert r["arrangement"].startswith("Switch between Net Sales") and "monthly trend" in r["arrangement"]
        assert "group" not in r["arrangement"]
        state, _ = build(c, path)
        assert state["receipt"] == r and not state["reused"]
        # the receipt is presentation only: the token and the saved values are unchanged by it
        dash = c.get("/api/dashboards/" + state["dashboard_id"]).json()
        assert dash["receipt"] == r and "receipt" not in c.portal.call(app.state.pipeline.store.get_artifact, "dashboards", state["dashboard_id"])


def test_build_receipt_wording_follows_months_measures_and_groups():
    catalog.reset_catalog()
    intent = {"measures": ["units_shipped"], "dimensions": ["month"], "grain": "month", "decision": "Compare distribution",
              "filters": {"product": ["Nubeqa"], "market": ["DE", "FR"]}, "dashboard_brief": {"period": {"start": "2026-10", "end": "2026-10"}}}
    req, q, err = resolve(intent, "new_build", {}, "October shipments")
    assert q is None and err is None, (q, err)
    from app.dashboard_builder import build_receipt
    one = build_receipt(assemble(req, "x", "c", "r", ""))
    assert one["months"] == 1 and one["charted_measures"] == 1 and not one["arrangement"].startswith("Switch")
    assert "October 2026" in one["arrangement"] and sorted(one["markets"]) == ["France", "Germany"]
    grouped_intent = {**intent, "measures": ["net_sales", "units_shipped", "on_time_in_full"]}
    per, _, _ = resolve(grouped_intent, "new_build", {"rates": "separate"}, "")
    grouped = build_receipt(assemble(per, "y", "c", "r", ""))
    # Two peers over the same months: the comparison layout, whether or not a guided example built it.
    assert grouped["groups"] == 2 and grouped["layout"] == "comparison" and "Summary cards for" in grouped["arrangement"]


def _artifact(groups: dict, columns=("units_shipped",), **extra) -> dict:
    cols = [{"id": c, "name": c, "unit": "units"} for c in columns]
    return {"columns": cols, "groups": [{"label": k, "points": [{"period": m, "values": {c: v for c in columns}} for m, v in pts]}
                                        for k, pts in groups.items()], **extra}


def test_choose_layout_follows_the_data_shape():
    from app.dashboard_builder import build_receipt, choose_layout
    a = [("2026-05", 1), ("2026-06", 2)]
    assert choose_layout(_artifact({"FR": a, "DE": a})) == "comparison"
    assert choose_layout(_artifact({"FR": a})) == "pulse"
    assert choose_layout(_artifact({"FR": a[:1]})) == "summary"
    assert choose_layout(_artifact({"FR": a, "DE": a[:1]})) == "overview"           # uneven coverage
    assert choose_layout(_artifact({"FR": a, "DE": a, "IT": a})) == "overview"      # three peers
    assert choose_layout(_artifact({"FR": [("2026-05", None)]})) == "empty"
    assert choose_layout(_artifact({"FR": a}, display_mode="table")) == "table"
    three = build_receipt(_artifact({"FR": a, "DE": a}, columns=("net_sales", "units_shipped", "on_time_in_full"), lead_measure="units_shipped"))
    assert three["layout"] == "comparison" and "two at a time, with a KPI selector" in three["arrangement"]
    assert "units_shipped leads" in three["arrangement"]
    plain = build_receipt(_artifact({"FR": a, "DE": a}))
    assert "leads" not in plain["arrangement"] and "one panel per KPI" in plain["arrangement"]
