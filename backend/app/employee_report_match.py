"""Resolve an existing employee view for a matching governed KPI and scope."""
import re

from . import catalog
from .briefing_definitions import FILTERS, VIEWS
from .briefings import active_owners, report_views
from .report_register import published_revisions


# A local, monthly workbook view cannot satisfy an explicit delivery format or
# prove a custom time selection that the intake parser does not model.
_SPECIAL_REQUIREMENT = re.compile(
    r"\b(?:tableau|power\s?bi|excel|csv|pdf|powerpoint|pbix|pbip|export|publish|daily|weekly|quarterly|annual(?:ly)?|yearly|hourly|"
    r"yoy|ytd|year.over.year|real.time|q[1-4]|20\d{2}|yesterday|(?:last|this|next) (?:month|quarter|year)|"
    r"january|february|march|april|june|july|august|september|october|november|december)\b"
    r"|\bmay\s+(?:\d+|through|to)\b"
    r"|\b(?:by|per|each)\s+(?:hour|day|week|quarter|year|hospital|clinic|customer|channel|territory|site|sku)\b", re.I)
# When a requester acts is distinct from the period of data they want to see.
_DECISION_TIMING = re.compile(r"\b(?:act|decide|meet)\s+(?:this|next)\s+(?:month|quarter|year)\b", re.I)


def matching_employee_report(intent: dict) -> dict | None:
    measures = intent.get("measures") or []
    if (len(measures) != 1 or intent.get("grain") != "month" or intent.get("scope_global")
            or intent.get("migration") or intent.get("unmatched_terms") or intent.get("other_markets")
            or intent.get("source_asset_id") or set(intent.get("dimensions") or []) - {"month", "product", "market"}):
        return None
    product = catalog.CATALOG["products"][FILTERS["product_id"]]
    market = catalog.CATALOG["markets"][FILTERS["market_id"]]
    allowed = {"product": product["name"], "market": FILTERS["market_id"],
               "region": market["region"], "therapeutic_area": product["therapeutic_area"]}
    filters = {k: v for k, v in (intent.get("filters") or {}).items() if v}
    if not {"product", "market"}.issubset(filters) or any(k not in allowed or v != [allowed[k]] for k, v in filters.items()):
        return None
    metric = catalog.CATALOG["measures"].get(measures[0], {})
    for view_id, (report_id, _, label, kpi_id, _, _) in VIEWS.items():
        if metric.get("certified") and metric.get("kpi_id") == kpi_id:
            return {"report_id": report_id, "view_id": view_id, "label": label,
                    "url": f"/briefings?view={view_id}"}
    return None


async def native_reuse(store, intent: dict, user_turns: list[str], estate: dict) -> dict | None:
    if estate["decision"] != "new_build" or any(_SPECIAL_REQUIREMENT.search(_DECISION_TIMING.sub("", turn)) for turn in user_turns):
        return None
    match = matching_employee_report(intent)
    if not match:
        return None
    metric = catalog.CATALOG["measures"][intent["measures"][0]]
    owner = active_owners().get(metric.get("owner_id"))
    if not owner:
        return None
    # Resolve the same current revision and evidence that the employee screen renders.
    try:
        period, previous, views = report_views(await published_revisions(store))
    except ValueError:
        return None
    view = next(v for v in views if v["id"] == match["view_id"])
    report = {**match, "title": view["report"], "owner": owner["name"], "owner_id": owner["id"],
              "revision": view["revision"], "period": period, "previous_period": previous,
              "kpi_id": view["kpi_id"], "evidence": view["evidence"]}
    reason = (f"Open {report['title']} for {view['title'].lower()} in Nubeqa, Germany. "
              f"The employee report uses {view['kpi_id']}, has an active owner and shows monthly data through {period}.")
    rule = "The requested KPI, product, market and monthly grain match a readable employee report."
    rules = ["RULE-001", "RULE-002", "RULE-003"]
    recommendation = {"value": "reuse", "label": "Reuse", "reason": reason, "rule": rule, "rules_applied": rules,
                      "evidence": [{"step": 7, "task": "Check employee reports", "summary": rule}]}
    return {**estate, "decision": "reuse", "reason": reason, "rule": rule, "rules_applied": rules,
            "recommendation": recommendation, "candidate": None, "flags": [], "replaces": [],
            "change_type": "employee_report_reuse", "target_model": None, "target_model_id": None,
            "employee_report": report, "estate_assessment": {"decision": estate["decision"], "reason": estate["reason"]}}
