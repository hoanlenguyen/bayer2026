"""Build the Atlas Vector Search index for business requests and KPIs.

    python -m app.build_vectors

Embeds the 150 Business_Requests and the 18 governed KPIs (OpenAI embeddings if
OPENAI_API_KEY is set, otherwise the local hashed embedding), writes them to the
`request_vectors` and `kpi_vectors` collections and creates a `vector_index`
(type vectorSearch, cosine) on each. Atlas needs a minute to build the index;
until then the backend uses in-memory search automatically. Re-run after
changing the embedding model or the data pack.
"""
from __future__ import annotations

import asyncio

from . import catalog as cat
from .llm import get_llm
from .settings import settings
from .store import MongoStore
from .vectors import VectorStore, build_atlas_index, get_embedder


async def main() -> None:
    if not settings.mongodb_uri:
        raise SystemExit("MONGODB_URI is not set. Add it to backend/.env first.")
    store = MongoStore.connect(settings.mongodb_uri, settings.mongodb_db)
    await store.ping()
    await cat.init(store)
    vectors = VectorStore(get_embedder(get_llm()), store.db)
    report = await build_atlas_index(vectors)
    for col, info in report.items():
        print(f"{col}: {info['documents']} documents, {info['dims']} dims ({info['model']}), index 'vector_index' requested")
    print("Atlas builds the index in about a minute. Check it under Atlas Search in the Atlas UI.")


if __name__ == "__main__":
    asyncio.run(main())
