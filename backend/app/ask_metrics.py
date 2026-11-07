"""Trace an Ask workbook preview and its frozen monthly history to exact source records."""
import math
from datetime import date

from . import catalog, facts
from .briefings import active_owners
from .decision import score_asset
from .employee_report_match import matching_employee_report


def verified_reuse_preview(intent: dict, decision: dict, asset: dict) -> dict | None:
    """Verify the saved, request-scoped workbook preview. A native BI visual is never inferred."""
    saved = decision.get("preview")
    filters = {k: v for k, v in (intent.get("filters") or {}).items() if v}
    if (decision.get("decision") != "reuse" or not saved or not asset or not decision["candidate"].get("gates_pass")
            or intent.get("grain") != "month" or intent.get("unmatched_terms") or intent.get("other_markets")
            or intent.get("scope_global") or intent.get("migration") or set(filters) != {"product", "market"}
            or len(filters["product"]) != 1 or len(filters["market"]) != 1
            or set(intent.get("dimensions") or []) - {"product", "market", "month"}):
        return None
    product, market = filters["product"][0], filters["market"][0]
    product_id = next((pid for pid, p in catalog.CATALOG["products"].items() if p["name"] == product), None)
    region = catalog.CATALOG["markets"].get(market, {}).get("region")
    model = catalog.model_by_id(asset["model_id"]) or {}
    if (not product_id or not region or asset["product_scope"] not in (product, "All Pharma")
            or asset["market_scope"] not in (market, "Global") or model.get("product_scope") not in (product, "All Pharma")
            or model.get("region_scope") not in (region, "Global")):
        return None
    measures = [catalog.CATALOG["measures"].get(mid, {}) for mid in intent.get("measures", [])]
    if not measures or any(not m.get("fact_column") or m.get("kpi_id") not in asset["kpis"] for m in measures):
        return None
    # Historical numbers stay attributable only if today's pack reproduces the saved values.
    try:
        fresh = facts.preview(intent)
    except (KeyError, TypeError, ValueError):
        return None
    if not fresh or any(fresh[k] != saved.get(k) for k in ("month", "previous_month", "by", "columns", "rows")):
        return None
    periods = {saved["month"], saved["previous_month"]}
    source_rows = [i for i, r in enumerate(catalog.SHEETS["product_market_monthly"], 2)
                   if r["product_id"] == product_id and r["market_id"] == market and r["month"] in periods]
    if len(source_rows) != 2:
        return None
    return {**saved, "source": "Product_Market_Monthly", "source_rows": source_rows,
            "fields": [m["fact_column"] for m in measures],
            "description": f"Workbook observations for {product} in {market}. The catalog records these KPIs on {asset['id']}."}

def metric_series(intent: dict, decision: dict) -> dict | None:
    """Read one product-market slice only when the recommendation's two-period evidence matches."""
    if decision.get("decision") != "reuse":
        return None
    native = decision.get("employee_report")
    if native:
        match = matching_employee_report(intent)
        metric = catalog.CATALOG["measures"].get((intent.get("measures") or [None])[0], {})
        if (not match or match["report_id"] != native.get("report_id") or match["view_id"] != native.get("view_id")
                or native.get("display_mode") not in ("chart", "table") or native.get("kpi_id") != metric.get("kpi_id")
                or native.get("owner_id") != metric.get("owner_id") or native.get("owner_id") not in active_owners()):
            return None
        proof = native.get("evidence") or {}
        expected_rows = proof.get("rows") or []
        display_mode = native["display_mode"]
    else:
        asset = catalog.asset_by_id((decision.get("candidate") or {}).get("asset_id")) or {}
        preview = verified_reuse_preview(intent, decision, asset)
        if not preview or not score_asset(intent, asset, catalog.CATALOG).reusable:
            return None
        expected_rows = preview["source_rows"]
        display_mode = "chart"

    product = intent["filters"]["product"][0]
    market_id = intent["filters"]["market"][0]
    product_id = next((pid for pid, p in catalog.CATALOG["products"].items() if p["name"] == product), None)
    filters = {"product_id": product_id, "market_id": market_id}
    columns = []
    for mid in intent["measures"]:
        metric = catalog.CATALOG["measures"].get(mid, {})
        if not metric.get("certified") or not metric.get("fact_column"):
            return None
        columns.append({"id": mid, "name": metric["name"], "unit": metric.get("fact_unit") or metric["unit"],
                        "field": metric["fact_column"], "lower_is_better": metric["lower_is_better"]})
    if native and native["view_id"] == "sales":
        columns.append({"id": "sales_forecast", "name": "Sales forecast", "unit": columns[0]["unit"],
                        "field": "forecast_m_eur_syn", "lower_is_better": None})

    rows = [(i, r) for i, r in enumerate(catalog.SHEETS.get("product_market_monthly", []), 2)
            if r.get("product_id") == product_id and r.get("market_id") == market_id]
    if len(rows) < 2 or any(not isinstance(r.get("month"), str) for _, r in rows):
        return None
    rows.sort(key=lambda pair: pair[1]["month"])
    if len({r["month"][:7] for _, r in rows}) != len(rows):
        return None
    rows = rows[-12:]
    if {i for i, _ in rows[-2:]} != set(expected_rows):
        return None
    if native:
        recent = [r for _, r in rows[-2:]]
        fields = proof.get("fields") or []
        records = [{k: r.get(k) for k in fields} for r in recent]
        if (proof.get("sheet") != "Product_Market_Monthly" or proof.get("filters") != filters or records != proof.get("records")
                or any(col["field"] not in fields for col in columns)
                or [r["month"][:7] for r in recent] != [native.get("previous_period"), native.get("period")]):
            return None

    points = []
    prior = None
    for index, r in rows:
        try:
            month = date.fromisoformat(r["month"])
        except ValueError:
            return None
        month_index = month.year * 12 + month.month
        if month.day != 1 or (prior is not None and month_index != prior + 1):
            return None
        prior = month_index
        values = {col["id"]: r.get(col["field"]) for col in columns}
        if (r.get("value_type") not in ("actual_like_synthetic", "forecast_like_synthetic") or
                any(type(v) not in (int, float) or not math.isfinite(v) for v in values.values())):
            return None
        points.append({"period": r["month"][:7], "row": index, "value_type": r["value_type"], "values": values})
    return {"source": "Product_Market_Monthly", "filters": filters, "product": product,
            "market": catalog.CATALOG["markets"][market_id]["name"], "start_period": points[0]["period"],
            "end_period": points[-1]["period"], "display_mode": display_mode, "columns": columns, "points": points}
