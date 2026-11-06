"""Loads the sample analytics catalog and department presets.

The catalog holds metadata only (measures, dimensions, datasets, existing
reports). The AI reasons over this metadata, never over raw production data.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent / "data"

_BASE_CATALOG: dict[str, Any] = json.loads((DATA_DIR / "catalog.json").read_text(encoding="utf-8"))
PRESETS: list[dict[str, Any]] = json.loads((DATA_DIR / "presets.json").read_text(encoding="utf-8"))

# Mutable runtime copy: assets registered during the session are appended here,
# so a second identical request is answered by reuse.
CATALOG: dict[str, Any] = copy.deepcopy(_BASE_CATALOG)

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
    """Restore the original sample catalog (used by tests)."""
    CATALOG.clear()
    CATALOG.update(copy.deepcopy(_BASE_CATALOG))
