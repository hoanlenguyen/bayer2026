"""Intent agent (/grill-me): turns a business request into a structured intent.

Asks at most two plain-language questions about the decision, never about
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
from ..triage import URGENCY_CHOICES, infer_urgency, urgency_from_answer, verify_urgency
from .base import Agent, Step
from .tools import catalog_brief

MAX_QUESTIONS = 2
OUT_OF_SCOPE = ["patient", "prescriber", "hcp", "physician", "adherence", "adverse event", "pharmacovigilance", "treatment"]

SYSTEM = """You turn a Bayer Pharmaceuticals business user's analytics request into a precise intent.
Users are not technical. Ask about the decision they need to make, never about specifications.
Ask at most one short question per turn, with 2-3 short answer suggestions.
Use ONLY ids from the catalog below. Put requested numbers that are not in the catalog, or that need patient or
prescriber-level data (out of scope), in unmatched_terms. Filters use product names, market ids, region names and
therapeutic areas. Set migration to {"from": "Tableau"} when the user wants to replace a Tableau workbook.
Respond with JSON only:
{"status": "ask" | "clear", "question": string|null, "suggestions": [string],
 "intent": {"decision": string, "measures": [id], "dimensions": [id], "grain": "month",
            "filters": {"product": [name], "market": [id], "region": [name], "therapeutic_area": [name]},
            "scope_global": boolean, "migration": object|null, "unmatched_terms": [string],
            "urgency": {"value": "normal" | "high" | "urgent", "evidence": "exact words from the request that show the deadline, or null"}}}
Urgency is how soon the user needs it. Only raise it above normal when the user's own words give a deadline or time
pressure, and quote those words as evidence. Never guess urgency from the topic.
Return "clear" when the measures and the decision are known, or when you already asked {max_q} questions.

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
    intent["measures"] = [m for m in dict.fromkeys(intent.get("measures") or []) if m in C["measures"]]
    intent["dimensions"] = [d for d in dict.fromkeys(intent.get("dimensions") or []) if d in C["dimensions"]]
    intent["grain"] = "month"
    raw = intent.get("filters") or {}
    names = {p["name"] for p in C["products"].values()}
    tas = {p["therapeutic_area"] for p in C["products"].values()}
    regions = set(REGION_ALIASES.values())
    clean = {
        "product": [p for p in raw.get("product") or [] if p in names],
        "market": [m for m in raw.get("market") or [] if m in C["markets"]],
        "region": [r for r in raw.get("region") or [] if r in regions],
        "therapeutic_area": [t for t in raw.get("therapeutic_area") or [] if t in tas],
    }
    intent["filters"] = {k: v for k, v in clean.items() if v}
    intent["scope_global"] = bool(intent.get("scope_global"))
    mig = intent.get("migration")
    intent["migration"] = {"from": "Tableau"} if mig else None
    intent["unmatched_terms"] = [str(t) for t in intent.get("unmatched_terms") or [] if str(t).strip()]
    return intent


class IntentAgent(Agent):
    name = "intent"
    title = "Intent agent (/grill-me)"
    role = "fast"

    async def run_llm(self, ctx: dict[str, Any], steps: list[Step]) -> dict[str, Any]:
        intent, asked = ctx["intent"], ctx["asked"]
        system = SYSTEM.replace("{max_q}", str(MAX_QUESTIONS)).replace("{catalog}", catalog_brief())
        user = json.dumps({"conversation": ctx["transcript"], "questions_already_asked": asked, "preset": ctx.get("preset"),
                           "current_intent": {k: v for k, v in intent.items() if not k.startswith("_")}}, ensure_ascii=False)
        out = await self.llm.json(self.role, system, user)
        steps.append(Step("model", "Extract intent from the conversation", f"status={out.get('status')}"))
        proposed = out.get("intent") or {}
        said = " ".join(m["content"] for m in ctx["transcript"] if m["role"] == "user")
        stated = intent.get("urgency") if (intent.get("urgency") or {}).get("source") == "stated" else None
        urgency = stated or verify_urgency(proposed.pop("urgency", None), said)
        if urgency.get("note"):
            steps.append(Step("check", "Urgency not supported by the request", urgency["note"], ok=False))
        merged = sanitize_intent({**intent, **proposed, "urgency": urgency})
        dropped = set(proposed.get("measures") or []) - set(merged["measures"])
        if dropped:
            steps.append(Step("check", "Removed KPI ids not in the catalog", ", ".join(sorted(dropped)), ok=False))
        status = out.get("status") if asked < MAX_QUESTIONS and out.get("question") else "clear"
        return {"status": status, "question": out.get("question"), "suggestions": out.get("suggestions") or [], "intent": merged}

    async def run_rules(self, ctx: dict[str, Any], steps: list[Step]) -> dict[str, Any]:
        transcript, intent, asked, preset = ctx["transcript"], ctx["intent"], ctx["asked"], ctx.get("preset")
        last = transcript[-1]["content"] if transcript else ""
        low = last.lower()
        pending = intent.pop("_pending", None)

        if pending == "decision":
            intent["decision"] = last
        elif pending == "measures" and not match_measures(last):
            intent.setdefault("unmatched_terms", []).append(last)
        elif pending == "scope":
            if "global" in low or "all" in low or "every" in low:
                intent["scope_global"] = True
        elif pending == "urgency":
            value = urgency_from_answer(last)
            if value:
                intent["urgency"] = {"value": value, "source": "stated", "evidence": last}

        said = " ".join(m["content"] for m in transcript if m["role"] == "user")
        if (intent.get("urgency") or {}).get("source") != "stated":
            intent["urgency"] = infer_urgency(said)

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
        if "global" in low or "portfolio" in low or "all products" in low:
            intent["scope_global"] = True
        if "tableau" in low and any(w in low for w in ("replace", "replacement", "migrat")):
            intent["migration"] = {"from": "Tableau"}
        blocked = [w for w in OUT_OF_SCOPE if w in low]
        if blocked:
            intent.setdefault("unmatched_terms", []).append(f"patient or prescriber-level data ({', '.join(blocked)})")
        steps.append(Step("rule", "Match catalog keywords",
                          f"KPIs={found_m or '-'}, breakdowns={found_d or '-'}, filters={found_f or '-'}"))

        def ask(field: str, question: str, suggestions: list[str]) -> dict[str, Any]:
            intent["_pending"] = field
            steps.append(Step("rule", f"Missing: {field}", "Ask a clarifying question"))
            return {"status": "ask", "question": question, "suggestions": suggestions, "intent": intent}

        if asked < MAX_QUESTIONS and not preset and not blocked:
            if not intent["measures"] and not intent.get("migration"):
                semantic = [s["name"] for s in ctx.get("kpi_suggestions") or []]
                if semantic:
                    steps.append(Step("tool", "vector_search(kpis)", ", ".join(semantic)))
                return ask("measures", "Which numbers do you need? For example net sales, market access coverage, OTIF or forecast accuracy.",
                           semantic or ["Net sales and growth", "Market access coverage", "OTIF and inventory coverage"])
            if not intent.get("filters") and not intent.get("scope_global"):
                return ask("scope", "Which products and markets should it cover?",
                           ["All products, all markets", "One product, global", "One market only"])
            if not intent.get("decision"):
                return ask("decision", "What decision will you make with it, and how often?",
                           ["Monthly performance review", "Decide where to act this month", "Prepare a leadership update"])
            if intent["urgency"]["source"] == "default":
                return ask("urgency", "When do you need this?", list(URGENCY_CHOICES))

        if not intent["measures"] and not intent.get("unmatched_terms") and not intent.get("migration"):
            intent["unmatched_terms"] = [transcript[0]["content"]] if transcript else []
        if intent.get("migration") and not intent["measures"]:
            intent["measures"] = ["net_sales", "net_sales_growth"]
        return {"status": "clear", "question": None, "suggestions": [], "intent": sanitize_intent(intent)}
