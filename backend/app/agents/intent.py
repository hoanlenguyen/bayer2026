"""Intent agent (/grill-me): turns a business request into a structured intent.

Asks material plain-language questions about the dashboard request and
specifications. Output: {"status": "ask"|"clear", "question", "suggestions", "intent"}.

Intent fields: decision, measures (canonical KPI ids), dimensions (breakdowns),
grain (month), filters {product, market, region, therapeutic_area} as lists,
scope_global, migration {"from": "Tableau"} or null, unmatched_terms.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .. import catalog as cat
from ..datapack import REGION_ALIASES
from .base import Agent, Step
from .tools import catalog_brief

OUT_OF_SCOPE = ["patient", "prescriber", "hcp", "physician", "adherence", "adverse event", "pharmacovigilance", "treatment"]

SYSTEM = """You turn a Bayer Pharmaceuticals employee dashboard request into a precise intent.
Users are not technical. Ask about the decision they need to make, never about specifications.
Ask at most one short question per turn, with 2-3 short answer suggestions.
Use ONLY ids from the catalog below. Put requested numbers that are not in the catalog, or that need patient or
prescriber-level data (out of scope), in unmatched_terms. Filters use product names, market ids, region names and
therapeutic areas. Set migration to {"from": "Tableau"} when the user wants to replace a Tableau workbook.
Respond with JSON only:
{"status": "ask" | "clear", "question": string|null, "suggestions": [string],
 "intent": {"decision": string, "audience": string, "source_asset_id": string|null, "measures": [id], "dimensions": [id], "grain": "month",
            "filters": {"product": [name], "market": [id], "region": [name], "therapeutic_area": [name]},
            "scope_global": boolean, "migration": object|null, "unmatched_terms": [string]}}
Return "clear" only when material requirements are known. Never erase an unresolved requirement because a question count was reached.

CATALOG
{catalog}"""


def _norm(text: str) -> str:
    return " " + re.sub(r"\s+", " ", text.lower()) + " "


def match_measures(text: str) -> list[str]:
    t = _norm(text)
    return [mid for mid, m in cat.CATALOG["measures"].items() if any(k in t for k in m["keywords"])]


def match_dimensions(text: str) -> list[str]:
    t = _norm(text)
    return [did for did, d in cat.CATALOG["dimensions"].items() if any(k in t for k in d["keywords"])]


def match_filters(text: str) -> dict[str, list[str]]:
    t = _norm(text)
    C = cat.CATALOG
    f: dict[str, list[str]] = {}
    products = [p["name"] for p in C["products"].values() if re.search(rf"\b{re.escape(p['name'].lower())}\b", t)]
    markets = [k for k, m in C["markets"].items() if re.search(rf"\b{re.escape(m['name'].lower())}\b", t)]
    regions = list(dict.fromkeys(v for k, v in REGION_ALIASES.items() if re.search(rf"\b{re.escape(k)}\b", t)))
    tas = list(dict.fromkeys(p["therapeutic_area"] for p in C["products"].values()
                             if re.search(rf"\b{re.escape(p['therapeutic_area'].lower())}\b", t)))
    for key, vals in (("product", products), ("market", markets), ("region", regions), ("therapeutic_area", tas)):
        if vals:
            f[key] = vals
    return f


def sanitize_intent(intent: dict[str, Any]) -> dict[str, Any]:
    """Keep only catalog IDs and known filter values. The model cannot invent KPIs or markets."""
    C = cat.CATALOG
    unknown = [str(m) for m in intent.get("measures") or [] if m not in C["measures"]]
    unknown += [str(d) for d in intent.get("dimensions") or [] if d not in C["dimensions"]]
    intent["measures"] = [m for m in dict.fromkeys(intent.get("measures") or []) if m in C["measures"]]
    intent["dimensions"] = [d for d in dict.fromkeys(intent.get("dimensions") or []) if d in C["dimensions"]]
    if intent.get("grain") not in (None, "month"):
        unknown.append("Unsupported grain: " + str(intent["grain"]))
    intent["grain"] = "month"
    aid = intent.get("source_asset_id")
    if aid and not cat.asset_by_id(aid):
        unknown.append("Unknown source asset: " + str(aid))
    raw = intent.get("filters") or {}
    names = {p["name"] for p in C["products"].values()}
    tas = {p["therapeutic_area"] for p in C["products"].values()}
    regions = set(REGION_ALIASES.values())
    clean = {
        "product": [p for p in raw.get("product") or [] if p in names],
        "market": [m for m in raw.get("market") or [] if m in C["markets"]],
        "region": [r for r in raw.get("region") or [] if r in regions],
        "therapeutic_area": [t for t in raw.get("therapeutic_area") or [] if t in tas],
        "month": [m for m in raw.get("month") or [] if m in {r["month"] for r in cat.SHEETS.get("product_market_monthly", [])}],
    }
    unknown += [f"{key}: {value}" for key, values in raw.items() for value in values if value not in clean.get(key, [])]
    intent["filters"] = {k: v for k, v in clean.items() if v}
    intent["scope_global"] = bool(intent.get("scope_global"))
    mig = intent.get("migration")
    intent["migration"] = {"from": "Tableau"} if mig else None
    intent["unmatched_terms"] = list(dict.fromkeys([str(t) for t in intent.get("unmatched_terms") or [] if str(t).strip()] + unknown))
    return intent


class IntentAgent(Agent):
    name = "intent"
    title = "Intent agent (/grill-me)"
    role = "fast"

    async def run_llm(self, ctx: dict[str, Any], steps: list[Step]) -> dict[str, Any]:
        intent, asked = ctx["intent"], ctx["asked"]
        system = SYSTEM.replace("{catalog}", catalog_brief())
        user = json.dumps({"conversation": ctx["transcript"], "questions_already_asked": asked, "preset": ctx.get("preset"),
                           "current_intent": {k: v for k, v in intent.items() if not k.startswith("_")}}, ensure_ascii=False)
        out = await self.llm.json(self.role, system, user)
        steps.append(Step("model", "Extract intent from the conversation", f"status={out.get('status')}"))
        proposed = out.get("intent") or {}
        merged = sanitize_intent({**intent, **proposed})
        dropped = set(proposed.get("measures") or []) - set(merged["measures"])
        if dropped:
            steps.append(Step("check", "Removed KPI ids not in the catalog", ", ".join(sorted(dropped)), ok=False))
        status = out.get("status") if out.get("question") else "clear"
        return {"status": status, "question": out.get("question"), "suggestions": out.get("suggestions") or [], "intent": merged}

    async def run_rules(self, ctx: dict[str, Any], steps: list[Step]) -> dict[str, Any]:
        transcript, intent, asked, preset = ctx["transcript"], ctx["intent"], ctx["asked"], ctx.get("preset")
        last = transcript[-1]["content"] if transcript else ""
        low = last.lower()
        pending = intent.pop("_pending", None)

        if pending == "decision":
            intent["decision"] = last
            intent["audience"] = last
        elif pending == "measures" and not match_measures(last):
            intent.setdefault("unmatched_terms", []).append(last)
        elif pending == "scope":
            if "global" in low or "all" in low or "every" in low:
                intent["scope_global"] = True

        # A preset already carries an exact intent; do not re-parse its own prompt text.
        if preset and len(transcript) == 1 and not pending:
            steps.append(Step("rule", "Use the preset's governed intent", preset["id"]))
            return {"status": "clear", "question": None, "suggestions": [], "intent": sanitize_intent(intent)}

        found_m, found_d, found_f = match_measures(last), match_dimensions(last), match_filters(last)
        intent["measures"] = list(dict.fromkeys(intent.get("measures", []) + found_m))
        intent["dimensions"] = list(dict.fromkeys(intent.get("dimensions", []) + found_d))
        filters = intent.setdefault("filters", {})
        for k, v in found_f.items():
            filters[k] = list(dict.fromkeys(filters.get(k, []) + v))
        if "global" in low or "all markets" in low or "every market" in low:
            intent["scope_global"] = True
        if "tableau" in low and any(w in low for w in ("replace", "replacement", "migrat")):
            intent["migration"] = {"from": "Tableau"}
        asset_ids = re.findall(r"AST-\d{4}", last.upper())
        if asset_ids:
            intent["source_asset_id"] = asset_ids[0]
            if len(set(asset_ids)) > 1:
                intent.setdefault("unmatched_terms", []).append("Multiple source assets: choose one to change")
        unsupported = re.findall(r"\b(?:daily|weekly|quarterly|hourly|yoy|year.over.year|ytd|q[1-4]|20(?:[01][0-9]|2[0-5789]|[3-9][0-9]))\b", low)
        # "May I build ..." is a request, not a reporting-period filter.
        period_text = re.sub(r"\bmay\s+(?:i|we|you)\b", "", low)
        named_period = re.search(r"\b(january|february|march|april|may|june|july|august|september|october|november|december|last month|this month|last year|this year|20[0-9]{2}-[0-9]{2})\b", period_text)
        if named_period:
            unsupported.append("specific reporting period: " + named_period.group(0))
        if unsupported:
            intent.setdefault("unmatched_terms", []).append("Unsupported period or comparison: " + ", ".join(unsupported))
        blocked = [w for w in OUT_OF_SCOPE if w in low]
        if blocked:
            intent.setdefault("unmatched_terms", []).append(f"patient or prescriber-level data ({', '.join(blocked)})")
        steps.append(Step("rule", "Match catalog keywords",
                          f"KPIs={found_m or '-'}, breakdowns={found_d or '-'}, filters={found_f or '-'}"))

        def ask(field: str, question: str, suggestions: list[str]) -> dict[str, Any]:
            intent["_pending"] = field
            steps.append(Step("rule", f"Missing: {field}", "Ask a clarifying question"))
            return {"status": "ask", "question": question, "suggestions": suggestions, "intent": intent}

        if not preset and not blocked and not intent.get("unmatched_terms"):
            if not intent["measures"] and not intent.get("migration"):
                return ask("measures", "Which numbers do you need? For example net sales, market access coverage, OTIF or forecast accuracy.",
                           ["Net sales and growth", "Market access coverage", "OTIF and inventory coverage"])
            if not any(intent.get("filters", {}).get(k) for k in ("market", "region")) and not intent.get("scope_global"):
                return ask("scope", "Which products and markets should it cover?",
                           ["All products, all markets", "One product, global", "One market only"])
            if not intent.get("decision"):
                return ask("decision", "Who will use this dashboard, and what review or decision should it support?",
                           ["Monthly performance review", "Decide where to act this month", "Prepare a leadership update"])

        if not intent["measures"] and not intent.get("unmatched_terms") and not intent.get("migration"):
            intent["unmatched_terms"] = [transcript[0]["content"]] if transcript else []
        if intent.get("migration") and not intent["measures"]:
            intent["measures"] = ["net_sales", "net_sales_growth"]
        return {"status": "clear", "question": None, "suggestions": [], "intent": sanitize_intent(intent)}
