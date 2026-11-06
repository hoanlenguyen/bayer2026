"""The analytics catalog and department presets.

The catalog holds metadata only (measures, dimensions, datasets, existing
reports). It is loaded from the store at startup; when the store is empty it is
seeded from app/data/*.json. The AI reasons over this metadata, never over raw
production data.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent / "data"

SEED_CATALOG: dict[str, Any] = {k: v for k, v in json.loads((DATA_DIR / "catalog.json").read_text(encoding="utf-8")).items()
                                if not k.startswith("_")}
SEED_PRESETS: list[dict[str, Any]] = json.loads((DATA_DIR / "presets.json").read_text(encoding="utf-8"))

# Live, in-process copies used by the pipeline. Mutated in place so imports stay valid.
CATALOG: dict[str, Any] = copy.deepcopy(SEED_CATALOG)
PRESETS: list[dict[str, Any]] = copy.deepcopy(SEED_PRESETS)

DATASET_DEPARTMENT = {
    "shipments_fact": "Supply chain",
    "inventory_snapshot": "Supply chain",
    "production_batches_fact": "Production",
    "line_events_fact": "Production",
    "quality_deviations": "Quality",
    "hr_attendance": "HR",
    "training_records": "HR",
    "cost_ledger": "Finance",
}


async def init(store: Any) -> str:
    """Load the catalog from the store, seeding it first if empty. Returns the source used."""
    await store.seed_catalog(SEED_CATALOG, SEED_PRESETS)
    loaded = await store.load_catalog()
    presets = await store.load_presets()
    if loaded:
        CATALOG.clear()
        CATALOG.update(loaded)
    if presets:
        PRESETS[:] = presets
    return store.name


def preset_by_id(preset_id: str | None) -> dict[str, Any] | None:
    return next((p for p in PRESETS if p["id"] == preset_id), None)


def measure(mid: str) -> dict[str, Any]:
    return CATALOG["measures"][mid]


def asset_by_id(aid: str) -> dict[str, Any] | None:
    return next((a for a in CATALOG["assets"] if a["id"] == aid), None)


def department_for(measures: list[str]) -> str | None:
    for m in measures:
        ds = CATALOG["measures"].get(m, {}).get("dataset")
        if ds in DATASET_DEPARTMENT:
            return DATASET_DEPARTMENT[ds]
    return None


def reset_catalog() -> None:
    """Restore the seed catalog (used by tests)."""
    CATALOG.clear()
    CATALOG.update(copy.deepcopy(SEED_CATALOG))
    PRESETS[:] = copy.deepcopy(SEED_PRESETS)
