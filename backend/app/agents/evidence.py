"""Evidence agent (/explore): proves what the recommendation rests on.

The agent picks the shared semantic model and inspects KPIs, reports, usage and
lineage with read-only catalog tools. Python then verifies the proposal (the
model exists and serves the requested KPIs) and writes every proof line from
catalog facts, so numbers shown to the user never come from the model
(RULE-004 lineage, RULE-008 explain every lifecycle action).
"""
from __future__ import annotations

import json
from typing import Any

from .. import catalog as cat
from .base import Agent, Step
from .tools import CATALOG_TOOLS, get_kpi, get_lineage, get_model, get_report

SYSTEM = """You are the evidence agent for governed analytics at Bayer Pharmaceuticals.
Given the intent and the lifecycle decision, use the tools to confirm: the approved KPI definitions (and which variants
must not be used), the shared semantic model to build on, the existing report involved (usage, owner, signals,
migration backlog) and the downstream impact from lineage. Use only ids returned by the tools.
When finished, reply with JSON only:
{"semantic_model": model_id, "notes": [short finding], "summary": "two plain sentences for a business user"}"""


def _pick_model(decision: dict[str, Any], availability: dict[str, Any], base: dict[str, Any] | None) -> str | None:
    if decision.get("target_model_id"):
        return decision["target_model_id"]
    if base and base.get("model_id") and decision["decision"] in ("repair", "consolidate", "reuse"):
        return base["model_id"]
    return (availability.get("best_model") or {}).get("id")


def finalize(intent: dict[str, Any], decision: dict[str, Any], availability: dict[str, Any],
             proposal: dict[str, Any], steps: list[Step]) -> dict[str, Any]:
    C = cat.CATALOG
    cand = decision.get("candidate") or {}
    base = cat.asset_by_id(cand.get("asset_id")) if decision["decision"] in ("repair", "consolidate", "migrate") else None
    verification: list[dict[str, Any]] = []
    req = intent.get("measures", [])

    expected = _pick_model(decision, availability, base)
    proposed = proposal.get("semantic_model")
    model_id = expected
    if proposed and proposed != expected:
        pm = cat.model_by_id(proposed)
        if not pm:
            verification.append({"ok": False, "text": f"Ignored model '{proposed}': not in the catalog."})
        elif not set(req) & set(pm["measures"]):
            verification.append({"ok": False, "text": f"Ignored model {proposed}: it serves none of the requested KPIs."})
        elif decision["decision"] in ("repair", "consolidate"):
            verification.append({"ok": False, "text": f"Kept {expected}: a {decision['decision']} stays on the report's own model."})
        else:
            model_id = proposed
            verification.append({"ok": True, "text": f"Agent chose {proposed} instead of {expected}; it serves requested KPIs."})
    if not any(not v["ok"] for v in verification):
        verification.append({"ok": True, "text": "The agent's model choice and ids match the catalog."})
    steps.append(Step("check", "Verify agent proposal against the catalog",
                      f"{sum(1 for v in verification if not v['ok'])} correction(s)"))

    model = cat.model_by_id(model_id)
    proofs: list[dict[str, Any]] = []
    if model:
        served = [m for m in req if m in model["measures"]]
        proofs.append({"ok": model["refresh_status"] == "healthy" and model["endorsement"] != "none",
                       "text": f"Shared model {model['id']} '{model['name']}' ({model['platform']}, {model['endorsement']}): "
                               f"refresh {model['refresh_status']} ({model['refresh_frequency']}), AI readiness {model['ai_readiness']}, "
                               f"serves {len(served)} of {len(req)} requested KPIs. Owner: {model['owner']}."})
        gaps = [C["measures"][m]["name"] for m in req if m not in model["measures"]]
        if gaps:
            proofs.append({"ok": False, "text": f"Model does not yet serve: {', '.join(gaps)}. Add the approved measures to it."})
        for issue in model["dq_issues"]:
            proofs.append({"ok": False, "text": f"Data quality {issue['id']} ({issue['severity']}): {issue['field']} = {issue['value']}. {issue['impact']}"})
    for m in req:
        md = C["measures"][m]
        avoid = ", ".join(f"{v['name']} ({v['status'].replace('_', ' ')})" for v in md["variants"]) or "none"
        proofs.append({"ok": md["certified"], "text": f"{md['name']}: use approved {md['kpi_id']}. Variants not to use: {avoid}."})
    if base:
        open_sig = [s for s in base["signals"] if s["status"] == "open"]
        proofs.append({"ok": base["owner_status"] == "active",
                       "text": f"{base['id']} '{base['name']}' ({base['platform']} {base['asset_type']}, {base['product_scope']} / {base['market_scope']}): "
                               f"{base['views_90d']:,} views and {base['users_90d']:,} users in 90 days; lifecycle {base['lifecycle']}; "
                               f"owner {base['owner']} ({base['owner_status']}); {len(open_sig)} open signal(s)"
                               + (f": {', '.join(s['code'] for s in open_sig)}" if open_sig else "") + "."})
        if base.get("migration"):
            mg = base["migration"]
            proofs.append({"ok": True, "text": f"Migration backlog: path {mg['recommended_path_candidate']}, target {mg['candidate_target_model_id']}, "
                                               f"complexity {mg['complexity']}, status {mg['status']} ({mg['synthetic_reason']})."})
    impact_node = (base or {}).get("id") or model_id
    lineage = get_lineage(impact_node) if impact_node else {"downstream_count": 0, "upstream": []}
    if impact_node:
        proofs.append({"ok": True, "text": f"Lineage: {len(lineage['upstream'])} upstream and {lineage['downstream_count']} downstream "
                                           f"dependencies for {impact_node} (RULE-004)."})

    return {
        "semantic_model": {k: model[k] for k in ("id", "name", "workspace", "platform", "endorsement", "refresh_status",
                                                 "ai_readiness", "owner", "measures")} if model else None,
        "datasets": [model_id] if model_id else [],
        "columns": {}, "relationships": [],
        "base_asset": base, "measures": req, "dimensions": intent.get("dimensions", []),
        "proofs": proofs, "verification": verification, "lineage": lineage,
        "replaces": decision.get("replaces", []), "rules_applied": decision.get("rules_applied", []),
        "notes": [str(n) for n in proposal.get("notes", [])][:6], "summary": str(proposal.get("summary") or ""),
    }


class EvidenceAgent(Agent):
    name = "evidence"
    title = "Evidence agent (/explore)"
    role = "reasoning"

    async def run_llm(self, ctx: dict[str, Any], steps: list[Step]) -> dict[str, Any]:
        intent, decision, availability = ctx["intent"], ctx["decision"], ctx["availability"]
        cand = decision.get("candidate") or {}
        user = json.dumps({
            "intent": {k: v for k, v in intent.items() if not k.startswith("_")},
            "decision": decision["decision"], "reason": decision["reason"], "report_id": cand.get("asset_id"),
            "suggested_model": decision.get("target_model_id") or (availability.get("best_model") or {}).get("id"),
        }, ensure_ascii=False)
        proposal = await self.llm.tool_loop(self.role, SYSTEM, user, CATALOG_TOOLS, self.tool_recorder(steps))
        steps.append(Step("model", "Proposed model and findings", str(proposal.get("semantic_model"))))
        return finalize(intent, decision, availability, proposal, steps)

    async def run_rules(self, ctx: dict[str, Any], steps: list[Step]) -> dict[str, Any]:
        intent, decision, availability = ctx["intent"], ctx["decision"], ctx["availability"]
        record = self.tool_recorder(steps)
        cand = decision.get("candidate") or {}
        base = cat.asset_by_id(cand.get("asset_id")) if decision["decision"] in ("repair", "consolidate", "migrate") else None
        if base:
            record("get_report", {"report_id": base["id"]}, get_report(base["id"]))
        for m in intent.get("measures", []):
            record("get_kpi", {"measure_id": m}, get_kpi(m))
        model_id = _pick_model(decision, availability, base)
        if model_id:
            record("get_model", {"model_id": model_id}, get_model(model_id))
        node = (base or {}).get("id") or model_id
        if node:
            record("get_lineage", {"node_id": node}, get_lineage(node))
        model = cat.model_by_id(model_id)
        summary = (f"The request can be served from the shared model '{model['name']}' using approved KPIs only. "
                   f"Local and conflicting variants are excluded." if model else "No shared model serves this request yet.")
        return finalize(intent, decision, availability, {"semantic_model": model_id, "summary": summary}, steps)
