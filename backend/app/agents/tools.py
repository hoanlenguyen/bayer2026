"""Read-only catalog tools the agents can call. Metadata only, never raw rows."""
from __future__ import annotations

from typing import Any

from .. import catalog as cat
from ..llm import Tool


def search_catalog(query: str) -> dict[str, Any]:
    q = query.lower()
    words = [w for w in q.replace(",", " ").split() if len(w) > 2]

    def hit(*texts: str) -> bool:
        blob = " ".join(texts).lower()
        return q in blob or any(w in blob for w in words)

    C = cat.CATALOG
    return {
        "measures": [{"id": k, "name": m["name"], "dataset": m["dataset"]} for k, m in C["measures"].items()
                     if hit(k, m["name"], m["definition"], " ".join(m["keywords"]))][:10],
        "dimensions": [{"id": k, "name": d["name"]} for k, d in C["dimensions"].items() if hit(k, d["name"], " ".join(d["keywords"]))][:10],
        "reports": [{"id": a["id"], "name": a["name"], "measures": a["measures"]} for a in C["assets"]
                    if hit(a["name"], " ".join(a["measures"]))][:10],
    }


def get_measure(measure_id: str) -> dict[str, Any]:
    m = cat.CATALOG["measures"].get(measure_id)
    if not m:
        return {"error": f"No measure '{measure_id}' in the catalog"}
    return {"id": measure_id, **{k: m[k] for k in ("name", "definition", "expression", "unit", "dataset", "certified", "default_grain")}}


def get_dataset(dataset_id: str) -> dict[str, Any]:
    d = cat.CATALOG["datasets"].get(dataset_id)
    if not d:
        return {"error": f"No dataset '{dataset_id}' in the catalog"}
    return {"id": dataset_id, **d}


def get_relationships(dataset_ids: list[str]) -> dict[str, Any]:
    rels = [r for r in cat.CATALOG["relationships"] if r["from"].split(".")[0] in dataset_ids]
    return {"relationships": rels}


def get_report(report_id: str) -> dict[str, Any]:
    a = cat.asset_by_id(report_id)
    if not a:
        return {"error": f"No report '{report_id}' in the catalog"}
    keys = ("id", "name", "workspace", "grain", "measures", "dimensions", "datasets", "certified", "owner",
            "owner_status", "refresh_age_hours", "last_review", "conflicts")
    return {k: a.get(k) for k in keys}


CATALOG_TOOLS = [
    Tool("search_catalog", "Find measures, dimensions and existing reports by keyword.",
         {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}, search_catalog),
    Tool("get_measure", "Certified definition, expression and source dataset of a measure.",
         {"type": "object", "properties": {"measure_id": {"type": "string"}}, "required": ["measure_id"]}, get_measure),
    Tool("get_dataset", "Table name, columns, available dimensions, row count, refresh age and quality tests of a dataset.",
         {"type": "object", "properties": {"dataset_id": {"type": "string"}}, "required": ["dataset_id"]}, get_dataset),
    Tool("get_relationships", "Join relationships starting from the given datasets.",
         {"type": "object", "properties": {"dataset_ids": {"type": "array", "items": {"type": "string"}}}, "required": ["dataset_ids"]},
         get_relationships),
    Tool("get_report", "Metadata of an existing report: measures, dimensions, grain, owner, freshness.",
         {"type": "object", "properties": {"report_id": {"type": "string"}}, "required": ["report_id"]}, get_report),
]


def catalog_brief() -> str:
    """Compact catalog summary for prompts: IDs, names and definitions only."""
    C = cat.CATALOG
    measures = "\n".join(f"- {k}: {m['name']} ({m['unit']}). {m['definition']}" for k, m in C["measures"].items())
    dims = ", ".join(f"{k} ({d['name']})" for k, d in C["dimensions"].items())
    return f"MEASURES\n{measures}\n\nDIMENSIONS\n{dims}\n\nGRAINS: hour, day, week, month"
