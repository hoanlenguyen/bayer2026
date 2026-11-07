"""Persistence: MongoDB when MONGODB_URI is set, otherwise in memory.

Collections
  conversations        chat messages, current intent, runs with every streamed event
  intents              each clarified intent (one per run)
  evidence             verified evidence records
  specs                DashboardSpec versions with status draft / approved / rejected
  agent_runs           audit log: agent, mode, model, steps, duration
  actions              follow-up actions with owner, due date, status history and verification
  catalog_<key>        the analytics catalog built from the SinceAI data pack: measures, dimensions,
                       models, assets, owners, workspaces, products, markets, lineage, rules
  datapack_<sheet>     every table sheet of the workbook, row for row (raw, for querying)
  presets              the 10 SinceAI business requests plus estate scenarios
"""
from __future__ import annotations

import copy
import logging
from typing import Any

from .settings import settings

log = logging.getLogger(__name__)

ARTIFACTS = ("intents", "evidence", "specs", "agent_runs", "actions", "briefing_selections", "dashboard_drafts", "dashboards")
# Deleted along with a conversation. Actions stay: a person accepted them, and they outlive the chat that proposed them.
CONVERSATION_ARTIFACTS = ("intents", "evidence", "specs", "agent_runs")
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

    async def delete(self, conv_id: str) -> bool:
        if self.conversations.pop(conv_id, None) is None:
            return False
        for kind in CONVERSATION_ARTIFACTS:
            self.artifacts[kind] = {k: d for k, d in self.artifacts[kind].items() if d.get("conversation_id") != conv_id}
        return True

    # pipeline artifacts
    async def save_artifact(self, kind: str, doc: dict[str, Any]) -> None:
        self.artifacts[kind][doc["_id"]] = copy.deepcopy(doc)

    async def insert_action_once(self, action: dict[str, Any]) -> dict[str, Any]:
        saved = self.artifacts["actions"].setdefault(action["_id"], copy.deepcopy(action))
        return copy.deepcopy(saved)

    async def advance_dashboard(self, doc: dict, previous_version: int) -> bool:
        existing = self.artifacts["dashboard_drafts"].get(doc["_id"], {})
        if existing.get("version", 0) != previous_version or existing.get("built_id"):
            return False
        self.artifacts["dashboard_drafts"][doc["_id"]] = copy.deepcopy(doc)
        return True

    async def publish_dashboard_once(self, doc: dict) -> dict:
        return copy.deepcopy(self.artifacts["dashboards"].setdefault(doc["_id"], copy.deepcopy(doc)))

    async def dashboard_directory(self) -> list[dict]:
        docs = sorted(self.artifacts["dashboards"].values(), key=lambda d: d["created_at"], reverse=True)
        return [{k: d[k] for k in ("id", "title", "created_at", "period", "decision_goal")} for d in docs]

    async def replace_briefing_action(self, action: dict[str, Any], prior_history: list) -> bool:
        current = self.artifacts["actions"].get(action["_id"])
        if not current or current["history"] != prior_history:
            return False
        self.artifacts["actions"][action["_id"]] = copy.deepcopy(action)
        return True

    async def list_briefing_actions(self, team: str, limit: int) -> list[dict[str, Any]]:
        items = [a for a in self.artifacts["actions"].values() if a.get("briefing_snapshot", {}).get("team") == team]
        return copy.deepcopy(sorted(items, key=lambda a: (a["created_at"], a["_id"]), reverse=True)[:limit])

    async def list_run_actions(self, conversation_id: str, run_id: str) -> list[dict[str, Any]]:
        return copy.deepcopy([a for a in self.artifacts["actions"].values()
                              if a.get("conversation_id") == conversation_id and a.get("run_id") == run_id])

    async def update_artifact(self, kind: str, doc_id: str, fields: dict[str, Any]) -> None:
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

    async def delete(self, conv_id: str) -> bool:
        result = await self.db["conversations"].delete_one({"_id": conv_id})
        if not result.deleted_count:
            return False
        for kind in CONVERSATION_ARTIFACTS:
            await self.db[kind].delete_many({"conversation_id": conv_id})
        return True

    # pipeline artifacts
    async def save_artifact(self, kind: str, doc: dict[str, Any]) -> None:
        await self.db[kind].replace_one({"_id": doc["_id"]}, doc, upsert=True)

    async def insert_action_once(self, action: dict[str, Any]) -> dict[str, Any]:
        from pymongo import ReturnDocument

        return await self.db["actions"].find_one_and_update(
            {"_id": action["_id"]}, {"$setOnInsert": action}, upsert=True, return_document=ReturnDocument.AFTER)

    async def advance_dashboard(self, doc: dict, previous_version: int) -> bool:
        from pymongo.errors import DuplicateKeyError

        if previous_version == 0:
            try:
                await self.db["dashboard_drafts"].insert_one(doc)
                return True
            except DuplicateKeyError:
                return False
        result = await self.db["dashboard_drafts"].replace_one(
            {"_id": doc["_id"], "version": previous_version, "built_id": None}, doc)
        return bool(result.matched_count)

    async def publish_dashboard_once(self, doc: dict) -> dict:
        from pymongo import ReturnDocument

        return await self.db["dashboards"].find_one_and_update(
            {"_id": doc["_id"]}, {"$setOnInsert": doc}, upsert=True, return_document=ReturnDocument.AFTER)

    async def dashboard_directory(self) -> list[dict]:
        fields = {k: 1 for k in ("id", "title", "created_at", "period", "decision_goal")}
        return [d async for d in self.db["dashboards"].find({}, {**fields, "_id": 0}).sort("created_at", -1)]

    async def replace_briefing_action(self, action: dict[str, Any], prior_history: list) -> bool:
        result = await self.db["actions"].replace_one({"_id": action["_id"], "history": prior_history}, action)
        return bool(result.matched_count)

    async def list_briefing_actions(self, team: str, limit: int) -> list[dict[str, Any]]:
        cursor = self.db["actions"].find({"briefing_snapshot.team": team}).sort([("created_at", -1), ("_id", -1)])
        return [a async for a in cursor.limit(limit)]

    async def list_run_actions(self, conversation_id: str, run_id: str) -> list[dict[str, Any]]:
        return [a async for a in self.db["actions"].find({"conversation_id": conversation_id, "run_id": run_id})]

    async def update_artifact(self, kind: str, doc_id: str, fields: dict[str, Any]) -> None:
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
