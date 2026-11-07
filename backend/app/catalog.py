"""The analytics catalog and presets, built from the SinceAI data pack.

Loaded from the store at startup. When the store is empty, it is seeded from
the workbook in materials/ (see app/datapack.py). Metadata only: the AI reasons
over KPI definitions, models, reports, usage, lineage and governance signals.
"""
from __future__ import annotations

import copy
from functools import lru_cache
from typing import Any

from . import datapack

CATALOG: dict[str, Any] = {}
PRESETS: list[dict[str, Any]] = []
SHEETS: dict[str, list[dict[str, Any]]] = {}


@lru_cache(maxsize=1)
def _seed() -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    return datapack.load()


def seed_catalog() -> dict[str, Any]:
    return copy.deepcopy(_seed()[1])


def seed_presets() -> list[dict[str, Any]]:
    return copy.deepcopy(datapack.PRESETS + datapack.SCENARIOS)


def reset_catalog() -> None:
    """Restore the catalog from the workbook (used by tests and the in-memory store)."""
    sheets, catalog = _seed()
    CATALOG.clear()
    CATALOG.update(copy.deepcopy(catalog))
    PRESETS[:] = seed_presets()
    SHEETS.clear()
    SHEETS.update(sheets)


async def init(store: Any) -> str:
    """Load the catalog from the store, seeding it from the workbook first if empty."""
    sheets, catalog = _seed()
    presets = seed_presets()
    await store.seed_datapack(sheets, catalog, presets)
    loaded = await store.load_catalog()
    CATALOG.clear()
    CATALOG.update(loaded or copy.deepcopy(catalog))
    # These built-in requests ship with the application, including when the estate is already seeded.
    PRESETS[:] = presets
    SHEETS.clear()
    SHEETS.update(sheets)
    if await store.count_artifacts("actions") == 0:
        from .actions import sample_actions

        for a in sample_actions():
            await store.save_artifact("actions", a)
    return store.name


def preset_by_id(preset_id: str | None) -> dict[str, Any] | None:
    return next((p for p in PRESETS if p["id"] == preset_id), None)


def measure(mid: str) -> dict[str, Any]:
    return CATALOG["measures"][mid]


def asset_by_id(aid: str | None) -> dict[str, Any] | None:
    return next((a for a in CATALOG.get("assets", []) if a["id"] == aid), None) if aid else None


def model_by_id(mid: str | None) -> dict[str, Any] | None:
    return CATALOG.get("models", {}).get(mid) if mid else None


def department_for(measures: list[str]) -> str | None:
    for m in measures:
        if m in CATALOG.get("measures", {}):
            return CATALOG["measures"][m]["domain"]
    return None


reset_catalog()
