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


def supports_monthly_workbook(user_turns: list[str]) -> bool:
    return not any(_SPECIAL_REQUIREMENT.search(_DECISION_TIMING.sub("", turn)) for turn in user_turns)


async def native_reuse(store, intent: dict, user_turns: list[str], estate: dict) -> dict | None:
    if estate["decision"] != "new_build" or not supports_monthly_workbook(user_turns):
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
              "revision": view["revision"], "display_mode": view["display_mode"], "period": period, "previous_period": previous,
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


# --------------------------------------------------------------------------- saved Ask dashboards
def covers(saved: dict, want: dict) -> bool:
    """A saved Ask dashboard covers a request when it has the same product and market IDs, every requested KPI, every
    requested breakdown, and its period contains the requested one (a request with no period accepts any)."""
    req = saved.get("requirements") or {}
    if set(req.get("products") or []) != want["products"] or set(req.get("markets") or []) != want["markets"]:
        return False
    on_dashboard = {c.get("id") for c in saved.get("columns") or [] if c.get("kpi_id")}
    if not want["measures"] or not want["measures"] <= on_dashboard:
        return False
    if not want["dimensions"] <= set(saved.get("dimensions") or req.get("dimensions") or []) | {"month", "product", "market"}:
        return False
    period, asked = saved.get("period") or {}, want.get("period") or {}
    if asked.get("start") and asked.get("end"):
        return bool(period.get("start")) and period["start"] <= asked["start"] and asked["end"] <= period.get("end", "")
    return True


def wanted_from_intent(intent: dict) -> dict | None:
    """The request's scope as catalog IDs, or None when it cannot be matched to a saved monthly dashboard."""
    C = catalog.CATALOG
    if (intent.get("grain") not in (None, "month") or intent.get("scope_global") or intent.get("migration")
            or intent.get("unmatched_terms") or intent.get("other_markets") or intent.get("source_asset_id")):
        return None
    filters = intent.get("filters") or {}
    names = {p["name"]: pid for pid, p in C["products"].items()}
    products = {names.get(p, p) for p in filters.get("product") or []}
    markets = set(filters.get("market") or [])
    if not products or not markets or not products <= set(C["products"]) or not markets <= set(C["markets"]):
        return None
    # Only KPIs a dashboard can show count: a requested KPI the workbook cannot give is left out of any build too.
    from .dashboard_builder import _supported  # lazy: dashboard_builder imports this module
    buildable = set(intent.get("measures") or []) & set(_supported())
    if not buildable:
        return None
    return {"products": products, "markets": markets, "measures": buildable,
            "dimensions": set(intent.get("dimensions") or []), "period": (intent.get("dashboard_brief") or {}).get("period")}


def wanted_from_requirements(req: dict) -> dict:
    """The clarified dashboard brief's scope, for the builder's check before a new build."""
    return {"products": set(req["products"]), "markets": set(req["markets"]), "measures": set(req["measures"]),
            "dimensions": set(req.get("dimensions") or []), "period": req.get("period")}


def newest_covering(saved: list[dict], want: dict | None, exclude_run: tuple[str, str] | None = None) -> dict | None:
    """The newest saved Ask dashboard covering `want`. `exclude_run` skips the run's own dashboard (conversation, run)."""
    if not want:
        return None
    found = [d for d in saved if d.get("id") and covers(d, want) and (d.get("conversation_id"), d.get("run_id")) != exclude_run]
    return max(found, key=lambda d: d.get("created_at") or "") if found else None


async def saved_dashboards(store) -> list[dict]:
    """Metadata of every dashboard built in Ask (no chart points), for step 3 and the builder's check."""
    from .bi_estate import _dashboards  # lazy: bi_estate is large and imports the briefing modules
    return await _dashboards(store)


async def matching_saved_dashboard(store, want: dict, exclude_run: tuple[str, str] | None = None) -> dict | None:
    return newest_covering(await saved_dashboards(store), want, exclude_run)


def saved_dashboard_summary(saved: dict) -> dict:
    """What step 3 and the decision show about a covering dashboard built in Ask."""
    C = catalog.CATALOG
    kpis = [{"id": c["id"], "name": c.get("name") or C["measures"].get(c["id"], {}).get("name", c["id"]), "kpi_id": c.get("kpi_id")}
            for c in saved.get("columns") or [] if c.get("kpi_id")]
    return {"id": saved["id"], "title": saved.get("title") or saved["id"], "url": f"/dashboards/{saved['id']}",
            "created_at": saved.get("created_at"), "created_by": (saved.get("created_by") or {}).get("name") or "someone",
            "period": saved.get("period") or {}, "kpis": kpis, "scope": saved.get("scope") or {}, "owner": None}


def _month(period: str | None) -> str:
    if not period:
        return ""
    names = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
    return f"{names[int(period[5:7]) - 1]} {period[:4]}"


def saved_dashboard_reuse(dashboard: dict | None, user_turns: list[str], estate: dict) -> dict | None:
    """Turn a new build into Reuse when step 3 found a dashboard built in Ask that covers the request. Python only.
    It has no owner yet (the BI steward assigns one), which is shown and proposed as follow-up, not a blocker."""
    if not dashboard or estate["decision"] != "new_build" or not supports_monthly_workbook(user_turns):
        return None
    period, scope, creator = dashboard["period"], dashboard["scope"], dashboard["created_by"]
    places = f"{', '.join(scope.get('products') or [])} in {' and '.join(scope.get('markets') or [])}"
    reason = (f"Open {dashboard['title']}. It was built in Ask by {creator} and already shows "
              f"{', '.join(k['name'] for k in dashboard['kpis'])} for {places}, {_month(period.get('start'))} to {_month(period.get('end'))}. "
              "It has no owner yet, so the BI steward should assign one.")
    rule = "Step 3 found a dashboard built in Ask with the requested product, markets, KPIs and period."
    rules = ["RULE-001", "RULE-002"]
    recommendation = {"value": "reuse", "label": "Reuse", "reason": reason, "rule": rule, "rules_applied": rules,
                      "evidence": [{"step": 3, "task": "Find existing analytics", "summary": rule}]}
    return {**estate, "decision": "reuse", "reason": reason, "rule": rule, "rules_applied": rules,
            "recommendation": recommendation, "candidate": None, "flags": [], "replaces": [],
            "change_type": "saved_dashboard_reuse", "target_model": None, "target_model_id": None,
            "saved_dashboard": dashboard, "estate_assessment": {"decision": estate["decision"], "reason": estate["reason"]}}
