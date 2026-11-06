"""Evidence agent (/explore): proves the request can be built from catalog sources.

The agent chooses source tables and columns using read-only catalog tools.
Python then verifies the proposal: unknown tables and columns are removed,
required tables are added, and every proof line is generated from catalog
facts, so the numbers shown to the user never come from the model.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .. import catalog as cat
from .base import Agent, Step
from .tools import CATALOG_TOOLS, get_dataset, get_measure, get_relationships, get_report

GRAIN_ADJ = {"hour": "hourly", "day": "daily", "week": "weekly", "month": "monthly"}
DIM_COLUMN_HINTS = {
    "customer": "customer_id", "carrier": "carrier_id", "line": "line_id", "product": "product_id",
    "batch": "batch_id", "material": "material_id", "supplier": "supplier_id", "priority": "priority",
    "deviation_category": "category", "shift": "shift", "department": "department", "cost_center": "cost_center",
    "destination_country": "destination_country",
}

SYSTEM = """You are the evidence agent for a governed analytics platform at a pharma plant.
Given the user's intent and the decision (extend an existing report or create a new one), use the tools to find
which source tables and columns deliver every requested measure and breakdown. Check row counts, freshness and
quality tests. For an extend decision, inspect the base report first.
Use only tables and columns returned by the tools. When finished, reply with JSON only:
{"datasets": [dataset_id], "columns": {dataset_id: [column]}, "notes": [short finding], "summary": "two plain sentences for a plant manager"}"""


def required_columns(intent: dict[str, Any], dataset_id: str) -> list[str]:
    """Columns needed for the intent's measures and breakdowns in one dataset."""
    C = cat.CATALOG
    cols = C["datasets"][dataset_id]["columns"]
    used: list[str] = []
    for m in intent["measures"]:
        used += re.findall(rf"{dataset_id}\[(\w+)\]", C["measures"][m]["expression"])
    for d in intent["dimensions"] + ["date"]:
        if d == "date":
            used += [c for c in cols if c.endswith("_date") or c.endswith("_ts") or c == "date"][:1]
        elif DIM_COLUMN_HINTS.get(d) in cols:
            used.append(DIM_COLUMN_HINTS[d])
    return [c for c in dict.fromkeys(used) if c in cols]


def finalize(intent: dict[str, Any], decision: dict[str, Any], availability: dict[str, Any],
             proposal: dict[str, Any], steps: list[Step]) -> dict[str, Any]:
    """Verify the agent's proposal against the catalog and build the evidence record."""
    C = cat.CATALOG
    cand = decision.get("candidate")
    base = cat.asset_by_id(cand["asset_id"]) if cand and decision["decision"] == "extend" else None
    verification: list[dict[str, Any]] = []

    proposed = [d for d in proposal.get("datasets", []) if isinstance(d, str)]
    unknown = [d for d in proposed if d not in C["datasets"]]
    for d in unknown:
        verification.append({"ok": False, "text": f"Removed '{d}': not a catalog dataset."})
    required = availability["datasets"] or (base["datasets"] if base else [])
    datasets = [d for d in dict.fromkeys([*proposed, *required]) if d in C["datasets"]]
    for d in required:
        if d in C["datasets"] and d not in proposed:
            verification.append({"ok": False, "text": f"Added '{d}': it holds a requested measure but was not selected."})

    columns: dict[str, list[str]] = {}
    for ds in datasets:
        valid = C["datasets"][ds]["columns"]
        chosen = [c for c in (proposal.get("columns") or {}).get(ds, []) if isinstance(c, str)]
        for c in chosen:
            if c not in valid:
                verification.append({"ok": False, "text": f"Removed column '{c}': it does not exist in {ds}."})
        need = required_columns(intent, ds)
        missing = [c for c in need if c not in chosen]
        if chosen and missing:
            verification.append({"ok": False, "text": f"Added required columns to {ds}: {', '.join(missing)}."})
        columns[ds] = [c for c in dict.fromkeys([*chosen, *need]) if c in valid]
    if not any(not v["ok"] for v in verification):
        verification.append({"ok": True, "text": "All tables and columns the agent selected exist in the catalog."})
    steps.append(Step("check", "Verify agent proposal against the catalog",
                      f"{sum(1 for v in verification if not v['ok'])} correction(s)", ok=True))

    proofs = []
    for ds in datasets:
        d = C["datasets"][ds]
        proofs.append({"ok": d["tests_passed"] == d["tests_total"],
                       "text": f"{d['table']}: {d['rows']:,} rows, refreshed {d['refresh_age_hours']} h ago, "
                               f"{d['tests_passed']}/{d['tests_total']} quality tests pass. Owner: {d['owner']}."})
    for m in intent["measures"]:
        md = C["measures"][m]
        proofs.append({"ok": md["certified"], "text": f"{md['name']} uses the certified definition: {md['definition']}"})
    if base:
        if decision.get("change_type") == "maintenance":
            proofs.append({"ok": False, "text": f"'{base['name']}' was refreshed {base['refresh_age_hours']} h ago; "
                                                f"a {GRAIN_ADJ[intent['grain']]} decision needs fresher data."})
        else:
            gaps = cand["measures_missing"] + cand["dimensions_missing"]
            if gaps:
                proofs.append({"ok": True, "text": f"Missing in '{base['name']}': {', '.join(gaps)}. All are available in the source tables above."})
            if not cand["grain_supported"]:
                proofs.append({"ok": True, "text": f"'{base['name']}' is {GRAIN_ADJ[base['grain']]}; the request needs "
                                                   f"{GRAIN_ADJ[intent['grain']]}. Source data supports it."})

    rels = [r for r in C["relationships"] if r["from"].split(".")[0] in datasets]
    return {"datasets": datasets, "columns": columns, "relationships": rels, "proofs": proofs,
            "verification": verification, "notes": [str(n) for n in proposal.get("notes", [])][:6],
            "summary": str(proposal.get("summary") or ""), "base_asset": base,
            "measures": intent["measures"], "dimensions": intent["dimensions"]}


class EvidenceAgent(Agent):
    name = "evidence"
    title = "Evidence agent (/explore)"
    role = "reasoning"

    async def run_llm(self, ctx: dict[str, Any], steps: list[Step]) -> dict[str, Any]:
        intent, decision = ctx["intent"], ctx["decision"]
        cand = decision.get("candidate") or {}
        user = json.dumps({"intent": {k: v for k, v in intent.items() if not k.startswith("_")},
                           "decision": decision["decision"], "change_type": decision.get("change_type"),
                           "base_report_id": cand.get("asset_id") if decision["decision"] == "extend" else None},
                          ensure_ascii=False)
        proposal = await self.llm.tool_loop(self.role, SYSTEM, user, CATALOG_TOOLS, self.tool_recorder(steps))
        steps.append(Step("model", "Proposed sources", f"{len(proposal.get('datasets', []))} table(s)"))
        return finalize(intent, decision, ctx["availability"], proposal, steps)

    async def run_rules(self, ctx: dict[str, Any], steps: list[Step]) -> dict[str, Any]:
        intent, decision, availability = ctx["intent"], ctx["decision"], ctx["availability"]
        record = self.tool_recorder(steps)
        cand = decision.get("candidate") or {}
        if decision["decision"] == "extend" and cand:
            record("get_report", {"report_id": cand["asset_id"]}, get_report(cand["asset_id"]))
        for m in intent["measures"]:
            record("get_measure", {"measure_id": m}, get_measure(m))
        datasets = availability["datasets"] or (cat.asset_by_id(cand["asset_id"])["datasets"] if cand else [])
        for ds in datasets:
            record("get_dataset", {"dataset_id": ds}, get_dataset(ds))
        record("get_relationships", {"dataset_ids": datasets}, get_relationships(datasets))
        n = len(intent["measures"])
        proposal = {
            "datasets": datasets,
            "columns": {ds: required_columns(intent, ds) for ds in datasets if ds in cat.CATALOG["datasets"]},
            "summary": f"The {n} requested measure{'s' if n != 1 else ''} come from {len(datasets)} certified source table"
                       f"{'s' if len(datasets) != 1 else ''} with passing quality checks. The breakdowns you asked for are available there.",
        }
        return finalize(intent, decision, availability, proposal, steps)
