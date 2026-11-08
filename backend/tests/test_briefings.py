import asyncio
from datetime import date

from fastapi.testclient import TestClient
import pytest

from app import briefings, catalog
from app.main import app
from app.store import MemoryStore, MongoStore

from .fakes import AsyncMockDB


def test_source_values_and_undated_routing():
    with TestClient(app) as c:
        commercial = c.get("/api/briefings/commercial").json()
        assert (commercial["period"], commercial["previous_period"]) == ("2026-10", "2026-09")
        assert commercial["selected_view_ids"] == ["sales", "shipments"]
        sales, units, otif = commercial["views"]
        assert (sales["current"], sales["previous"], sales["forecast"], sales["forecast_variance_pct"]) == (13.96, 44.5, 12.49, 11.8)
        assert (units["current"], units["previous"], units["change_pct"]) == (12635, 188001, -93.3)
        assert (otif["current"], otif["previous"], otif["change_pp"]) == (80.9, 90.9, -10.0)
        assert sales["evidence"]["rows"] == [10, 11]
        assert sales["evidence"]["records"][1]["month"] == "2026-10-01"
        history = sales["history"]
        assert (history["start_period"], history["end_period"], history["unit"]) == ("2026-01", "2026-10", "€m")
        assert [p["row"] for p in history["points"]] == list(range(2, 12))
        assert history["points"][0] == {"row": 2, "period": "2026-01", "value": 19.66,
                                        "value_type": "forecast_like_synthetic", "forecast": 18.42}
        assert [(p["row"], p["value"], p["forecast"]) for p in history["points"][-2:]] == [(10, 44.5, 48.59), (11, 13.96, 12.49)]
        assert [p["row"] for p in history["points"] if p["value_type"] == "forecast_like_synthetic"] == [2, 4, 7, 9]
        for v in [units, otif]:
            assert len(v["history"]["points"]) == 10 and all("forecast" not in p for p in v["history"]["points"])
            assert v["history"]["points"][-1]["value"] == v["current"]
        assert commercial["route"] is None
        supply = c.get("/api/briefings/supply").json()
        assert supply["selected_view_ids"] == ["shipments", "otif"]
        assert (supply["route"]["source"], supply["route"]["mode"], supply["route"]["period"]) == ("External-CMO", "road", None)
        assert supply["route"]["evidence"]["sheet"] == "Supply_Operations" and supply["route"]["evidence"]["rows"] == [2]


def test_shared_selection_and_snapshot_actions():
    url = "/api/briefings/supply"
    with TestClient(app) as c:
        old = c.get(url).json()
        request = {"version": old["version"], "owner_id": "OWN-017", "due_date": "2026-11-18"}
        assert c.put(url + "/selection", json={"view_ids": ["otif", "otif"]}).status_code == 422
        assert c.put(url + "/selection", json={"view_ids": []}).status_code == 422
        assert c.put(url + "/selection", json={"view_ids": ["bad"]}).status_code == 422
        fresh = c.put(url + "/selection", json={"view_ids": ["otif"]}).json()
        assert c.get(url).json()["selected_view_ids"] == ["otif"]
        assert c.get("/api/briefings/commercial").json()["selected_view_ids"] == ["sales", "shipments"]
        assert c.post(url + "/actions", json=request).status_code == 409
        request["version"] = fresh["version"]
        assert c.post(url + "/actions", json={**request, "owner_id": "OWN-999"}).status_code == 422
        saved = c.post(url + "/actions", json=request).json()
        assert saved["title"] == fresh["suggested_action"] and saved["status"] == "open"
        assert saved["owner_id"] == request["owner_id"] and saved["owner"] == "Leo Weber"
        assert saved["due_date"] == request["due_date"]
        snap = saved["briefing_snapshot"]
        assert snap["selected_view_ids"] == ["otif"] and len(snap["views"]) == 1
        assert snap["views"][0]["report_id"] == "BR-OTIF" and snap["views"][0]["current"] == 80.9
        assert "history" not in snap["views"][0]
        assert snap["views"][0]["evidence"]["filters"] == {"product_id": "P-NUB", "market_id": "DE"}
        aid = saved["_id"]
        assert c.post(url + "/actions", json={**request, "owner_id": "OWN-008"}).json()["owner_id"] == "OWN-017"
        assert c.get(url).json()["action"]["_id"] == aid
        assert saved["created_by_id"] == "OWN-005" and saved["created_by"] == "Felix Schmidt"
        assert c.patch("/api/briefings/commercial/actions/" + aid, json={"status": "done"}).status_code == 404
        updated = c.patch(url + "/actions/" + aid, json={"status": "done", "outcome": "Dispatch records reviewed."}).json()
        assert updated["status"] == "done" and updated["briefing_snapshot"] == snap
        assert updated["history"][-1]["by_id"] == "OWN-005"
        c.put(url + "/selection", json={"view_ids": ["shipments", "sales"]})
        latest = c.get(url).json()
        assert latest["action"] is None
        assert [(a["_id"], a["outcome"]) for a in latest["recent_actions"]] == [(aid, "Dispatch records reviewed.")]
        assert not c.get("/api/briefings/commercial").json()["recent_actions"]
        assert c.post(url + "/actions", json=request).json()["status"] == "done"
        scoped = c.post(url + "/actions", json={**request, "version": latest["version"], "view_id": "sales",
                                                "title": "Compare the latest sales figures"}).json()
        assert scoped["asset_id"] == "BR-SALES"
        assert [v["id"] for v in scoped["briefing_snapshot"]["views"]] == ["sales"]
        assert scoped["briefing_snapshot"]["views"][0]["history"] == latest["views"][0]["history"]
        assert c.get(url).json()["views"][0]["action"]["_id"] == scoped["_id"]


def test_source_updates_and_published_report_revision(monkeypatch):
    catalog.reset_catalog()
    # New workbook periods and reviewed report titles/modes change the evidence fingerprint.
    sample = dict(catalog.SHEETS["product_market_monthly"][9], month="2026-11-01", net_sales_m_eur_syn=21,
                  forecast_m_eur_syn=20, forecast_variance_pct=5)
    monkeypatch.setitem(catalog.SHEETS, "product_market_monthly", [*catalog.SHEETS["product_market_monthly"], sample])
    latest, previous, base = briefings.report_views({})
    _, _, edited = briefings.report_views({"BR-SALES": {"title": "Reviewed performance", "revision": 1,
                                                        "display_mode": "table"}})
    assert (latest, previous, base[0]["current"]) == ("2026-11", "2026-10", 21)
    assert edited[0]["report"] == "Reviewed performance" and edited[0]["display_mode"] == "table"
    assert edited[0]["version"] != base[0]["version"]
    assert edited[0]["evidence"] == base[0]["evidence"]


def test_briefing_audit_cannot_be_bypassed_or_rewritten():
    with TestClient(app) as c:
        url = "/api/briefings/commercial"
        version = c.get(url).json()["version"]
        saved = c.post(url + "/actions", json={"version": version, "owner_id": "OWN-017",
                                               "due_date": "2026-11-18"}).json()
        action_url = url + "/actions/" + saved["_id"]
        generic_url = "/api/actions/" + saved["_id"]
        assert c.patch(generic_url, json={"owner": "Other name", "by": "unverified"}).status_code == 409
        assert c.patch(action_url, json={"status": "open", "owner": "Other name"}).status_code == 422
        assert c.patch(action_url, json={"outcome": "Standalone edit"}).status_code == 422
        assert c.patch(action_url, json={"status": "in_progress", "outcome": "Premature"}).status_code == 422
        complete = {"status": "done", "outcome": "Compared both periods."}
        done = c.patch(action_url, json=complete).json()
        assert c.patch(action_url, json=complete).json() == done
        assert c.patch(action_url, json={**complete, "outcome": "Overwrite"}).status_code == 409
        assert c.get(generic_url).json() == done
        note = {"status": "verified", "verification": {"result": "confirmed", "note": "Source rows checked."}}
        verified = c.patch(action_url, json=note).json()
        assert verified["verify"]["checked_by_id"] == "OWN-008"
        assert c.patch(action_url, json=note).json() == verified
        assert c.patch(action_url, json={"status": "verified", "verification": {"result": "improved"}}).status_code == 409
        normal = c.post("/api/actions", json={"title": "Ordinary action", "owner": "First"}).json()
        assert c.patch("/api/actions/" + normal["_id"], json={"owner": "Second"}).json()["owner"] == "Second"


@pytest.mark.asyncio
@pytest.mark.parametrize("make_store", [MemoryStore, lambda: MongoStore(AsyncMockDB())])
async def test_conflicting_writers_only_append_one_history_event(make_store):
    store = make_store()
    initial = {"_id": "a", "status": "open", "history": [{"change": "created", "to": "open"}]}
    await store.insert_action_once(initial)
    competing = [{**initial, "status": "done", "outcome": note,
                  "history": [*initial["history"], {"change": "status", "to": "done", "note": note}]}
                 for note in ("First outcome", "Other outcome")]
    writes = await asyncio.gather(*(store.replace_briefing_action(a, initial["history"]) for a in competing))
    assert writes.count(True) == 1
    assert await store.get_artifact("actions", "a") == competing[writes.index(True)]


@pytest.mark.asyncio
async def test_briefing_survives_store_reconnect():
    catalog.reset_catalog()
    db = AsyncMockDB()
    original = MongoStore(db)
    await original.save_artifact("briefing_selections", {"_id": "commercial", "view_ids": ["sales"]})
    briefing = await briefings.read_briefing(original, "commercial")
    action = await briefings.save_followup(original, "commercial", briefing["version"], None, None, "OWN-008",
                                           date(2026, 11, 18))
    reconnected = MongoStore(db)
    recovered = await briefings.read_briefing(reconnected, "commercial")
    assert recovered["storage_mode"] == "mongodb" and recovered["selected_view_ids"] == ["sales"]
    assert recovered["action"]["_id"] == action["_id"] and recovered["recent_actions"] == [action]
    retry = await briefings.save_followup(reconnected, "commercial", briefing["version"], None, None, "OWN-017",
                                          date(2026, 11, 20))
    assert retry == action and await reconnected.count_artifacts("actions") == 1


def test_briefing_follows_the_newest_dashboard_built_in_ask():
    store = MemoryStore()
    default = asyncio.run(briefings.read_briefing(store, "commercial"))
    assert (default["product"], default["market"], default["scope_source"]) == ("Nubeqa", "Germany", None)
    store.artifacts.setdefault("dashboards", {}).update({
        "dash_old": {"id": "dash_old", "title": "Old", "created_at": "2026-11-01T09:00:00+00:00",
                     "scope": {"products": ["Kerendia"], "markets": ["Italy"]}},
        "dash_multi": {"id": "dash_multi", "title": "Two products", "created_at": "2026-11-09T09:00:00+00:00",
                       "scope": {"products": ["Nubeqa", "Kerendia"], "markets": ["France"]}},  # skipped: not one product
        "dash_new": {"id": "dash_new", "title": "Nubeqa · 2 markets", "created_at": "2026-11-08T09:00:00+00:00",
                     "scope": {"products": ["Nubeqa"], "markets": ["Germany", "France"]}},
    })
    first = asyncio.run(briefings.read_briefing(store, "commercial"))
    assert first["scope_source"]["id"] == "dash_new" and first["scope_source"]["url"] == "/dashboards/dash_new"
    assert [m["name"] for m in first["markets"]] == ["Germany", "France"] and first["market"] == "Germany"
    france = asyncio.run(briefings.read_briefing(store, "commercial", "FR"))
    sales = next(v for v in france["views"] if v["id"] == "sales")
    assert france["market"] == "France" and sales["evidence"]["filters"] == {"product_id": "P-NUB", "market_id": "FR"}
    assert (sales["current"], sales["forecast"]) == (37.58, 39.2) and france["version"] != first["version"]
    assert asyncio.run(briefings.read_briefing(store, "commercial", "XX"))["market"] == "Germany"  # unknown: first market
    trends = {t["market"]: {v["id"]: v["points"][-1]["value"] for v in t["views"]} for t in france["market_trends"]}
    assert list(trends) == ["Germany", "France"] and trends["Germany"]["sales"] == 13.96 and trends["France"]["sales"] == 37.58
    assert default["market_trends"] == []  # one market: the single chart as before
