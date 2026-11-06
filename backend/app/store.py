"""Persistence: MongoDB when MONGODB_URI is set, otherwise in memory.

Collections
  conversations        chat messages, current intent, runs with every streamed event
  intents              each clarified intent (one per run)
  evidence             verified evidence records
  specs                DashboardSpec versions with status draft / approved / rejected
  agent_runs           audit log: agent, mode, model, steps, duration
  catalog_measures, catalog_dimensions, catalog_datasets, catalog_assets, catalog_relationships
                       the analytics catalog (seeded from app/data/catalog.json when empty)
  presets              department presets
"""
from __future__ import annotations

import copy
import logging
from typing import Any

from .settings import settings

log = logging.getLogger(__name__)

ARTIFACTS = ("intents", "evidence", "specs", "agent_runs")
CATALOG_MAPS = ("measures", "dimensions", "datasets")


class MemoryStore:
    name = "memory"

    def __init__(self) -> None:
        self.conversations: dict[str, dict[str, Any]] = {}
        self.artifacts: dict[str, dict[str, dict[str, Any]]] = {k: {} for k in ARTIFACTS}
        self.catalog: dict[str, Any] | None = None
        self.presets: list[dict[str, Any]] | None = None

    # conversations
    async def get(self, conv_id: str) -> dict[str, Any] | None:
        doc = self.conversations.get(conv_id)
        return copy.deepcopy(doc) if doc else None

    async def save(self, conv: dict[str, Any]) -> None:
        self.conversations[conv["_id"]] = copy.deepcopy(conv)

    async def list(self, limit: int = 20) -> list[dict[str, Any]]:
        docs = sorted(self.conversations.values(), key=lambda d: d.get("updated_at", ""), reverse=True)[:limit]
        return [{"_id": d["_id"], "title": d.get("title"), "updated_at": d.get("updated_at")} for d in docs]

    # pipeline artifacts
    async def save_artifact(self, kind: str, doc: dict[str, Any]) -> None:
        self.artifacts[kind][doc["_id"]] = copy.deepcopy(doc)

    async def update_artifact(self, kind: str, doc_id: str, fields: dict[str, Any]) -> None:
        if doc_id in self.artifacts[kind]:
            self.artifacts[kind][doc_id].update(copy.deepcopy(fields))

    async def list_artifacts(self, kind: str, conv_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        docs = [d for d in self.artifacts[kind].values() if conv_id is None or d.get("conversation_id") == conv_id]
        return copy.deepcopy(sorted(docs, key=lambda d: d.get("created_at", ""), reverse=True)[:limit])

    # catalog
    async def load_catalog(self) -> dict[str, Any] | None:
        return copy.deepcopy(self.catalog)

    async def load_presets(self) -> list[dict[str, Any]] | None:
        return copy.deepcopy(self.presets)

    async def seed_catalog(self, catalog: dict[str, Any], presets: list[dict[str, Any]], reset: bool = False) -> None:
        if reset or self.catalog is None:
            self.catalog = copy.deepcopy({k: v for k, v in catalog.items() if not k.startswith("_")})
            self.presets = copy.deepcopy(presets)

    async def upsert_asset(self, asset: dict[str, Any]) -> None:
        if self.catalog is None:
            return
        assets = self.catalog["assets"]
        for i, a in enumerate(assets):
            if a["id"] == asset["id"]:
                assets[i] = copy.deepcopy(asset)
                return
        assets.append(copy.deepcopy(asset))

    async def update_dataset(self, dataset_id: str, fields: dict[str, Any]) -> None:
        if self.catalog and dataset_id in self.catalog["datasets"]:
            self.catalog["datasets"][dataset_id].update(fields)


class MongoStore:
    name = "mongodb"

    def __init__(self, db: Any, client: Any | None = None) -> None:
        self.client = client
        self.db = db

    @classmethod
    def connect(cls, uri: str, db_name: str) -> "MongoStore":
        from pymongo import AsyncMongoClient

        client = AsyncMongoClient(uri, serverSelectionTimeoutMS=5000, appname="analytics-manager")
        return cls(client[db_name], client)

    async def ping(self) -> None:
        await self.db.command("ping")

    async def ensure_indexes(self) -> None:
        await self.db["conversations"].create_index([("updated_at", -1)])
        for kind in ARTIFACTS:
            await self.db[kind].create_index([("conversation_id", 1), ("created_at", -1)])
        await self.db["specs"].create_index([("status", 1)])

    # conversations
    async def get(self, conv_id: str) -> dict[str, Any] | None:
        return await self.db["conversations"].find_one({"_id": conv_id})

    async def save(self, conv: dict[str, Any]) -> None:
        await self.db["conversations"].replace_one({"_id": conv["_id"]}, conv, upsert=True)

    async def list(self, limit: int = 20) -> list[dict[str, Any]]:
        cursor = self.db["conversations"].find({}, {"title": 1, "updated_at": 1}).sort("updated_at", -1).limit(limit)
        return [d async for d in cursor]

    # pipeline artifacts
    async def save_artifact(self, kind: str, doc: dict[str, Any]) -> None:
        await self.db[kind].replace_one({"_id": doc["_id"]}, doc, upsert=True)

    async def update_artifact(self, kind: str, doc_id: str, fields: dict[str, Any]) -> None:
        await self.db[kind].update_one({"_id": doc_id}, {"$set": fields})

    async def list_artifacts(self, kind: str, conv_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        query = {"conversation_id": conv_id} if conv_id else {}
        cursor = self.db[kind].find(query).sort("created_at", -1).limit(limit)
        return [d async for d in cursor]

    # catalog
    async def load_catalog(self) -> dict[str, Any] | None:
        if await self.db["catalog_assets"].count_documents({}) == 0:
            return None
        catalog: dict[str, Any] = {}
        for key in CATALOG_MAPS:
            catalog[key] = {d.pop("_id"): d async for d in self.db[f"catalog_{key}"].find({})}
        catalog["assets"] = [{k: v for k, v in d.items() if k not in ("_id", "order")}
                             async for d in self.db["catalog_assets"].find({}).sort("order", 1)]
        catalog["relationships"] = [{k: v for k, v in d.items() if k != "_id"}
                                    async for d in self.db["catalog_relationships"].find({}).sort("_id", 1)]
        return catalog

    async def load_presets(self) -> list[dict[str, Any]] | None:
        docs = [d async for d in self.db["presets"].find({}).sort("order", 1)]
        return [{k: v for k, v in d.items() if k not in ("_id", "order")} for d in docs] or None

    async def seed_catalog(self, catalog: dict[str, Any], presets: list[dict[str, Any]], reset: bool = False) -> None:
        if not reset and await self.db["catalog_assets"].count_documents({}) > 0:
            return
        for key in CATALOG_MAPS:
            col = self.db[f"catalog_{key}"]
            await col.delete_many({})
            await col.insert_many([{"_id": k, **v} for k, v in catalog[key].items()])
        await self.db["catalog_assets"].delete_many({})
        await self.db["catalog_assets"].insert_many([{"_id": a["id"], "order": i, **a} for i, a in enumerate(catalog["assets"])])
        await self.db["catalog_relationships"].delete_many({})
        await self.db["catalog_relationships"].insert_many([{"_id": i, **r} for i, r in enumerate(catalog["relationships"])])
        await self.db["presets"].delete_many({})
        await self.db["presets"].insert_many([{"_id": p["id"], "order": i, **p} for i, p in enumerate(presets)])
        log.info("Seeded MongoDB catalog: %d assets, %d measures", len(catalog["assets"]), len(catalog["measures"]))

    async def upsert_asset(self, asset: dict[str, Any]) -> None:
        # Keep the original position of existing reports; new ones go last.
        await self.db["catalog_assets"].update_one(
            {"_id": asset["id"]},
            {"$set": {k: v for k, v in asset.items() if k != "order"}, "$setOnInsert": {"order": 10_000}},
            upsert=True)

    async def update_dataset(self, dataset_id: str, fields: dict[str, Any]) -> None:
        await self.db["catalog_datasets"].update_one({"_id": dataset_id}, {"$set": fields})


Store = MemoryStore | MongoStore


async def create_store() -> Store:
    if settings.mongodb_uri:
        try:
            store = MongoStore.connect(settings.mongodb_uri, settings.mongodb_db)
            await store.ping()
            await store.ensure_indexes()
            log.info("Using MongoDB database '%s'", settings.mongodb_db)
            return store
        except Exception as exc:
            log.warning("MongoDB unavailable (%s). Falling back to in-memory storage.", exc)
    return MemoryStore()
