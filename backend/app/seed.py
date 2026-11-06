"""Seed the MongoDB catalog from app/data/*.json.

    python -m app.seed            # seed only if the catalog is empty
    python -m app.seed --reset    # replace catalog and presets (keeps conversations)
"""
from __future__ import annotations

import argparse
import asyncio

from .catalog import SEED_CATALOG, SEED_PRESETS
from .settings import settings
from .store import MongoStore


async def main(reset: bool) -> None:
    if not settings.mongodb_uri:
        raise SystemExit("MONGODB_URI is not set. Add it to backend/.env first.")
    store = MongoStore.connect(settings.mongodb_uri, settings.mongodb_db)
    await store.ping()
    await store.ensure_indexes()
    await store.seed_catalog(SEED_CATALOG, SEED_PRESETS, reset=reset)
    count = await store.db["catalog_assets"].count_documents({})
    print(f"Catalog in '{settings.mongodb_db}': {count} reports, {len(SEED_CATALOG['measures'])} measures.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="replace the existing catalog and presets")
    asyncio.run(main(parser.parse_args().reset))
