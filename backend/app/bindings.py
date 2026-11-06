"""Executable, deliberately narrow demo contract. These are team-defined formulas.

No workbook metadata is presented as a real Bayer schema. The self-contained
demo model uses the exact synthetic fact rows and explicit EUR conversion.
"""
from __future__ import annotations
from . import catalog as cat
from .governance import digest

VERSION = "demo-pmm-v1"
BINDINGS = {
    "net_sales": {"column": "NetSalesEUR", "source": "net_sales_m_eur_syn", "factor": 1_000_000,
                  "unit": "EUR", "format": "€ #,0.00;(€ #,0.00);€ 0.00", "aggregation": "SUM"},
    "units_shipped": {"column": "UnitsShipped", "source": "units_shipped_syn", "factor": 1,
                      "unit": "units", "format": "#,0", "aggregation": "SUM"},
}
DIMENSIONS = {"month": "Month", "product": "Product", "market": "Market", "region": "Region", "therapeutic_area": "TherapeuticArea"}


def rows() -> list[dict]:
    result = []
    for source in cat.SHEETS["product_market_monthly"]:
        product = cat.CATALOG["products"][source["product_id"]]
        market = cat.CATALOG["markets"][source["market_id"]]
        result.append({"Product": product["name"], "Market": source["market_id"], "Month": source["month"],
                       "Region": market["region"], "TherapeuticArea": product["therapeutic_area"],
                       "NetSalesEUR": round(source["net_sales_m_eur_syn"] * 1_000_000, 2),
                       "UnitsShipped": source["units_shipped_syn"], "ValueType": source["value_type"]})
    return result


def contract(spec: dict) -> dict:
    required = [m["id"] for m in spec["measures"]]
    missing = [m for m in required if m not in BINDINGS]
    unknown_dims = [d for d in spec.get("dimensions", []) if d not in DIMENSIONS]
    filters = spec.get("filters") or {}
    missing += [f"filter:{k}" for k in filters if k not in DIMENSIONS]
    if not missing and not unknown_dims and not selected_rows(spec):
        missing.append("No synthetic fact rows match this scope")
    supported = bool(required) and not missing and not unknown_dims and spec["decision_type"] == "new_build"
    return {"version": VERSION, "mode": "synthetic_demo_model", "supported": supported,
            "model_name": "BayerDemo", "table": "DemoFacts", "source_sheet": "Product_Market_Monthly",
            "bindings": {m: BINDINGS[m] for m in required if m in BINDINGS},
            "dimensions": DIMENSIONS, "missing": missing + unknown_dims,
            "data_hash": digest(rows()),
            "period": "January–October 2026; monthly source grain, no daily or patient data",
            "note": "Team-defined demo SUM formulas; EUR = workbook M EUR × 1,000,000. Shared local demo model, not a live Bayer model. All included fact rows are synthetic; this is not actual company performance."}


def selected_rows(spec: dict) -> list[dict]:
    return [r for r in rows() if all(not values or r[DIMENSIONS[key]] in values
                                   for key, values in (spec.get("filters") or {}).items())]


def expected_values(spec: dict) -> dict:
    selected = selected_rows(spec)
    breakdowns = {}
    for dim in sorted(set(spec.get("dimensions", [])) | {"month"}):
        groups = sorted({r[DIMENSIONS[dim]] for r in selected})
        breakdowns[dim] = [{"label": group, "values": {
            m["id"]: round(sum(r[BINDINGS[m["id"]]["column"]] for r in selected if r[DIMENSIONS[dim]] == group), 2)
            for m in spec["measures"]}} for group in groups]
    return {"rows": len(selected), "totals": {m["id"]: round(sum(r[BINDINGS[m["id"]]["column"]] for r in selected), 2)
                                              for m in spec["measures"]},
            "breakdowns": breakdowns,
            "note": "Python reference totals for target-runtime reconciliation. Power BI evaluation is not yet verified."}
