"""Intent agent (/grill-me): turns a request into a structured intent.

Asks at most two plain-language questions about the decision, never about
specifications. Output: {"status": "ask"|"clear", "question", "suggestions", "intent"}.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .. import catalog as cat
from .base import Agent, Step
from .tools import catalog_brief

MAX_QUESTIONS = 2
GRAINS = ("hour", "day", "week", "month")
GRAIN_WORDS = [
    (r"\b(hourly|per hour|every hour|real[- ]time)\b", "hour"),
    (r"\b(today|daily|shift|this morning|each day|every day|right now)\b", "day"),
    (r"\b(weekly|this week|per week|each week)\b", "week"),
    (r"\b(monthly|this month|month-end|month end|per month)\b", "month"),
]

SYSTEM = """You turn a plant employee's request into a precise analytics intent.
Users are not technical. Ask about the decision they need to make, never about specifications.
Ask at most one short question per turn, with 2-3 short answer suggestions.
Use ONLY ids from the catalog below. Put requested numbers that are not in the catalog in unmatched_terms.
Respond with JSON only:
{"status": "ask" | "clear", "question": string|null, "suggestions": [string],
 "intent": {"decision": string, "measures": [id], "dimensions": [id], "grain": "hour"|"day"|"week"|"month",
            "filters": {dimension_id: value}, "unmatched_terms": [string]}}
Return "clear" when measures, grain and the decision are known, or when you already asked {max_q} questions.

CATALOG
{catalog}"""


def _norm(text: str) -> str:
    return " " + re.sub(r"\s+", " ", text.lower()) + " "


def match_measures(text: str) -> list[str]:
    t = _norm(text)
    return [mid for mid, m in cat.CATALOG["measures"].items() if any(k in t for k in m["keywords"])]


def match_dimensions(text: str) -> list[str]:
    t = _norm(text)
    return [did for did, d in cat.CATALOG["dimensions"].items()
            if did != "date" and any(re.search(r"\b" + re.escape(k) + r"\b", t) for k in d["keywords"])]


def match_grain(text: str) -> str | None:
    for pattern, grain in GRAIN_WORDS:
        if re.search(pattern, text.lower()):
            return grain
    return None


def sanitize_intent(intent: dict[str, Any]) -> dict[str, Any]:
    """Keep only catalog IDs. The model cannot introduce measures that do not exist."""
    C = cat.CATALOG
    intent["measures"] = [m for m in dict.fromkeys(intent.get("measures") or []) if m in C["measures"]]
    intent["dimensions"] = [d for d in dict.fromkeys(intent.get("dimensions") or []) if d in C["dimensions"]]
    if intent.get("grain") not in GRAINS:
        intent["grain"] = None
    intent["filters"] = {k: v for k, v in (intent.get("filters") or {}).items() if k in C["dimensions"]}
    intent["unmatched_terms"] = [str(t) for t in intent.get("unmatched_terms") or [] if str(t).strip()]
    return intent


def _dimension_suggestions(intent: dict[str, Any]) -> list[str]:
    C = cat.CATALOG
    datasets = {C["measures"][m]["dataset"] for m in intent["measures"]}
    dims = [d for ds in datasets for d in C["datasets"][ds]["dimensions"] if d != "date"]
    return [f"By {C['dimensions'][d]['name'].lower()}" for d in list(dict.fromkeys(dims))[:3]]


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
        merged = sanitize_intent({**intent, **(out.get("intent") or {})})
        dropped = set((out.get("intent") or {}).get("measures") or []) - set(merged["measures"])
        if dropped:
            steps.append(Step("check", "Removed IDs not in the catalog", ", ".join(sorted(dropped)), ok=False))
        status = out.get("status") if asked < MAX_QUESTIONS and out.get("question") else "clear"
        return {"status": status, "question": out.get("question"), "suggestions": out.get("suggestions") or [], "intent": merged}

    async def run_rules(self, ctx: dict[str, Any], steps: list[Step]) -> dict[str, Any]:
        transcript, intent, asked, preset = ctx["transcript"], ctx["intent"], ctx["asked"], ctx.get("preset")
        last = transcript[-1]["content"] if transcript else ""
        pending = intent.pop("_pending", None)

        if pending == "preset_filter" and preset and preset.get("ask"):
            if not last.lower().startswith("all"):
                intent.setdefault("filters", {})[preset["ask"]["field"]] = last
        elif pending == "decision":
            intent["decision"] = last
        elif pending == "measures" and not match_measures(last):
            intent.setdefault("unmatched_terms", []).append(last)

        found_m, found_d, found_g = match_measures(last), match_dimensions(last), match_grain(last)
        intent["measures"] = list(dict.fromkeys(intent.get("measures", []) + found_m))
        intent["dimensions"] = list(dict.fromkeys(intent.get("dimensions", []) + found_d))
        intent["grain"] = intent.get("grain") or found_g
        steps.append(Step("rule", "Match catalog keywords",
                          f"measures={found_m or '-'}, dimensions={found_d or '-'}, grain={found_g or '-'}"))

        def ask(field: str, question: str, suggestions: list[str]) -> dict[str, Any]:
            intent["_pending"] = field
            steps.append(Step("rule", f"Missing: {field}", "Ask a clarifying question"))
            return {"status": "ask", "question": question, "suggestions": suggestions, "intent": intent}

        if asked < MAX_QUESTIONS:
            if preset and preset.get("ask") and asked == 0:
                return ask("preset_filter", preset["ask"]["question"], preset["ask"]["suggestions"])
            if not preset:
                if not intent["measures"]:
                    return ask("measures", "Which numbers do you need to see? For example late shipments, OEE, open deviations or budget variance.",
                               ["Late shipments", "OEE and downtime", "Open deviations"])
                if not intent.get("decision") and not intent.get("grain"):
                    return ask("decision", "What decision should this help you make, and how often?",
                               ["Act on today's issues", "Weekly review", "Monthly report"])
                if not intent["dimensions"]:
                    return ask("dimensions", "How should I break it down?", _dimension_suggestions(intent))

        if not intent["measures"] and not intent.get("unmatched_terms"):
            intent["unmatched_terms"] = [transcript[0]["content"]] if transcript else []
        return {"status": "clear", "question": None, "suggestions": [], "intent": sanitize_intent(intent)}
