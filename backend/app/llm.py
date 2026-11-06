"""Model access for the agent steps.

Two providers share one interface:
- ``OpenAIProvider`` calls the OpenAI API (GPT-6 family by default).
- ``MockProvider`` is rule-based and runs offline. It is the default when no
  OPENAI_API_KEY is set, and the fallback if an API call fails.

The model only ever receives the user's words and catalog metadata
(measure and dimension names and definitions), never raw production data.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from .catalog import CATALOG
from .settings import settings

log = logging.getLogger(__name__)

MAX_QUESTIONS = 2
GRAINS = ("hour", "day", "week", "month")

GRAIN_WORDS = [
    (r"\b(hourly|per hour|every hour|real[- ]time)\b", "hour"),
    (r"\b(today|daily|shift|this morning|each day|every day|right now)\b", "day"),
    (r"\b(weekly|this week|per week|each week)\b", "week"),
    (r"\b(monthly|this month|month-end|month end|per month)\b", "month"),
]


# ---------------------------------------------------------------- helpers
def _norm(text: str) -> str:
    return " " + re.sub(r"\s+", " ", text.lower()) + " "


def match_measures(text: str) -> list[str]:
    t = _norm(text)
    return [mid for mid, m in CATALOG["measures"].items() if any(k in t for k in m["keywords"])]


def match_dimensions(text: str) -> list[str]:
    t = _norm(text)
    return [did for did, d in CATALOG["dimensions"].items()
            if did != "date" and any(re.search(r"\b" + re.escape(k) + r"\b", t) for k in d["keywords"])]


def match_grain(text: str) -> str | None:
    t = text.lower()
    for pattern, grain in GRAIN_WORDS:
        if re.search(pattern, t):
            return grain
    return None


def sanitize_intent(intent: dict[str, Any]) -> dict[str, Any]:
    """Keep only catalog IDs the model is allowed to use."""
    intent["measures"] = [m for m in dict.fromkeys(intent.get("measures", [])) if m in CATALOG["measures"]]
    intent["dimensions"] = [d for d in dict.fromkeys(intent.get("dimensions", [])) if d in CATALOG["dimensions"]]
    if intent.get("grain") not in GRAINS:
        intent["grain"] = None
    intent["filters"] = {k: v for k, v in (intent.get("filters") or {}).items() if k in CATALOG["dimensions"]}
    intent["unmatched_terms"] = [str(t) for t in intent.get("unmatched_terms", []) if str(t).strip()]
    return intent


def catalog_brief() -> str:
    """Metadata sent to the model: IDs, names and definitions only."""
    measures = "\n".join(f"- {mid}: {m['name']} ({m['unit']}). {m['definition']}" for mid, m in CATALOG["measures"].items())
    dims = ", ".join(f"{did} ({d['name']})" for did, d in CATALOG["dimensions"].items())
    return f"MEASURES\n{measures}\n\nDIMENSIONS\n{dims}\n\nGRAINS: hour, day, week, month"


def _dimension_suggestions(intent: dict[str, Any]) -> list[str]:
    datasets = {CATALOG["measures"][m]["dataset"] for m in intent["measures"]}
    dims = [d for ds in datasets for d in CATALOG["datasets"][ds]["dimensions"] if d != "date"]
    return [f"By {CATALOG['dimensions'][d]['name'].lower()}" for d in list(dict.fromkeys(dims))[:3]]


# ---------------------------------------------------------------- mock provider
class MockProvider:
    name = "mock"

    async def grill(self, transcript: list[dict[str, str]], intent: dict[str, Any], asked: int,
                    preset: dict[str, Any] | None) -> dict[str, Any]:
        last = transcript[-1]["content"] if transcript else ""
        pending = intent.pop("_pending", None)

        # Apply the answer to the pending question.
        if pending == "preset_filter" and preset and preset.get("ask"):
            if not last.lower().startswith("all"):
                intent.setdefault("filters", {})[preset["ask"]["field"]] = last
        elif pending == "decision":
            intent["decision"] = last
        elif pending == "measures" and not match_measures(last):
            intent.setdefault("unmatched_terms", []).append(last)

        # Pull any facts out of the latest message.
        intent["measures"] = list(dict.fromkeys(intent.get("measures", []) + match_measures(last)))
        intent["dimensions"] = list(dict.fromkeys(intent.get("dimensions", []) + match_dimensions(last)))
        intent["grain"] = intent.get("grain") or match_grain(last)

        def ask(field: str, question: str, suggestions: list[str]) -> dict[str, Any]:
            intent["_pending"] = field
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
        return {"status": "clear", "question": None, "suggestions": [], "intent": intent}

    async def explain(self, kind: str, payload: dict[str, Any]) -> str:
        return template_explanation(kind, payload)

    async def spec_layout(self, draft: dict[str, Any]) -> dict[str, Any]:
        return rule_based_layout(draft)


def template_explanation(kind: str, p: dict[str, Any]) -> str:
    d = p.get("decision", {})
    cand = d.get("candidate") or {}
    if kind == "decision":
        dec = d.get("decision")
        if dec == "reuse":
            return f"Good news: **{cand.get('name')}** already answers this with certified data, so nothing new needs to be built. {d.get('reason', '')}"
        if dec == "extend":
            if d.get("change_type") == "maintenance":
                return f"**{cand.get('name')}** covers everything you asked for, but its data is too old for a daily decision. I propose a maintenance change to its refresh schedule instead of a new report."
            missing = [CATALOG["measures"][m]["name"].lower() for m in cand.get("measures_missing", [])] + \
                      [CATALOG["dimensions"][d]["name"].lower() for d in cand.get("dimensions_missing", [])]
            extra = " and a finer time grain" if not cand.get("grain_supported", True) else ""
            return f"**{cand.get('name')}** covers most of this. I propose adding {' and '.join(missing) or 'the missing parts'}{extra} to it instead of building a new report."
        if dec == "create":
            return "Nothing governed in the catalog answers this yet, but the data exists. I drafted a new report built only from certified definitions."
        return "I couldn't find the data for this in the catalog. " + p.get("missing_text", "")
    return ""


def rule_based_layout(draft: dict[str, Any]) -> dict[str, Any]:
    measures = draft["measures"]
    dims = [d for d in draft["dimensions"] if d != "date"]
    visuals = [{"type": "card", "title": m["name"], "measure": m["id"], "by": None} for m in measures[:3]]
    if dims:
        visuals.append({"type": "table", "title": f"{measures[0]['name']} by {CATALOG['dimensions'][dims[0]]['name'].lower()}",
                        "measure": measures[0]["id"], "by": dims[0]})
    visuals.append({"type": "line", "title": f"{measures[0]['name']} trend", "measure": measures[0]["id"], "by": "date"})
    return {
        "pages": [{"name": "Today" if draft["grain"] in ("hour", "day") else "Overview", "visuals": visuals[:6]}],
        "rationale": f"One page to support the decision: \"{draft['decision']}\". Headline numbers first, then the breakdown that tells you where to act, then the trend.",
    }


# ---------------------------------------------------------------- OpenAI provider
GRILL_SYSTEM = """You turn a plant employee's request into a precise analytics intent.
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

EXPLAIN_SYSTEM = """You explain an analytics decision to a non-technical plant employee in 2-3 short sentences.
Name the report in **bold**. Say what will happen next. Plain language, no jargon, no dashes as punctuation."""

LAYOUT_SYSTEM = """You design a minimal Power BI report page for one decision. Fewer visuals is better (max 6).
Use only the measure ids and dimension ids given. Visual types: card, bar, line, table.
Respond with JSON only: {"pages": [{"name": string, "visuals": [{"type": string, "title": string, "measure": id, "by": id|null}]}],
"rationale": string (one or two sentences on why this layout supports the decision)}"""


class OpenAIProvider:
    name = "openai"

    def __init__(self) -> None:
        from openai import AsyncOpenAI

        self.client = AsyncOpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)
        self.mock = MockProvider()

    async def _json(self, model: str, system: str, user: str) -> dict[str, Any]:
        resp = await self.client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={"type": "json_object"},
        )
        return json.loads(resp.choices[0].message.content or "{}")

    async def grill(self, transcript, intent, asked, preset):
        try:
            system = GRILL_SYSTEM.replace("{max_q}", str(MAX_QUESTIONS)).replace("{catalog}", catalog_brief())
            user = json.dumps({"conversation": transcript, "current_intent": {k: v for k, v in intent.items() if not k.startswith("_")},
                               "questions_already_asked": asked, "preset": preset}, ensure_ascii=False)
            out = await self._json(settings.model_fast, system, user)
            merged = {**intent, **(out.get("intent") or {})}
            status = out.get("status") if asked < MAX_QUESTIONS else "clear"
            return {"status": status, "question": out.get("question"), "suggestions": out.get("suggestions") or [],
                    "intent": merged}
        except Exception as exc:  # fall back so the demo never stalls
            log.warning("OpenAI grill failed, using mock: %s", exc)
            return await self.mock.grill(transcript, intent, asked, preset)

    async def explain(self, kind, payload):
        try:
            resp = await self.client.chat.completions.create(
                model=settings.model_fast,
                messages=[{"role": "system", "content": EXPLAIN_SYSTEM},
                          {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)}],
            )
            return resp.choices[0].message.content or template_explanation(kind, payload)
        except Exception as exc:
            log.warning("OpenAI explain failed, using template: %s", exc)
            return template_explanation(kind, payload)

    async def spec_layout(self, draft):
        try:
            out = await self._json(settings.model_reasoning, LAYOUT_SYSTEM, json.dumps(draft, ensure_ascii=False))
            allowed_m = {m["id"] for m in draft["measures"]}
            allowed_d = set(draft["dimensions"]) | {"date", None}
            for page in out.get("pages", []):
                page["visuals"] = [v for v in page.get("visuals", []) if v.get("measure") in allowed_m and v.get("by") in allowed_d][:6]
            if not any(p.get("visuals") for p in out.get("pages", [])):
                raise ValueError("model returned no valid visuals")
            return out
        except Exception as exc:
            log.warning("OpenAI layout failed, using rules: %s", exc)
            return rule_based_layout(draft)


def get_provider() -> MockProvider | OpenAIProvider:
    return OpenAIProvider() if settings.llm_provider == "openai" else MockProvider()
