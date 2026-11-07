from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from app import catalog
from app.ask_metrics import metric_series
from app.employee_report_match import native_reuse
from app.main import app
from app.pipeline import analyse
from app.store import MemoryStore
from .helpers import preset_intent, sse


def open_handoff(client, **request):
    events = sse(client.post("/api/chat", json=request))
    cid = events[0]["id"]
    if events[-1].get("state") == "clarifying":
        sse(client.post("/api/chat", json={"conversation_id": cid, "message": "Decide where to act this month"}))
    conversation = client.get("/api/conversations/" + cid).json()
    run = conversation["runs"][-1]
    return f"/api/conversations/{cid}/runs/{run['id']}/handoff", conversation


def test_multi_metric_source_series_freezes_and_detects_changes_outside_the_latest_pair(monkeypatch):
    with TestClient(app) as c:
        path, conv = open_handoff(c, preset_id="scn_reuse_lynkuet_es")
        pulse = c.get(path).json()["metric_series"]
        assert pulse["source"] == "Product_Market_Monthly" and pulse["filters"] == {"product_id": "P-LYN", "market_id": "ES"}
        assert (pulse["start_period"], pulse["end_period"], pulse["display_mode"]) == ("2026-01", "2026-10", "chart")
        assert [(c["id"], c["field"], c["unit"]) for c in pulse["columns"]] == [
            ("inventory_coverage", "inventory_weeks_syn", "weeks"), ("on_time_in_full", "otif_pct_syn", "%")]
        rows = catalog.SHEETS["product_market_monthly"]
        assert [p["row"] for p in pulse["points"]] == list(range(592, 602))
        for p in pulse["points"]:
            raw = rows[p["row"] - 2]
            assert p["period"] == raw["month"][:7] and p["value_type"] == raw["value_type"]
            assert p["values"] == {c["id"]: raw[c["field"]] for c in pulse["columns"]}
        action = c.post(path + "/actions", json={"owner_id": "OWN-017", "due_date": "2026-11-20"}).json()
        assert action["request_snapshot"]["metric_series"] == pulse
        before = rows[590]["inventory_weeks_syn"]
        monkeypatch.setitem(rows[590], "inventory_weeks_syn", before + 1)
        assert c.get(path).json()["metric_series"] is None
        assert c.get("/api/actions/" + action["_id"]).json()["request_snapshot"]["metric_series"] == pulse
        monkeypatch.setitem(rows[590], "inventory_weeks_syn", before)
        assert c.get(path).json()["metric_series"] == pulse
        # No new numbers may be attached to runs saved before this feature.
        saved_decision = next(e["data"] for e in conv["runs"][-1]["events"] if e.get("stage") == "decision" and e.get("status") == "done")
        del saved_decision["metric_series"]
        c.portal.call(app.state.pipeline.store.save, conv)
        assert c.get(path).json()["metric_series"] is None
        # An old assignment cannot be enriched even when the run does contain a matching series.
        saved_decision["metric_series"] = pulse
        c.portal.call(app.state.pipeline.store.save, conv)
        stored = c.portal.call(app.state.pipeline.store.get_artifact, "actions", action["_id"])
        del stored["request_snapshot"]["metric_series"]
        c.portal.call(app.state.pipeline.store.save_artifact, "actions", stored)
        assert c.get(path).json().get("metric_series") is None


def test_only_the_saved_native_revision_can_supply_the_report_display_mode():
    with TestClient(app) as c:
        request = {"message": "Monthly units shipped for Nubeqa in Germany. Needed today."}
        old, _ = open_handoff(c, **request)
        initial = c.get(old).json()
        assert initial["metric_series"]["display_mode"] == "chart"
        path = "/api/report-register/BR-SHIPMENTS"
        owner = c.get(path).json()["owner"]["id"]
        for seq, (kind, actor) in enumerate([("requested", "OWN-008"), ("prepared", owner), ("approved", "OWN-039")]):
            payload = {"kind": kind, "actor_id": actor, "expected_seq": seq, "note": "Use a table for the monthly numbers.",
                       "evidence_ref": "KPI_Catalog row 15"}
            if kind == "prepared":
                payload["display_mode"] = "table"
            c.post(path + "/changes", json=payload).raise_for_status()
        assert c.get(old).json()["metric_series"] is None
        new, _ = open_handoff(c, **request)
        live = c.get(new).json()
        assert live["employee_report"]["display_mode"] == live["metric_series"]["display_mode"] == "table"
        assert live["metric_series"]["points"][-1]["values"] == {"units_shipped": 12635}
        assert live["metric_series"]["points"][0]["value_type"] == "forecast_like_synthetic"
        for preset in ("scn_reuse_eylea_jp", "req_migrate_xarelto", "scn_out_of_scope"):
            other, _ = open_handoff(c, preset_id=preset)
            assert c.get(other).json()["metric_series"] is None


def test_bounded_ordered_windows_refuse_missing_values_duplicates_and_bad_scope(monkeypatch):
    catalog.reset_catalog()
    intent = preset_intent("scn_reuse_lynkuet_es")
    original = catalog.SHEETS["product_market_monthly"]
    earlier = [dict(original[590], month=f"2025-{month:02}-01") for month in (12, 11, 10, 9)]
    monkeypatch.setitem(catalog.SHEETS, "product_market_monthly", [*original, *earlier])
    decision = analyse(intent)["decision"]
    pulse = metric_series(intent, decision)
    assert len(pulse["points"]) == 12 and pulse["start_period"] == "2025-11" and pulse["end_period"] == "2026-10"
    assert metric_series({**intent, "filters": {"product": ["Lynkuet"], "market": ["DE"]}}, decision) is None
    bad = deepcopy(decision)
    bad["preview"]["rows"][0]["values"]["inventory_coverage"] = 999
    assert metric_series(intent, bad) is None
    monkeypatch.setitem(earlier[1], "inventory_weeks_syn", None)
    assert metric_series(intent, decision) is None
    monkeypatch.setitem(catalog.SHEETS, "product_market_monthly", [*original, dict(original[590])])
    assert metric_series(intent, decision) is None


@pytest.mark.asyncio
async def test_native_sales_view_separately_labels_the_workbook_forecast():
    catalog.reset_catalog()
    intent = {"measures": ["net_sales"], "grain": "month", "dimensions": ["month"],
              "filters": {"product": ["Nubeqa"], "market": ["DE"]}}
    native = await native_reuse(MemoryStore(), intent, ["Monthly Nubeqa net sales in Germany"],
                                {"decision": "new_build", "reason": "No imported match."})
    pulse = metric_series(intent, native)
    assert [c["field"] for c in pulse["columns"]] == ["net_sales_m_eur_syn", "forecast_m_eur_syn"]
    assert pulse["points"][-1]["values"] == {"net_sales": 13.96, "sales_forecast": 12.49}
    assert pulse["columns"][1]["lower_is_better"] is None
