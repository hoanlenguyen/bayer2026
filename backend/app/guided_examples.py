"""Guided dashboard examples on the Ask start screen: one registry for the backend and the frontend.

Each example fixes the product, two countries, two governed KPIs and a by-country breakdown. The visitor answers two
questions with offered choices only: the decision purpose (which also sets the lead KPI) and the reporting period.
Answers are matched to option IDs, never parsed for KPIs, scope or migration, so a model or classifier cannot change
the brief. Every example is checked against the workbook before it is offered: both periods must be contiguous and
fully covered for both countries and both KPIs, with finite values.
"""
from __future__ import annotations

import math
from functools import lru_cache
from typing import Any

from . import catalog
from .dashboard_intake import workbook_months

PURPOSE_QUESTION = "What decision will you make using this dashboard?"
PERIOD_QUESTION = "Which reporting period should the charts cover?"
PRESENTATION = "market_comparison"

EXAMPLES: list[dict[str, Any]] = [
    {"id": "nubeqa-sales-shipments", "placement": "visible", "product": "P-NUB", "markets": ["FR", "DE"],
     "measures": ["net_sales", "units_shipped"],
     "text": "Build a monthly dashboard comparing Nubeqa net sales and units shipped by market in France and Germany.",
     "purposes": [("a", "Decide where to investigate a shipment swing", "units_shipped"),
                  ("b", "Choose which market to prioritize for a sales review", "net_sales")]},
    {"id": "lynkuet-stock-delivery", "placement": "visible", "product": "P-LYN", "markets": ["FR", "DE"],
     "measures": ["inventory_coverage", "on_time_in_full"],
     "text": "Build a monthly dashboard comparing Lynkuet inventory coverage and OTIF by market in France and Germany.",
     "purposes": [("a", "Decide where to check replenishment", "inventory_coverage"),
                  ("b", "Assess delivery reliability by market", "on_time_in_full")]},
    {"id": "kerendia-access-shipments", "placement": "more", "product": "P-KER", "markets": ["IT", "ES"],
     "measures": ["market_access_coverage", "units_shipped"],
     "text": "Build a monthly dashboard comparing Kerendia market access coverage and units shipped by market in Italy and Spain.",
     "purposes": [("a", "Prioritize markets for a market access review", "market_access_coverage"),
                  ("b", "Identify where to investigate changes in shipment volume", "units_shipped")]},
    {"id": "eylea-sales-delivery", "placement": "more", "product": "P-EYL", "markets": ["CA", "US"],
     "measures": ["net_sales", "on_time_in_full"],
     "text": "Build a monthly dashboard comparing Eylea net sales and OTIF by market in Canada and the United States.",
     "purposes": [("a", "Choose which market to bring to the sales review", "net_sales"),
                  ("b", "Identify where to investigate delivery reliability", "on_time_in_full")]},
    {"id": "xarelto-stock-shipments", "placement": "more", "product": "P-XAR", "markets": ["BR", "MX"],
     "measures": ["inventory_coverage", "units_shipped"],
     "text": "Build a monthly dashboard comparing Xarelto inventory coverage and units shipped by market in Brazil and Mexico.",
     "purposes": [("a", "Decide where to review stock allocation", "inventory_coverage"),
                  ("b", "Identify where to investigate shipment swings", "units_shipped")]},
]
BY_ID = {e["id"]: e for e in EXAMPLES}
SOURCE_SHEET = "product_market_monthly"


def covered_months(example: dict[str, Any]) -> list[str]:
    """Workbook months where both countries have a finite value for both KPIs of this example."""
    C = catalog.CATALOG
    fields = [C["measures"][m]["fact_column"] for m in example["measures"] if m in C["measures"]]
    rows = {(r["product_id"], r["market_id"], r["month"][:7]): r for r in catalog.SHEETS.get(SOURCE_SHEET, [])}
    def complete(month: str) -> bool:
        return all((row := rows.get((example["product"], m, month))) is not None and all(
            type(row.get(f)) in (int, float) and math.isfinite(row[f]) for f in fields) for m in example["markets"])
    return [m for m in workbook_months() if complete(m)]


def periods(example: dict[str, Any]) -> list[dict[str, Any]]:
    """The two period choices for this comparison, from the months it fully covers (independent of today's date).
    Empty when coverage has a gap or is too short for two distinct windows."""
    months = covered_months(example)
    every = workbook_months()
    if len(months) < 7 or months != every[every.index(months[0]):every.index(months[0]) + len(months)]:
        return []
    return [{"id": "all", "label": "All available workbook months", "start": months[0], "end": months[-1], "count": len(months)},
            {"id": "last6", "label": "Last 6 workbook months", "start": months[-6], "end": months[-1], "count": 6}]


def _month_label(m: str) -> str:
    import calendar
    return f"{calendar.month_name[int(m[5:7])]} {m[:4]}"


def period_text(p: dict[str, Any]) -> str:
    return f"{_month_label(p['start'])} to {_month_label(p['end'])}, {p['count']} months"


def verify(example: dict[str, Any]) -> str | None:
    """Why this example cannot be offered, or None. Checks the catalog and every needed workbook row."""
    C = catalog.CATALOG
    if example["product"] not in C["products"] or any(m not in C["markets"] for m in example["markets"]):
        return "product or market missing from the catalog"
    measures = [C["measures"].get(m) for m in example["measures"]]
    if any(not m or not m.get("certified") or not m.get("fact_column") for m in measures):
        return "a KPI is not certified or has no workbook field"
    if {f for _, _, f in example["purposes"]} != set(example["measures"]):
        return "the purpose choices must focus each KPI once"
    if not periods(example):
        return "the workbook does not cover two distinct, gap-free periods for both countries and both KPIs"
    return None


@lru_cache(maxsize=2)
def _checked(snapshot_key: int) -> dict[str, str | None]:
    return {e["id"]: verify(e) for e in EXAMPLES}


def available() -> list[dict[str, Any]]:
    problems = _checked(id(catalog.SHEETS.get(SOURCE_SHEET)))
    return [e for e in EXAMPLES if problems[e["id"]] is None]


def get(example_id: str | None) -> dict[str, Any] | None:
    return next((e for e in available() if e["id"] == example_id), None)


def purpose_options(example: dict[str, Any]) -> list[dict[str, str]]:
    return [{"id": oid, "label": label} for oid, label, _ in example["purposes"]]


def period_options(example: dict[str, Any]) -> list[dict[str, Any]]:
    """The offered period choices with their exact dates. Stored on the run when shown, so the answer uses these dates."""
    return [{"id": p["id"], "label": p["label"], "detail": period_text(p), "start": p["start"], "end": p["end"], "count": p["count"]}
            for p in periods(example)]


def still_covered(example: dict[str, Any], window: dict[str, Any]) -> bool:
    """True if every month of an offered window is still fully covered in the current workbook."""
    months = covered_months(example)
    return window["start"] in months and window["end"] in months and \
        months.index(window["end"]) - months.index(window["start"]) + 1 == window["count"]


def scope_facts(example: dict[str, Any]) -> dict[str, Any]:
    """The verified comparison scope, as the next question shows it."""
    C = catalog.CATALOG
    return {"product": C["products"][example["product"]]["name"], "markets": [C["markets"][m]["name"] for m in example["markets"]],
            "measures": [C["measures"][m]["name"] for m in example["measures"]]}


def choose(options: list[dict[str, str]], choice_id: str | None, text: str) -> dict[str, str] | None:
    """The offered option the reply selects: by stable ID, or by its exact label. Nothing else counts."""
    if choice_id:
        return next((o for o in options if o["id"] == choice_id), None)
    folded = " ".join(text.split()).casefold()
    return next((o for o in options if o["label"].casefold() == folded), None)


def intent_for(example: dict[str, Any], purpose_id: str, window: dict[str, Any]) -> dict[str, Any]:
    """The complete, deterministic intent for an answered example, with the exact dates that were offered."""
    C = catalog.CATALOG
    _, purpose, lead = next(p for p in example["purposes"] if p[0] == purpose_id)
    product = C["products"][example["product"]]["name"]
    return {
        "question": example["text"], "measures": list(example["measures"]), "dimensions": ["month", "market"], "grain": "month",
        "filters": {"product": [product], "market": list(example["markets"])}, "unmatched_terms": [], "decision": purpose,
        "scope_global": False, "migration": None,
        "dashboard_brief": {"decision": purpose, "period": {"start": window["start"], "end": window["end"]}, "breakdown": "market",
                            "guided": {"id": example["id"], "purpose": purpose_id, "period": window["id"], "lead_measure": lead,
                                       "presentation": PRESENTATION}},
        "urgency": {"value": "normal", "source": "default", "evidence": None},
    }


def public() -> dict[str, Any]:
    C = catalog.CATALOG
    return {
        "purpose_question": PURPOSE_QUESTION, "period_question": PERIOD_QUESTION,
        "examples": [{"id": e["id"], "placement": e["placement"], "text": e["text"],
                      "product": C["products"][e["product"]]["name"], "markets": [C["markets"][m]["name"] for m in e["markets"]],
                      "measures": [C["measures"][m]["name"] for m in e["measures"]], "purposes": purpose_options(e),
                      "periods": period_options(e)}
                     for e in available()],
    }
