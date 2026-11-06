"""Persistence: MongoDB when configured, otherwise durable single-worker SQLite.

Collections
  conversations        chat messages, current intent, runs with every streamed event
  intents              each clarified intent (one per run)
  evidence             verified evidence records
  specs                DashboardSpec versions with status draft / approved / rejected
  agent_runs           audit log: agent, mode, model, steps, duration
  actions              follow-up actions with owner, due date, status history and verification
  catalog_<key>        the analytics catalog built from the Bayer data pack: measures, dimensions,
                       models, assets, owners, workspaces, products, markets, lineage, rules
  datapack_<sheet>     every table sheet of the workbook, row for row (raw, for querying)
  presets              Bayer business requests plus labelled team demo scenarios
"""
from __future__ import annotations

import copy
import logging
import json
import sqlite3
from pathlib import Path
from typing import Any

from .settings import settings

log = logging.getLogger(__name__)

ARTIFACTS = ("intents", "evidence", "specs", "agent_runs", "actions", "audit", "outputs", "submissions")
CATALOG_MAPS = ("measures", "dimensions", "models", "owners", "workspaces", "products", "markets")
CATALOG_LISTS = ("assets", "lineage", "rules")


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
        if kind == "audit" and doc["_id"] in self.artifacts[kind]:
            raise ValueError("Audit events are immutable")
        self.artifacts[kind][doc["_id"]] = copy.deepcopy(doc)

    async def update_artifact(self, kind: str, doc_id: str, fields: dict[str, Any]) -> None:
        if kind == "audit":
            raise ValueError("Audit events are immutable")
        if doc_id in self.artifacts[kind]:
            self.artifacts[kind][doc_id].update(copy.deepcopy(fields))

    async def get_artifact(self, kind: str, doc_id: str) -> dict[str, Any] | None:
        doc = self.artifacts[kind].get(doc_id)
        return copy.deepcopy(doc) if doc else None

    async def count_artifacts(self, kind: str) -> int:
        return len(self.artifacts[kind])

    async def list_artifacts(self, kind: str, conv_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        docs = [d for d in self.artifacts[kind].values() if conv_id is None or d.get("conversation_id") == conv_id]
        return copy.deepcopy(sorted(docs, key=lambda d: d.get("created_at", ""), reverse=True)[:limit])

    # catalog
    async def load_catalog(self) -> dict[str, Any] | None:
        return copy.deepcopy(self.catalog)

    async def load_presets(self) -> list[dict[str, Any]] | None:
        return copy.deepcopy(self.presets)

    async def seed_datapack(self, sheets: dict[str, list[dict[str, Any]]], catalog: dict[str, Any],
                            presets: list[dict[str, Any]], reset: bool = False) -> None:
        # Raw sheets stay in the workbook cache; only the catalog is kept here.
        if reset or self.catalog is None:
            self.catalog = copy.deepcopy(catalog)
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

    async def update_model(self, model_id: str, fields: dict[str, Any]) -> None:
        if self.catalog and model_id in self.catalog["models"]:
            self.catalog["models"][model_id].update(fields)


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
        await self.db["actions"].create_index([("status", 1), ("due_date", 1)])
        await self.db["actions"].create_index([("owner", 1)])

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
        if kind == "audit":
            await self.db[kind].insert_one(doc)
            return
        await self.db[kind].replace_one({"_id": doc["_id"]}, doc, upsert=True)

    async def update_artifact(self, kind: str, doc_id: str, fields: dict[str, Any]) -> None:
        if kind == "audit":
            raise ValueError("Audit events are immutable")
        await self.db[kind].update_one({"_id": doc_id}, {"$set": fields})

    async def get_artifact(self, kind: str, doc_id: str) -> dict[str, Any] | None:
        return await self.db[kind].find_one({"_id": doc_id})

    async def count_artifacts(self, kind: str) -> int:
        return await self.db[kind].count_documents({})

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
        for key in CATALOG_LISTS:
            catalog[key] = [{k: v for k, v in d.items() if k not in ("_id", "order")}
                            async for d in self.db[f"catalog_{key}"].find({}).sort("order", 1)]
        meta = await self.db["catalog_meta"].find_one({"_id": "meta"}) or {}
        catalog.update({k: v for k, v in meta.items() if k != "_id"})
        return catalog

    async def load_presets(self) -> list[dict[str, Any]] | None:
        docs = [d async for d in self.db["presets"].find({}).sort("order", 1)]
        return [{k: v for k, v in d.items() if k not in ("_id", "order")} for d in docs] or None

    async def seed_datapack(self, sheets: dict[str, list[dict[str, Any]]], catalog: dict[str, Any],
                            presets: list[dict[str, Any]], reset: bool = False) -> None:
        """Write raw sheets, the derived catalog and presets. Skips if already seeded unless reset."""
        if not reset and await self.db["catalog_assets"].count_documents({}) > 0:
            meta = await self.db["catalog_meta"].find_one({"_id": "meta"}) or {}
            if meta.get("schema") == catalog.get("schema"):
                return
            # An older catalog (for example the earlier fictional plant catalog) would break the app: replace it.
            log.warning("Catalog in MongoDB has schema %s, expected %s. Reloading it from the data pack.",
                        meta.get("schema"), catalog.get("schema"))
        for old in ("catalog_datasets", "catalog_relationships"):   # from the earlier plant catalog
            await self.db[old].delete_many({})
        for name, rows in sheets.items():
            col = self.db[f"datapack_{name}"]
            await col.delete_many({})
            if rows:
                await col.insert_many([dict(r) for r in rows])
        for key in CATALOG_MAPS:
            col = self.db[f"catalog_{key}"]
            await col.delete_many({})
            if catalog[key]:
                await col.insert_many([{"_id": k, **v} for k, v in catalog[key].items()])
        for key in CATALOG_LISTS:
            col = self.db[f"catalog_{key}"]
            await col.delete_many({})
            if catalog[key]:
                await col.insert_many([{"_id": r.get("id", i), "order": i, **r} for i, r in enumerate(catalog[key])])
        await self.db["catalog_meta"].replace_one(
            {"_id": "meta"}, {"_id": "meta", **{k: v for k, v in catalog.items() if k not in CATALOG_MAPS + CATALOG_LISTS}}, upsert=True)
        await self.db["presets"].delete_many({})
        await self.db["presets"].insert_many([{"_id": p["id"], "order": i, **p} for i, p in enumerate(presets)])
        log.info("Seeded MongoDB from the data pack: %d sheets, %d assets", len(sheets), len(catalog["assets"]))

    async def upsert_asset(self, asset: dict[str, Any]) -> None:
        # Keep the original position of existing reports; new ones go last.
        await self.db["catalog_assets"].update_one(
            {"_id": asset["id"]},
            {"$set": {k: v for k, v in asset.items() if k != "order"}, "$setOnInsert": {"order": 10_000}},
            upsert=True)

    async def update_model(self, model_id: str, fields: dict[str, Any]) -> None:
        await self.db["catalog_models"].update_one({"_id": model_id}, {"$set": fields})


class SQLiteStore(MemoryStore):
    """Durable single-worker demo store. One atomic JSON snapshot per write."""
    name = "sqlite"

    def __init__(self, path: Path) -> None:
        super().__init__()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.execute("CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY, body TEXT NOT NULL)")
        row = self.connection.execute("SELECT body FROM state WHERE id=1").fetchone()
        if row:
            data = json.loads(row[0])
            self.conversations = data["conversations"]
            self.artifacts.update(data["artifacts"])
            self.catalog, self.presets = data["catalog"], data["presets"]

    def flush(self):
        data = {"conversations": self.conversations, "artifacts": self.artifacts,
                "catalog": self.catalog, "presets": self.presets}
        with self.connection:
            self.connection.execute("INSERT OR REPLACE INTO state VALUES (1, ?)", (json.dumps(data),))

    async def save(self, conv):
        await super().save(conv)
        self.flush()

    async def save_artifact(self, kind, doc):
        await super().save_artifact(kind, doc)
        self.flush()

    async def update_artifact(self, kind, doc_id, fields):
        await super().update_artifact(kind, doc_id, fields)
        self.flush()

    async def seed_datapack(self, sheets, catalog, presets, reset=False):
        await super().seed_datapack(sheets, catalog, presets, reset)
        self.flush()

    async def upsert_asset(self, asset):
        await super().upsert_asset(asset)
        self.flush()

    async def update_model(self, model_id, fields):
        await super().update_model(model_id, fields)
        self.flush()


Store = MemoryStore | MongoStore | SQLiteStore


async def create_store() -> Store:
    if settings.mongodb_uri:
        try:
            store = MongoStore.connect(settings.mongodb_uri, settings.mongodb_db)
            await store.ping()
            await store.ensure_indexes()
            log.info("Using MongoDB database '%s'", settings.mongodb_db)
            return store
        except Exception as exc:
            raise RuntimeError("Configured MongoDB is unavailable; refusing silent data loss") from exc
    if settings.store_mode == "memory":
        return MemoryStore()
    return SQLiteStore(settings.sqlite_path)
