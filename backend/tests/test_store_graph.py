import pytest

from app import catalog as cat
from app.datapack import read_workbook
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
    sheets = read_workbook()
    await store.seed_datapack(sheets, cat.seed_catalog(), cat.seed_presets())
    loaded = await store.load_catalog()
    assert [a["id"] for a in loaded["assets"]][:3] == ["AST-0001", "AST-0002", "AST-0003"]
    assert loaded["measures"]["net_sales"]["kpi_id"] == "KPI-001" and len(loaded["models"]) == 75
    assert len(loaded["lineage"]) == 438 and loaded["source"].startswith("Bayer")
    assert [p["id"] for p in await store.load_presets()] == [p["id"] for p in cat.PRESETS]
    if isinstance(store, MongoStore):
        assert await store.db["datapack_asset_usage"].count_documents({}) == 3600

    await store.upsert_asset({**loaded["assets"][0], "views_90d": 1})
    await store.upsert_asset({"id": "NEW-X", "name": "New", "measures": []})
    await store.seed_datapack(sheets, cat.seed_catalog(), cat.seed_presets())   # no reset: keeps changes
    again = await store.load_catalog()
    assert again["assets"][0]["views_90d"] == 1 and again["assets"][-1]["id"] == "NEW-X"

    await store.save({"_id": "c1", "title": "t", "updated_at": "2026-11-06T10:00:00+00:00", "runs": []})
    assert (await store.get("c1"))["title"] == "t"
    await store.save_artifact("specs", {"_id": "s1", "conversation_id": "c1", "created_at": "x", "status": "draft"})
    await store.update_artifact("specs", "s1", {"status": "approved"})
    assert (await store.list_artifacts("specs", "c1"))[0]["status"] == "approved"


async def test_catalog_init_from_mongo_seeds_samples():
    store = MongoStore(AsyncMockDB())
    await cat.init(store)
    assert cat.asset_by_id("AST-0217")["owner_status"] == "inactive"
    assert await store.count_artifacts("actions") == 4


def test_graph():
    g = build_graph()
    ids = {e["id"]: e for e in g["entities"]}
    rels = {(e["s"], e["rel"], e["t"]) for e in g["edges"]}
    assert ids["KPI-002"]["status"] == "conflict" and ("KPI-002", "variant_of", "family:Net Sales") in rels
    assert ("KPI-003", "variant_of", "family:Net Sales") in rels
    assert ids["AST-0001"]["status"] == "conflict" and ("AST-0001", "uses", "KPI-009") in rels
    assert ids[g["focus"]]["status"] == "certified"
    assert all(e["s"] in ids and e["t"] in ids for e in g["edges"])


async def test_outdated_catalog_in_mongo_is_reloaded():
    store = MongoStore(AsyncMockDB())
    # Simulate the earlier plant catalog: assets present, no schema in meta.
    await store.db["catalog_assets"].insert_many([{"_id": "rpt_delivery_perf", "order": 0, "id": "rpt_delivery_perf", "name": "Old"}])
    await store.db["catalog_datasets"].insert_many([{"_id": "shipments_fact"}])
    await store.seed_datapack(read_workbook(), cat.seed_catalog(), cat.seed_presets())
    loaded = await store.load_catalog()
    assert len(loaded["assets"]) == 360 and loaded["schema"] == 2
    assert await store.db["catalog_datasets"].count_documents({}) == 0
    # A current catalog is kept (no reload on every start).
    await store.upsert_asset({**loaded["assets"][0], "views_90d": 7})
    await store.seed_datapack(read_workbook(), cat.seed_catalog(), cat.seed_presets())
    assert (await store.load_catalog())["assets"][0]["views_90d"] == 7
