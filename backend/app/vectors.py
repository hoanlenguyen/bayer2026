"""Vector search (RAG retrieval) over business requests and KPIs.

Two uses:
- **Duplicate detection at intake**: find earlier requests that ask the same
  thing ("same as 22 earlier requests, join them instead of a 23rd").
- **Semantic KPI discovery**: suggest governed KPIs for free-text wording that
  keyword matching misses.

Embeddings: OpenAI `text-embedding-3-small` when an API key is set, otherwise a
local hashed bag-of-words embedding (offline, deterministic, weaker).
Search: MongoDB Atlas Vector Search (`$vectorSearch`) when the collections and
the vector index exist in Atlas; otherwise exact cosine search in memory.
The index is built with `python -m app.build_vectors`.
"""
from __future__ import annotations

import hashlib
import logging
import math
import re
from dataclasses import dataclass
from typing import Any

from . import catalog as cat
from .settings import settings

log = logging.getLogger(__name__)

LOCAL_DIMS = 512
OPENAI_EMBED_MODEL = "text-embedding-3-small"
OPENAI_DIMS = 1536
INDEX_NAME = "vector_index"
COLLECTIONS = {"requests": "request_vectors", "kpis": "kpi_vectors"}
# Similarity above which two requests count as the same request, or as a related one. Scales differ per embedder.
DUPLICATE_THRESHOLD = {"openai": 0.85, "local": 0.80}
SIMILAR_THRESHOLD = {"openai": 0.60, "local": 0.40}
KPI_THRESHOLD = {"openai": 0.35, "local": 0.15}  # local embedder: only shared words count

_TOKEN = re.compile(r"[a-z0-9][a-z0-9\-]+")
_STOP = {"the", "and", "for", "our", "with", "can", "you", "need", "please", "have", "new", "a", "an", "of", "by",
         "we", "me", "show", "create", "build", "report", "dashboard", "i", "to", "in", "on", "is", "are", "what"}


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))  # vectors are L2-normalised


def _normalise(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class LocalEmbedder:
    """Hashed unigrams and bigrams. Offline and deterministic; good at near-duplicates, weak at synonyms."""

    name = "local"
    model = "hashed-bow-512"
    dims = LOCAL_DIMS

    @staticmethod
    def _stem(word: str) -> str:
        # Tiny suffix stripping so "replace" and "replacement" or "dashboards" and "dashboard" meet.
        for suffix in ("ments", "ment", "ings", "ing", "ations", "ation", "ers", "er", "ies", "es", "ed", "s"):
            if word.endswith(suffix) and len(word) - len(suffix) >= 4:
                return word[: -len(suffix)]
        return word

    def _vec(self, text: str) -> list[float]:
        words = [self._stem(w) for w in _TOKEN.findall(text.lower()) if w not in _STOP]
        feats = words + [f"{a} {b}" for a, b in zip(words, words[1:])]
        v = [0.0] * self.dims
        for f in feats:
            h = int(hashlib.md5(f.encode()).hexdigest(), 16)
            v[h % self.dims] += 1.0 if (h >> 9) % 2 else -1.0
        return _normalise(v)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]


class OpenAIEmbedder:
    name = "openai"

    def __init__(self, client: Any) -> None:
        self.client = client
        self.model = settings.embed_model or OPENAI_EMBED_MODEL
        self.dims = settings.embed_dims or OPENAI_DIMS

    async def embed(self, texts: list[str]) -> list[list[float]]:
        resp = await self.client.embeddings.create(model=self.model, input=texts)
        return [_normalise(list(d.embedding)) for d in resp.data]


def get_embedder(llm: Any) -> LocalEmbedder | OpenAIEmbedder:
    if getattr(llm, "enabled", False) and hasattr(getattr(llm, "client", None), "embeddings"):
        return OpenAIEmbedder(llm.client)
    return LocalEmbedder()


# ---------------------------------------------------------------- corpora
def request_docs() -> list[dict[str, Any]]:
    """One document per Business_Requests row (labels kept for display, not used for matching)."""
    return [{"_id": r["request_id"], "kind": "request", "text": r["request_text"], "request_date": r.get("request_date"),
             "product_context": r.get("product_context"), "market_context": r.get("market_context"),
             "urgency": r.get("urgency"), "status": r.get("status")}
            for r in cat.SHEETS.get("business_requests", [])]


def kpi_docs() -> list[dict[str, Any]]:
    return [{"_id": mid, "kind": "kpi", "name": m["name"], "domain": m["domain"],
             "text": f"{m['name']}. {m['domain']}. {m['definition']} Also called: {', '.join(m.get('keywords', []))}."}
            for mid, m in cat.CATALOG.get("measures", {}).items()]


CORPORA = {"requests": request_docs, "kpis": kpi_docs}


@dataclass
class Hit:
    doc: dict[str, Any]
    score: float


class VectorStore:
    """Embeds the corpora once and answers nearest-neighbour queries, in Atlas or in memory."""

    def __init__(self, embedder: LocalEmbedder | OpenAIEmbedder, mongo_db: Any | None = None) -> None:
        self.embedder = embedder
        self.db = mongo_db
        self._mem: dict[str, list[tuple[dict[str, Any], list[float]]]] = {}
        self.backend: dict[str, str] = {}

    async def _ensure_memory(self, corpus: str) -> None:
        if corpus in self._mem:
            return
        docs = CORPORA[corpus]()
        # Embed distinct texts once (the 150 requests share 10 texts).
        texts = list(dict.fromkeys(d["text"] for d in docs))
        vecs = dict(zip(texts, await self.embedder.embed(texts))) if texts else {}
        self._mem[corpus] = [(d, vecs[d["text"]]) for d in docs]

    async def _atlas_ready(self, corpus: str) -> bool:
        if self.db is None:
            return False
        try:
            col = self.db[COLLECTIONS[corpus]]
            sample = await col.find_one({}, {"embedding_model": 1})
            return bool(sample) and sample.get("embedding_model") == self.embedder.model
        except Exception:
            return False

    async def search(self, corpus: str, text: str, k: int = 5) -> list[Hit]:
        qv = (await self.embedder.embed([text]))[0]
        if await self._atlas_ready(corpus):
            try:
                pipeline = [
                    {"$vectorSearch": {"index": INDEX_NAME, "path": "embedding", "queryVector": qv,
                                       "numCandidates": max(100, k * 20), "limit": k}},
                    {"$addFields": {"score": {"$meta": "vectorSearchScore"}}},
                    {"$unset": "embedding"},
                ]
                rows = [d async for d in await self.db[COLLECTIONS[corpus]].aggregate(pipeline)]
                self.backend[corpus] = "atlas"
                # Atlas cosine score is (1 + cos) / 2; convert back to cosine for one scale everywhere.
                return [Hit({k_: v for k_, v in r.items() if k_ != "score"}, round(2 * r["score"] - 1, 4)) for r in rows]
            except Exception as exc:
                log.warning("Atlas $vectorSearch failed (%s); using in-memory search.", exc)
        await self._ensure_memory(corpus)
        self.backend[corpus] = "memory"
        scored = sorted(((d, _cosine(qv, v)) for d, v in self._mem[corpus]), key=lambda x: -x[1])
        return [Hit(d, round(s, 4)) for d, s in scored[:k]]

    async def all_vectors(self, corpus: str) -> list[tuple[dict[str, Any], list[float]]]:
        await self._ensure_memory(corpus)
        return self._mem[corpus]


# ---------------------------------------------------------------- features
async def similar_requests(store: VectorStore, text: str, k: int = 30) -> dict[str, Any]:
    """Earlier requests that ask the same thing, grouped by text, with how often each was asked."""
    hits = await store.search("requests", text, k=k)
    dup_t, sim_t = DUPLICATE_THRESHOLD[store.embedder.name], SIMILAR_THRESHOLD[store.embedder.name]
    rows = cat.SHEETS.get("business_requests", [])
    groups: dict[str, dict[str, Any]] = {}
    for h in hits:
        if h.doc["text"] in groups:
            continue
        same_text = [r["request_id"] for r in rows if r["request_text"] == h.doc["text"]]
        groups[h.doc["text"]] = {"text": h.doc["text"], "similarity": h.score, "asked": len(same_text),
                                 "request_ids": same_text[:12],
                                 "match": "same" if h.score >= dup_t else "similar" if h.score >= sim_t else "unrelated"}
    ordered = sorted(groups.values(), key=lambda g: -g["similarity"])
    dupes = [g for g in ordered if g["match"] == "same"]
    related = [g for g in ordered if g["match"] == "similar"]
    return {"duplicates": dupes, "similar": related[:3], "nearest": ordered[:3],
            "duplicate_count": sum(g["asked"] for g in dupes), "thresholds": {"same": dup_t, "similar": sim_t},
            "embedder": store.embedder.name, "model": store.embedder.model, "search": store.backend.get("requests", "memory")}


async def suggest_kpis(store: VectorStore, text: str, k: int = 3) -> list[dict[str, Any]]:
    hits = await store.search("kpis", text, k=k)
    t = KPI_THRESHOLD[store.embedder.name]
    return [{"measure_id": h.doc["_id"], "name": h.doc["name"], "similarity": h.score} for h in hits if h.score >= t]


async def request_clusters(store: VectorStore) -> list[dict[str, Any]]:
    """Group the intake queue into distinct asks (greedy, by duplicate threshold)."""
    vecs = await store.all_vectors("requests")
    threshold = DUPLICATE_THRESHOLD[store.embedder.name]
    clusters: list[dict[str, Any]] = []
    for doc, v in vecs:
        for c in clusters:
            if _cosine(v, c["_vec"]) >= threshold:
                c["request_ids"].append(doc["_id"])
                c["urgency"][doc.get("urgency")] += 1
                c["status"][doc.get("status")] += 1
                break
        else:
            from collections import Counter

            clusters.append({"text": doc["text"], "_vec": v, "request_ids": [doc["_id"]],
                             "urgency": Counter({doc.get("urgency"): 1}), "status": Counter({doc.get("status"): 1})})
    return sorted(({"text": c["text"], "count": len(c["request_ids"]), "request_ids": c["request_ids"],
                    "urgency": dict(c["urgency"]), "status": dict(c["status"])} for c in clusters),
                  key=lambda c: -c["count"])


async def build_atlas_index(store: VectorStore) -> dict[str, Any]:
    """Write embeddings to Atlas and create the vector search index on each collection."""
    from pymongo.operations import SearchIndexModel

    if store.db is None:
        raise RuntimeError("MongoDB is not configured")
    report = {}
    for corpus, col_name in COLLECTIONS.items():
        store._mem.pop(corpus, None)
        pairs = await store.all_vectors(corpus)
        col = store.db[col_name]
        await col.delete_many({})
        if pairs:
            await col.insert_many([{**d, "embedding": v, "embedding_model": store.embedder.model} for d, v in pairs])
        existing = [i["name"] async for i in await col.list_search_indexes()]
        definition = {"fields": [{"type": "vector", "path": "embedding", "numDimensions": store.embedder.dims,
                                  "similarity": "cosine"}]}
        if INDEX_NAME in existing:
            await col.update_search_index(INDEX_NAME, definition)
        else:
            await col.create_search_index(SearchIndexModel(definition=definition, name=INDEX_NAME, type="vectorSearch"))
        report[col_name] = {"documents": len(pairs), "dims": store.embedder.dims, "model": store.embedder.model}
    return report
