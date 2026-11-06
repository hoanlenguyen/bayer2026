import pytest

from app import catalog as cat
from app.graph import build_graph
from app.store import MemoryStore, MongoStore

from .fakes import AsyncMockDB


@pytest.fixture(autouse=True)
def _catalog():
    cat.reset_catalog()


@pytest.mark.parametrize("make", [MemoryStore, lambda: MongoStore(AsyncMockDB())])
async def test_store_roundtrip(make):
    store = make()
    if isinstance(store, MongoStore):
        await store.ensure_indexes()
    assert await store.load_catalog() is None
    await store.seed_catalog(cat.SEED_CATALOG, cat.SEED_PRESETS)
    loaded = await store.load_catalog()
    assert [a["id"] for a in loaded["assets"]] == [a["id"] for a in cat.SEED_CATALOG["assets"]]
    assert loaded["measures"]["oee"]["name"] == "OEE %"
    assert loaded["relationships"] == cat.SEED_CATALOG["relationships"]
    assert [p["id"] for p in await store.load_presets()] == [p["id"] for p in cat.SEED_PRESETS]

    # seeding again without reset keeps changes
    await store.upsert_asset({**loaded["assets"][0], "views_90d": 1})
    await store.upsert_asset({"id": "rpt_new", "name": "New", "measures": []})
    await store.seed_catalog(cat.SEED_CATALOG, cat.SEED_PRESETS)
    again = await store.load_catalog()
    assert again["assets"][0]["views_90d"] == 1 and again["assets"][-1]["id"] == "rpt_new"

    await store.save({"_id": "c1", "title": "t", "updated_at": "2026-11-06T10:00:00+00:00", "runs": []})
    assert (await store.get("c1"))["title"] == "t"
    assert [c["_id"] for c in await store.list()] == ["c1"]

    await store.save_artifact("specs", {"_id": "s1", "conversation_id": "c1", "created_at": "x", "status": "draft"})
    await store.update_artifact("specs", "s1", {"status": "approved"})
    assert (await store.list_artifacts("specs", "c1"))[0]["status"] == "approved"


async def test_catalog_init_from_store():
    store = MongoStore(AsyncMockDB())
    await cat.init(store)
    assert cat.asset_by_id("rpt_delivery_perf")["owner"] == "S. Virtanen"
    assert len(cat.PRESETS) == len(cat.SEED_PRESETS)


def test_graph_from_plant_catalog():
    g = build_graph()
    ids = {e["id"]: e for e in g["entities"]}
    assert g["focus"] == "rpt_delivery_perf"
    assert ids["rpt_logistics_weekly"]["status"] == "conflict"
    assert ids["p_j_kovac"]["status"] == "left"
    rels = {(e["s"], e["rel"], e["t"]) for e in g["edges"]}
    assert ("rpt_logistics_weekly", "conflicts_with", "otif") in rels
    assert ("rpt_logistics_weekly", "duplicate_of", "rpt_delivery_perf") in rels
    assert ("rpt_line_oee", "duplicate_of", "rpt_daily_production") in rels
    assert ("shipments_fact", "feeds", "late_shipments") in rels
    assert all(e["s"] in ids and e["t"] in ids for e in g["edges"])
