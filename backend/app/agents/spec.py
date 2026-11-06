"""Spec agent (/to-spec): turns intent and evidence into a validated DashboardSpec.

The model only designs the page (visuals, name, rationale). Python assembles
everything else from the verified evidence (shared semantic model, approved
KPIs, scope, owner, what it replaces) and validates the result. Validation
errors go back to the model for a revision.

A repair is a maintenance change: the spec lists the repairs and has no pages.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from .. import catalog as cat
from .base import Agent, Step

MAX_ATTEMPTS = 3
MAX_VISUALS = 6
VISUAL_TYPES = {"card", "bar", "line", "table"}

SYSTEM = """You design a minimal Power BI report page for one business decision at Bayer Pharmaceuticals.
Fewer visuals is better (max 6): headline KPI cards first, then the breakdown that shows where to act, then a monthly
trend if useful. Use only the measure ids and breakdown ids given ("month" is allowed for trends).
Visual types: card, bar, line, table.
Respond with JSON only:
{"name": string (short report name), "pages": [{"name": string, "visuals": [{"type": string, "title": string, "measure": id, "by": id|null}]}],
 "rationale": string (one or two sentences on why this layout supports the decision)}
If validation errors are given, fix exactly those problems."""


def rule_layout(draft: dict[str, Any]) -> dict[str, Any]:
    C = cat.CATALOG
    measures = draft["measures"]
    dims = [d for d in draft["dimensions"] if d != "month"]
    visuals = [{"type": "card", "title": m["name"], "measure": m["id"], "by": None} for m in measures[:4]]
    if dims:
        visuals.append({"type": "bar" if dims[0] in ("product", "region", "therapeutic_area") else "table",
                        "title": f"{measures[0]['name']} by {C['dimensions'][dims[0]]['name'].lower()}",
                        "measure": measures[0]["id"], "by": dims[0]})
    visuals.append({"type": "line", "title": f"{measures[0]['name']} by month", "measure": measures[0]["id"], "by": "month"})
    return {"pages": [{"name": "Overview", "visuals": visuals[:MAX_VISUALS]}],
            "rationale": f"One page for the decision \"{draft['decision']}\": headline KPIs first, then where to act, then the monthly trend."}


def scope_label(intent: dict[str, Any]) -> tuple[str, str]:
    from ..decision import intent_products

    products = intent_products(intent, cat.CATALOG)
    f = intent.get("filters") or {}
    markets = f.get("market") or []
    product_scope = products[0] if len(products) == 1 and "product" not in intent.get("dimensions", []) else "All Pharma"
    market_scope = markets[0] if len(markets) == 1 and not intent.get("scope_global") else "Global"
    return product_scope, market_scope


def default_name(intent: dict[str, Any], preset: dict[str, Any] | None, base: dict[str, Any] | None) -> str:
    if base and intent.get("_decision") in ("repair", "consolidate"):
        return base["name"]
    if preset:
        return preset["title"]
    C = cat.CATALOG
    product_scope, market_scope = scope_label(intent)
    kpis = " and ".join(C["measures"][m]["name"] for m in intent["measures"][:2])
    return f"{'' if product_scope == 'All Pharma' else product_scope + ' '}{kpis}{'' if market_scope == 'Global' else ' ' + market_scope}".strip()


def assemble(layout: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Build the full spec. Everything except the page design comes from verified evidence."""
    C = cat.CATALOG
    intent, decision, evidence = ctx["intent"], ctx["decision"], ctx["evidence"]
    dec = decision["decision"]
    base = evidence.get("base_asset")
    keep_base = dec in ("repair", "consolidate")
    measures = [{"id": m, "kpi_id": C["measures"][m]["kpi_id"], "name": C["measures"][m]["name"], "unit": C["measures"][m]["unit"],
                 "definition": C["measures"][m]["definition"], "certified": C["measures"][m]["certified"]} for m in intent["measures"]]
    product_scope, market_scope = scope_label(intent)
    change: dict[str, Any] = {}
    if dec == "repair":
        change = {"repairs": decision["reason"], "asset_id": base["id"] if base else None}
    elif dec == "consolidate" and base:
        change = {"add_measures": (decision.get("candidate") or {}).get("measures_missing", []),
                  "fold_in": decision.get("replaces", [])}
    elif dec == "migrate":
        change = {"migrate_from": base["id"] if base else None, "retire_after_cutover": decision.get("replaces", [])}
    owner = base["owner"] if keep_base and base and base["owner_status"] == "active" else "You (requester)"
    if keep_base and base:
        name = base["name"]
    elif dec == "migrate":
        name = f"{product_scope} Commercial (Power BI)"
    else:
        name = str(layout.get("name") or "").strip() or default_name(intent, ctx.get("preset"), None)
    return {
        "name": name,
        "decision": intent["decision"],
        "decision_type": dec,
        "change_type": decision.get("change_type"),
        "base_asset_id": base["id"] if keep_base and base else None,
        "change": change,
        "semantic_model": evidence.get("semantic_model"),
        "entities": evidence.get("datasets", []),
        "measures": measures,
        "dimensions": intent.get("dimensions", []),
        "filters": intent.get("filters", {}),
        "product_scope": base["product_scope"] if keep_base and base else product_scope,
        "market_scope": base["market_scope"] if keep_base and base else market_scope,
        "pages": [] if dec == "repair" else (layout.get("pages") or []),
        "rationale": str(layout.get("rationale") or ""),
        "replaces": decision.get("replaces", []),
        "rules_applied": decision.get("rules_applied", []),
        "owner": owner,
        "approver": (base["owner"] if base and base["owner_status"] == "active" else "Data steward"),
        "review_date": (date.today() + timedelta(days=180)).isoformat(),
    }


def validate(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Deterministic checks shown to the approver."""
    C = cat.CATALOG
    checks: list[dict[str, Any]] = []

    def check(ok: bool, text: str) -> None:
        checks.append({"ok": bool(ok), "text": text})

    measure_ids = {m["id"] for m in spec["measures"]}
    model = spec.get("semantic_model") or {}
    check(bool(spec["name"]), "Report has a name")
    uncert = [m["name"] for m in spec["measures"] if not m["certified"]]
    check(bool(spec["measures"]) and not uncert, "All KPIs use approved definitions (RULE-002)"
          + (f" (not approved: {', '.join(uncert)})" if uncert else ""))
    check(bool(model) and model.get("id") in C["models"], "Built on a shared semantic model in the catalog (RULE-001)")
    gaps = [m["name"] for m in spec["measures"] if m["id"] not in set(model.get("measures") or [])]
    check(not gaps, "The shared model serves every KPI" + (f" (to add: {', '.join(gaps)})" if gaps else ""))
    check(bool(spec["owner"]) and bool(spec["review_date"]), "Owner and review date are set (RULE-003)")
    if spec["decision_type"] == "repair":
        check(bool(spec["change"].get("repairs")), "Repairs are listed")
        return checks
    visuals = [v for p in spec["pages"] for v in p.get("visuals", [])]
    allowed_by = set(spec["dimensions"]) | {"month", None}
    check(1 <= len(visuals) <= MAX_VISUALS, f"Between 1 and {MAX_VISUALS} visuals ({len(visuals)})")
    bad_type = [str(v.get("type")) for v in visuals if v.get("type") not in VISUAL_TYPES]
    check(not bad_type, "Visual types are supported" + (f" (unsupported: {', '.join(bad_type)})" if bad_type else ""))
    bad_m = [str(v.get("measure")) for v in visuals if v.get("measure") not in measure_ids]
    check(not bad_m, "Every visual uses a KPI from the spec" + (f" (unknown: {', '.join(bad_m)})" if bad_m else ""))
    bad_by = [str(v.get("by")) for v in visuals if v.get("by") not in allowed_by]
    check(not bad_by, "Every breakdown is a requested dimension or month" + (f" (unknown: {', '.join(bad_by)})" if bad_by else ""))
    check(measure_ids <= {v.get("measure") for v in visuals}, "Every requested KPI appears on the page")
    return checks


def _blocking(checks: list[dict[str, Any]]) -> list[str]:
    # A model gap is reported to the approver but is fixed by adding measures to the model, not by the layout.
    return [c["text"] for c in checks if not c["ok"] and not c["text"].startswith("The shared model serves")]


class SpecAgent(Agent):
    name = "spec"
    title = "Spec agent (/to-spec)"
    role = "reasoning"

    def _payload(self, ctx: dict[str, Any], errors: list[str], previous: dict[str, Any] | None) -> str:
        C = cat.CATALOG
        intent = ctx["intent"]
        return json.dumps({
            "decision_to_support": intent["decision"],
            "measures": [{"id": m, "name": C["measures"][m]["name"], "unit": C["measures"][m]["unit"]} for m in intent["measures"]],
            "breakdowns": [{"id": d, "name": C["dimensions"][d]["name"]} for d in intent.get("dimensions", [])],
            "filters": intent.get("filters", {}),
            "suggested_name": default_name(intent, ctx.get("preset"), ctx["evidence"].get("base_asset")),
            "previous_attempt": previous, "validation_errors": errors,
        }, ensure_ascii=False)

    async def run_llm(self, ctx: dict[str, Any], steps: list[Step]) -> dict[str, Any]:
        if ctx["decision"]["decision"] == "repair":
            return await self.run_rules(ctx, steps)
        errors: list[str] = []
        previous = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            layout = await self.llm.json(self.role, SYSTEM, self._payload(ctx, errors, previous))
            n = sum(len(p.get("visuals", [])) for p in layout.get("pages", []))
            steps.append(Step("model", "Draft page layout" if attempt == 1 else f"Revise layout (attempt {attempt})", f"{n} visuals"))
            spec = assemble(layout, ctx)
            checks = validate(spec)
            errors = _blocking(checks)
            steps.append(Step("check", "Validate spec", "all checks pass" if not errors else "; ".join(errors), ok=not errors))
            if not errors:
                spec["validation"] = {"passed": all(c["ok"] for c in checks), "checks": checks, "attempts": attempt}
                return spec
            previous = {"pages": layout.get("pages"), "name": layout.get("name")}
        raise ValueError(f"spec still invalid after {MAX_ATTEMPTS} attempts: {'; '.join(errors)}")

    async def run_rules(self, ctx: dict[str, Any], steps: list[Step]) -> dict[str, Any]:
        intent = ctx["intent"]
        if ctx["decision"]["decision"] == "repair":
            layout: dict[str, Any] = {"pages": [], "rationale": "Maintenance change: repair the existing report instead of building a copy."}
            steps.append(Step("rule", "Repair plan", ctx["decision"]["reason"]))
        else:
            draft = {"decision": intent["decision"], "dimensions": intent.get("dimensions", []),
                     "measures": [{"id": m, "name": cat.CATALOG["measures"][m]["name"]} for m in intent["measures"]]}
            layout = rule_layout(draft)
            layout["name"] = default_name(intent, ctx.get("preset"), ctx["evidence"].get("base_asset"))
            steps.append(Step("rule", "Standard layout", "KPI cards, breakdown, monthly trend"))
        spec = assemble(layout, ctx)
        checks = validate(spec)
        errors = _blocking(checks)
        steps.append(Step("check", "Validate spec", "all checks pass" if not errors else "; ".join(errors), ok=not errors))
        spec["validation"] = {"passed": all(c["ok"] for c in checks), "checks": checks, "attempts": 1}
        return spec
