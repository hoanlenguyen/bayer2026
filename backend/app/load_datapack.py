"""Load the SinceAI data pack into MongoDB.

    python -m app.load_datapack                     # workbook in materials/, skip if already loaded
    python -m app.load_datapack --reset             # replace catalog, raw sheets and presets
    python -m app.load_datapack path/to/file.xlsx --reset

Writes one `datapack_<sheet>` collection per table sheet (raw rows), the derived
`catalog_*` collections the pipeline uses, and `presets`. Conversations,
specs and actions are kept.
"""
from __future__ import annotations

import argparse
import asyncio

from . import datapack
from .settings import settings
from .store import MongoStore


async def main(path: str | None, reset: bool) -> None:
    if not settings.mongodb_uri:
        raise SystemExit("MONGODB_URI is not set. Add it to backend/.env first.")
    sheets, catalog = datapack.load(path)
    store = MongoStore.connect(settings.mongodb_uri, settings.mongodb_db)
    await store.ping()
    await store.ensure_indexes()
    await store.seed_datapack(sheets, catalog, datapack.PRESETS + datapack.SCENARIOS, reset=reset)
    counts = {name: await store.db[f"datapack_{name}"].count_documents({}) for name in sheets}
    print(f"Database '{settings.mongodb_db}':")
    for name, n in counts.items():
        print(f"  datapack_{name:<24} {n:>5} rows")
    print(f"  catalog: {len(catalog['assets'])} assets, {len(catalog['models'])} models, {len(catalog['measures'])} measures")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path", nargs="?", help="workbook path (default: materials/…Builder_Data_Pack.xlsx)")
    parser.add_argument("--reset", action="store_true", help="replace what is already loaded")
    args = parser.parse_args()
    asyncio.run(main(args.path, args.reset))
