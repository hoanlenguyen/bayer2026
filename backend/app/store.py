"""Conversation storage: MongoDB when MONGODB_URI is set, otherwise in memory."""
from __future__ import annotations

import copy
import logging
from typing import Any, Protocol

from .settings import settings

log = logging.getLogger(__name__)


class Store(Protocol):
    name: str

    async def get(self, conv_id: str) -> dict[str, Any] | None: ...
    async def save(self, conv: dict[str, Any]) -> None: ...
    async def list(self, limit: int = 20) -> list[dict[str, Any]]: ...


class MemoryStore:
    name = "memory"

    def __init__(self) -> None:
        self._data: dict[str, dict[str, Any]] = {}

    async def get(self, conv_id):
        doc = self._data.get(conv_id)
        return copy.deepcopy(doc) if doc else None

    async def save(self, conv):
        self._data[conv["_id"]] = copy.deepcopy(conv)

    async def list(self, limit=20):
        docs = sorted(self._data.values(), key=lambda d: d.get("updated_at", ""), reverse=True)[:limit]
        return [{"_id": d["_id"], "title": d.get("title"), "updated_at": d.get("updated_at")} for d in docs]


class MongoStore:
    name = "mongodb"

    def __init__(self, uri: str, db: str) -> None:
        from pymongo import AsyncMongoClient

        self.client = AsyncMongoClient(uri, serverSelectionTimeoutMS=4000)
        self.col = self.client[db]["conversations"]

    async def ping(self) -> None:
        await self.client.admin.command("ping")

    async def get(self, conv_id):
        return await self.col.find_one({"_id": conv_id})

    async def save(self, conv):
        await self.col.replace_one({"_id": conv["_id"]}, conv, upsert=True)

    async def list(self, limit=20):
        cursor = self.col.find({}, {"title": 1, "updated_at": 1}).sort("updated_at", -1).limit(limit)
        return [d async for d in cursor]


async def create_store() -> Store:
    if settings.mongodb_uri:
        try:
            store = MongoStore(settings.mongodb_uri, settings.mongodb_db)
            await store.ping()
            log.info("Using MongoDB database '%s'", settings.mongodb_db)
            return store
        except Exception as exc:
            log.warning("MongoDB unavailable (%s). Falling back to in-memory storage.", exc)
    return MemoryStore()
