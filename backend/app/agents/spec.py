"""Spec agent (/to-spec): turns intent and evidence into a validated DashboardSpec.

The model only designs the page (which visuals, titles, rationale). Python
assembles everything else from the verified evidence and validates the result.
If validation fails, the errors go back to the model for a revision.
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

SYSTEM = """You design a minimal Power BI report page for one decision at a pharma plant. Fewer visuals is better (max 6).
Headline numbers first, then the breakdown that shows where to act, then a trend if useful.
Use only the measure ids and dimension ids given ("date" is allowed for trends). Visual types: card, bar, line, table.
Respond with JSON only:
{"name": string (short report name), "pages": [{"name": string, "visuals": [{"type": string, "title": string, "measure": id, "by": id|null}]}],
 "rationale": string (one or two sentences on why this layout supports the decision)}
If validation errors are given, fix exactly those problems."""


def rule_layout(draft: dict[str, Any]) -> dict[str, Any]:
    C = cat.CATALOG
    measures = draft["measures"]
    dims = [d for d in draft["dimensions"] if d != "date"]
    visuals = [{"type": "card", "title": m["name"], "measure": m["id"], "by": None} for m in measures[:4]]
    if dims:
        visuals.append({"type": "table", "title": f"{measures[0]['name']} by {C['dimensions'][dims[0]]['name'].lower()}",
                        "measure": measures[0]["id"], "by": dims[0]})
    visuals.append({"type": "line", "title": f"{measures[0]['name']} trend", "measure": measures[0]["id"], "by": "date"})
    return {"pages": [{"name": "Today" if draft["grain"] in ("hour", "day") else "Overview", "visuals": visuals[:MAX_VISUALS]}],
            "rationale": f"One page for the decision \"{draft['decision']}\": headline numbers first, then the breakdown that shows "
                         "where to act, then the trend."}


def default_name(intent: dict[str, Any], preset: dict[str, Any] | None, base: dict[str, Any] | None) -> str:
    if base:
        return base["name"]
    if preset:
        return f"{preset['department']} · {preset['title']}"
    C = cat.CATALOG
    name = " and ".join(C["measures"][m]["name"] for m in intent["measures"][:2])
    if intent["dimensions"]:
        name += f" by {C['dimensions'][intent['dimensions'][0]]['name'].lower()}"
    return name


def assemble(layout: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Build the full spec. Everything except the page design comes from verified evidence."""
    C = cat.CATALOG
    intent, decision, evidence = ctx["intent"], ctx["decision"], ctx["evidence"]
    base = evidence["base_asset"]
    measures = [{"id": m, **{k: C["measures"][m][k] for k in ("name", "expression", "definition", "dataset", "unit")},
                 "certified": C["measures"][m]["certified"]} for m in intent["measures"]]
    change: dict[str, Any] = {}
    if decision.get("change_type") == "maintenance":
        change = {"refresh_schedule": "every 4 hours", "note": "Maintenance change: no new visuals."}
    elif base:
        cand = decision["candidate"]
        change = {"add_measures": cand["measures_missing"], "add_dimensions": cand["dimensions_missing"],
                  "grain": intent["grain"] if not cand["grain_supported"] else base["grain"]}
    return {
        "name": base["name"] if base else (str(layout.get("name") or "").strip() or default_name(intent, ctx.get("preset"), None)),
        "decision": intent["decision"],
        "decision_type": decision["decision"],
        "change_type": decision.get("change_type"),
        "base_asset_id": base["id"] if base else None,
        "change": change,
        "entities": evidence["datasets"],
        "columns": evidence["columns"],
        "grain": {ds: intent["grain"] for ds in evidence["datasets"]},
        "relationships": evidence["relationships"],
        "measures": measures,
        "dimensions": intent["dimensions"],
        "filters": intent.get("filters", {}),
        "pages": layout.get("pages") or [],
        "rationale": str(layout.get("rationale") or ""),
        "owner": base["owner"] if base else "You (requester)",
        "approver": base["owner"] if base else "Data steward",
        "review_date": (date.today() + timedelta(days=180)).isoformat(),
    }


def validate(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Deterministic checks. Every failed check blocks approval until fixed."""
    C = cat.CATALOG
    checks: list[dict[str, Any]] = []

    def check(ok: bool, text: str) -> None:
        checks.append({"ok": bool(ok), "text": text})

    measure_ids = {m["id"] for m in spec["measures"]}
    allowed_by = set(spec["dimensions"]) | {"date", None}
    entity_dims = {d for ds in spec["entities"] for d in C["datasets"].get(ds, {}).get("dimensions", [])}
    visuals = [v for p in spec["pages"] for v in p.get("visuals", [])]

    check(bool(spec["name"]), "Report has a name")
    check(len(spec["pages"]) >= 1, "Report has at least one page")
    check(1 <= len(visuals) <= MAX_VISUALS, f"Between 1 and {MAX_VISUALS} visuals ({len(visuals)})")
    bad_type = [v.get("type") for v in visuals if v.get("type") not in VISUAL_TYPES]
    check(not bad_type, "Visual types are supported" + (f" (unsupported: {', '.join(map(str, bad_type))})" if bad_type else ""))
    bad_m = [v.get("measure") for v in visuals if v.get("measure") not in measure_ids]
    check(not bad_m, "Every visual uses a measure from the spec" + (f" (unknown: {', '.join(map(str, bad_m))})" if bad_m else ""))
    bad_by = [v.get("by") for v in visuals if v.get("by") not in allowed_by]
    check(not bad_by, "Every breakdown is a requested dimension or date" + (f" (unknown: {', '.join(map(str, bad_by))})" if bad_by else ""))
    used_m = {v.get("measure") for v in visuals}
    check(measure_ids <= used_m, "Every requested measure appears on the page")
    uncert = [m["name"] for m in spec["measures"] if not m["certified"]]
    check(not uncert, "All measures use certified definitions" + (f" (not certified: {', '.join(uncert)})" if uncert else ""))
    unknown_ds = [d for d in spec["entities"] if d not in C["datasets"]]
    check(not unknown_ds and bool(spec["entities"]), "All source tables exist in the catalog")
    missing_dims = [d for d in spec["dimensions"] if d not in entity_dims]
    check(not missing_dims, "Every breakdown is available in the source tables" + (f" (missing: {', '.join(missing_dims)})" if missing_dims else ""))
    check(bool(spec["owner"]) and bool(spec["review_date"]), "Owner and review date are set")
    return checks


class SpecAgent(Agent):
    name = "spec"
    title = "Spec agent (/to-spec)"
    role = "reasoning"

    def _payload(self, ctx: dict[str, Any], errors: list[str], previous: dict[str, Any] | None) -> str:
        C = cat.CATALOG
        intent = ctx["intent"]
        return json.dumps({
            "decision_to_support": intent["decision"],
            "grain": intent["grain"],
            "measures": [{"id": m, "name": C["measures"][m]["name"], "unit": C["measures"][m]["unit"]} for m in intent["measures"]],
            "dimensions": [{"id": d, "name": C["dimensions"][d]["name"]} for d in intent["dimensions"]],
            "suggested_name": default_name(intent, ctx.get("preset"), ctx["evidence"]["base_asset"]),
            "previous_attempt": previous,
            "validation_errors": errors,
        }, ensure_ascii=False)

    async def run_llm(self, ctx: dict[str, Any], steps: list[Step]) -> dict[str, Any]:
        errors: list[str] = []
        previous = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            layout = await self.llm.json(self.role, SYSTEM, self._payload(ctx, errors, previous))
            n = sum(len(p.get("visuals", [])) for p in layout.get("pages", []))
            steps.append(Step("model", "Draft page layout" if attempt == 1 else f"Revise layout (attempt {attempt})", f"{n} visuals"))
            spec = assemble(layout, ctx)
            checks = validate(spec)
            errors = [c["text"] for c in checks if not c["ok"]]
            steps.append(Step("check", "Validate spec", "all checks pass" if not errors else "; ".join(errors), ok=not errors))
            if not errors:
                spec["validation"] = {"passed": True, "checks": checks, "attempts": attempt}
                return spec
            previous = {"pages": layout.get("pages"), "name": layout.get("name")}
        raise ValueError(f"spec still invalid after {MAX_ATTEMPTS} attempts: {'; '.join(errors)}")

    async def run_rules(self, ctx: dict[str, Any], steps: list[Step]) -> dict[str, Any]:
        intent = ctx["intent"]
        draft = {"decision": intent["decision"], "grain": intent["grain"], "dimensions": intent["dimensions"],
                 "measures": [{"id": m, "name": cat.CATALOG["measures"][m]["name"]} for m in intent["measures"]]}
        layout = rule_layout(draft)
        layout["name"] = default_name(intent, ctx.get("preset"), ctx["evidence"]["base_asset"])
        steps.append(Step("rule", "Standard layout", "cards, breakdown table, trend"))
        spec = assemble(layout, ctx)
        checks = validate(spec)
        errors = [c["text"] for c in checks if not c["ok"]]
        steps.append(Step("check", "Validate spec", "all checks pass" if not errors else "; ".join(errors), ok=not errors))
        spec["validation"] = {"passed": not errors, "checks": checks, "attempts": 1}
        return spec
