"""SinceAI 2026 Builder Data Pack.

Reads the workbook in ``materials/`` and builds the analytics catalog the
pipeline reasons over. All values in the workbook are synthetic; product and
therapeutic-area names are public context only.

Sheet → catalog mapping
  KPI_Catalog            measures (one per canonical metric) with their variants
  Semantic_Models        shared semantic models (refresh, endorsement, AI readiness)
  Analytics_Assets       reports/dashboards/apps/workbooks, enriched with
    + Asset_KPI_Map        KPIs used (mapped to canonical measures, variants flagged)
    + Asset_Usage          views / users / errors in the last 3 months
    + Governance_Signals   open signals per asset
    + Migration_Backlog    Tableau → Power BI candidate path
    + Data_Quality         issues per asset/model
  Owners, Workspaces, Products, Markets, Lineage_Edges, Governance_Rules
  Business_Requests      the 10 distinct request texts become presets
  Product_Market_Monthly, Market_Access, Supply_Operations, Launch_Milestones
                         synthetic business facts for previews and verification
"""
from __future__ import annotations

import os
import re
from collections import Counter, defaultdict
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

REPO_DIR = Path(__file__).resolve().parents[2]
DEFAULT_PATH = REPO_DIR / "materials" / "Bayer_Pharmaceuticals_SinceAI_2026_FINAL_Builder_Data_Pack.xlsx"

# Sheets that are tables (header row first). START_HERE and Package_Overview are prose.
TABLE_SHEETS = [
    "Public_References", "Products", "Markets", "Owners", "KPI_Catalog", "Workspaces", "Semantic_Models",
    "Analytics_Assets", "Asset_KPI_Map", "Asset_Usage", "Lineage_Edges", "Product_Market_Monthly",
    "Launch_Milestones", "Market_Access", "Supply_Operations", "Data_Quality", "Governance_Signals",
    "Migration_Backlog", "Business_Requests", "Governance_Rules", "Data_Dictionary", "Change_Log",
]

# Bump when the catalog structure changes, so stores holding an older catalog are reseeded.
CATALOG_SCHEMA = 2

# Usage window for adoption evidence: the last three months in the data pack.
USAGE_MONTHS = 3


WORKBOOK_COMPANY_NAME = "Bayer"  # how the source workbook names the company; shown everywhere as SinceAI


def snake(name: str) -> str:
    """Sheet names already use underscores: KPI_Catalog -> kpi_catalog."""
    return name.lower()


def _cell(v: Any) -> Any:
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, str) and not v.startswith("http"):  # the workbook is unchanged; source links must keep working
        return v.replace(WORKBOOK_COMPANY_NAME, "SinceAI")
    return v


def workbook_path() -> Path:
    return Path(os.getenv("DATAPACK_PATH") or DEFAULT_PATH)


@lru_cache(maxsize=4)
def read_workbook(path: str | None = None) -> dict[str, list[dict[str, Any]]]:
    """All table sheets as lists of row dicts, keyed by snake_case sheet name."""
    import openpyxl

    wb = openpyxl.load_workbook(path or workbook_path(), read_only=True, data_only=True)
    sheets: dict[str, list[dict[str, Any]]] = {}
    for name in TABLE_SHEETS:
        if name not in wb.sheetnames:
            continue
        rows = list(wb[name].iter_rows(values_only=True))
        header = [h for h in rows[0] if h is not None]
        sheets[snake(name)] = [
            {h: _cell(v) for h, v in zip(header, r) if h != "synthetic_record"}
            for r in rows[1:] if any(c is not None for c in r)
        ]
    wb.close()
    return sheets


# ---------------------------------------------------------------- vocabulary
def measure_id(canonical_metric: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", canonical_metric.lower()).strip("_")


# Extra phrases people use for each canonical metric (lower case).
MEASURE_ALIASES: dict[str, list[str]] = {
    "net_sales": ["net sales", "first sales", "sales performance", "performance", "revenue"],
    "net_sales_growth": ["sales growth", "growth", "performance"],
    "forecast_variance": ["forecast variance", "variance to forecast", "vs forecast"],
    "demand_forecast_accuracy": ["forecast accuracy", "supply-risk", "supply risk", "demand forecast"],
    "demand_forecast_bias": ["forecast bias"],
    "units_shipped": ["units shipped", "volume", "units"],
    "inventory_coverage": ["inventory coverage", "inventory", "stock cover", "weeks of cover", "supply-risk", "supply risk"],
    "on_time_in_full": ["otif", "on-time in-full", "on time in full", "on-time delivery", "supply-risk", "supply risk"],
    "launch_adoption_index": ["adoption indicators", "launch adoption", "launch readiness", "adoption"],
    "market_access_coverage": ["market access"],
    "reimbursement_status_coverage": ["reimbursement"],
    "gross_to_net_rate": ["gross-to-net", "gross to net", "gtn"],
    "operating_contribution": ["operating contribution", "contribution", "profitability"],
    "budget_variance": ["budget variance", "budget"],
    "commercial_reach_index": ["commercial reach", "reach"],
    "digital_engagement_index": ["digital engagement", "engagement"],
    "report_adoption": ["report adoption", "report usage"],
    "certified_asset_share": ["certified asset share", "certified share"],
}

# Synthetic fact columns in Product_Market_Monthly that preview each measure.
FACT_COLUMNS = {
    "net_sales": ("net_sales_m_eur_syn", "M EUR"),
    "forecast_variance": ("forecast_variance_pct", "%"),
    "market_access_coverage": ("market_access_coverage_pct_syn", "%"),
    "on_time_in_full": ("otif_pct_syn", "%"),
    "inventory_coverage": ("inventory_weeks_syn", "weeks"),
    "units_shipped": ("units_shipped_syn", "units"),
}

# For these measures a lower value is better.
LOWER_IS_BETTER = {"forecast_variance", "demand_forecast_bias", "gross_to_net_rate", "budget_variance"}

DIMENSIONS = {
    "product": {"name": "Product", "keywords": ["by product", "by medicine", "per product", "brands", "by brand", "product performance"]},
    "market": {"name": "Market (country)", "keywords": ["by country", "country-level", "per country", "by market", "and markets", "and country", "countries"]},
    "region": {"name": "Region", "keywords": ["by region", "per region"]},
    "therapeutic_area": {"name": "Therapeutic area", "keywords": ["by therapeutic area", "by therapy area"]},
    "month": {"name": "Month", "keywords": ["monthly", "trend", "over time", "by month"]},
}

REGION_ALIASES = {"emea": "EMEA", "europe": "EMEA", "north america": "North America", "asia pacific": "Asia Pacific",
                  "apac": "Asia Pacific", "latin america": "Latin America", "latam": "Latin America"}


# ---------------------------------------------------------------- presets
# The 10 distinct texts in Business_Requests, mapped to governed KPIs and scope.
PRESETS = [
    {"id": "req_migrate_xarelto", "department": "Commercial", "title": "Replace a legacy Tableau workbook",
     "prompt": "Please create a Power BI replacement for our legacy Tableau Xarelto commercial workbook.",
     "decision": "Keep the Xarelto commercial view available after Tableau is switched off, without migrating waste.",
     "measures": ["net_sales", "net_sales_growth"], "dimensions": ["market", "month"],
     "filters": {"product": ["Xarelto"]}, "scope_global": True, "migration": {"from": "Tableau"}, "requests": 22},
    {"id": "req_finance_gtn", "department": "Finance", "title": "Finance dashboard",
     "prompt": "Can we have a new finance dashboard for net sales, gross-to-net and budget variance by product?",
     "decision": "Decide which products need a pricing or budget review this month.",
     "measures": ["net_sales", "gross_to_net_rate", "budget_variance"], "dimensions": ["product"],
     "filters": {}, "scope_global": True, "requests": 20},
    {"id": "req_launch_lynkuet", "department": "Launch Excellence", "title": "Lynkuet launch tracker",
     "prompt": "Can we build a launch dashboard for Lynkuet with market access, first sales and adoption indicators?",
     "decision": "Decide which launch markets need support to speed up access and uptake.",
     "measures": ["market_access_coverage", "net_sales", "launch_adoption_index"], "dimensions": ["market"],
     "filters": {"product": ["Lynkuet"]}, "scope_global": True, "requests": 17},
    {"id": "req_access_by_product", "department": "Market Access", "title": "Market access by product",
     "prompt": "Please build a new report for market access coverage and reimbursement status by product.",
     "decision": "Decide where to focus reimbursement work across the portfolio.",
     "measures": ["market_access_coverage", "reimbursement_status_coverage"], "dimensions": ["product"],
     "filters": {}, "scope_global": True, "requests": 16},
    {"id": "req_oncology_compare", "department": "Commercial", "title": "Oncology brand comparison",
     "prompt": "I need a dashboard comparing product performance across oncology brands and markets.",
     "decision": "Decide where oncology brands under-perform and need commercial attention.",
     "measures": ["net_sales", "net_sales_growth"], "dimensions": ["product", "market"],
     "filters": {"therapeutic_area": ["Oncology"]}, "scope_global": True, "requests": 16},
    {"id": "req_kerendia_mgmt", "department": "Commercial", "title": "Kerendia management report",
     "prompt": "I need a new Kerendia management report for monthly performance in EMEA and North America.",
     "decision": "Review Kerendia performance each month and agree corrective actions by region.",
     "measures": ["net_sales", "net_sales_growth"], "dimensions": ["region", "month"],
     "filters": {"product": ["Kerendia"], "region": ["EMEA", "North America"]}, "scope_global": False, "requests": 14},
    {"id": "req_exec_view", "department": "Executive", "title": "Executive one-view",
     "prompt": "We need one executive view combining net sales, forecast accuracy and inventory coverage for SinceAI Pharma.",
     "decision": "Give leadership one trusted view of sales, forecast quality and supply cover.",
     "measures": ["net_sales", "demand_forecast_accuracy", "inventory_coverage"], "dimensions": ["product"],
     "filters": {}, "scope_global": True, "requests": 14},
    {"id": "req_beyonttra_launch", "department": "Launch Excellence", "title": "Beyonttra launch readiness",
     "prompt": "Can you create a country-level Beyonttra report for launch readiness and reimbursement progress?",
     "decision": "Decide which countries are ready to launch and where reimbursement is blocking.",
     "measures": ["launch_adoption_index", "reimbursement_status_coverage"], "dimensions": ["market"],
     "filters": {"product": ["Beyonttra"]}, "scope_global": True, "requests": 13},
    {"id": "req_nubeqa_global", "department": "Commercial", "title": "Nubeqa global view",
     "prompt": "Create a global Nubeqa dashboard showing sales growth, forecast variance and market access by country.",
     "decision": "Decide which countries need action on Nubeqa growth, forecast gaps or access.",
     "measures": ["net_sales_growth", "forecast_variance", "market_access_coverage"], "dimensions": ["market"],
     "filters": {"product": ["Nubeqa"]}, "scope_global": True, "requests": 9},
    {"id": "req_supply_risk", "department": "Supply Chain", "title": "Supply risk by medicine",
     "prompt": "We need a monthly supply-risk dashboard by medicine and country.",
     "decision": "Decide which product-country combinations need supply intervention this month.",
     "measures": ["on_time_in_full", "inventory_coverage", "demand_forecast_accuracy"], "dimensions": ["product", "market"],
     "filters": {}, "scope_global": True, "requests": 9},
]

# Scenarios built from assets in the estate, so the demo shows every outcome.
# They are not Business_Requests rows; the UI labels them "Estate scenario".
SCENARIOS = [
    {"id": "scn_reuse_lynkuet_es", "department": "Supply Chain", "title": "Lynkuet supply in Spain", "scenario": "reuse",
     "prompt": "Show monthly inventory coverage and OTIF for Lynkuet in Spain.",
     "decision": "Decide whether to adjust replenishment for the Spanish supply review.",
     "measures": ["inventory_coverage", "on_time_in_full"], "dimensions": ["month"],
     "filters": {"product": ["Lynkuet"], "market": ["ES"]}, "scope_global": False},
    {"id": "scn_reuse_eylea_jp", "department": "Commercial", "title": "Eylea in Japan", "scenario": "review",
     "prompt": "How are Eylea net sales and digital engagement developing in Japan?",
     "decision": "Check Eylea momentum in Japan before the quarterly review.",
     "measures": ["net_sales", "digital_engagement_index"], "dimensions": ["month"],
     "filters": {"product": ["Eylea"], "market": ["JP"]}, "scope_global": False},
    {"id": "scn_repair_xarelto_mx", "department": "Supply Chain", "title": "Xarelto supply in Mexico", "scenario": "review",
     "prompt": "Show Xarelto on-time-in-full and market access coverage for Mexico.",
     "decision": "Decide whether Mexico needs a supply or access intervention for Xarelto.",
     "measures": ["on_time_in_full", "market_access_coverage"], "dimensions": ["month"],
     "filters": {"product": ["Xarelto"], "market": ["MX"]}, "scope_global": False},
    {"id": "scn_repair_canada_budget", "department": "Finance", "title": "Canada budget and access", "scenario": "review",
     "prompt": "I need budget variance and market access coverage for the portfolio in Canada.",
     "decision": "Decide where Canada spend is off budget relative to access progress.",
     "measures": ["budget_variance", "market_access_coverage"], "dimensions": ["product"],
     "filters": {"market": ["CA"]}, "scope_global": False},
    {"id": "scn_out_of_scope", "department": "Commercial", "title": "Patient-level question", "scenario": "not_feasible",
     "prompt": "Can we see Nubeqa patient adherence by prescriber?",
     "decision": "Understand adherence by prescriber.",
     "measures": [], "requested_terms": ["patient adherence", "prescriber-level data"], "dimensions": [],
     "filters": {"product": ["Nubeqa"]}, "scope_global": False},
]


# ---------------------------------------------------------------- catalog
def build_catalog(sheets: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    owners = {o["owner_id"]: o for o in sheets["owners"]}
    workspaces = {w["workspace_id"]: w for w in sheets["workspaces"]}
    products = {p["product_id"]: p for p in sheets["products"]}
    markets = {m["market_id"]: m for m in sheets["markets"]}
    kpis = {k["kpi_id"]: k for k in sheets["kpi_catalog"]}

    # Measures: one per canonical metric, with all variants.
    measures: dict[str, dict[str, Any]] = {}
    for k in sheets["kpi_catalog"]:
        mid = measure_id(k["canonical_metric"])
        m = measures.setdefault(mid, {"name": k["canonical_metric"], "unit": k["unit"], "domain": k["domain"],
                                      "default_grain": "month", "certified": False, "kpi_id": None, "variants": [],
                                      "definition": "No approved definition yet.", "owner_id": None,
                                      "criticality": k.get("business_criticality")})
        if k["definition_status"] == "canonical" and k["approval_status"] == "approved":
            m.update(certified=True, kpi_id=k["kpi_id"], owner_id=k["owner_id"],
                     definition=f"Approved {k['domain'].lower()} definition of {k['canonical_metric']} (KPI {k['kpi_id']}, {k['unit']}, {k['default_frequency']}).")
        else:
            m["variants"].append({"kpi_id": k["kpi_id"], "name": k["kpi_name"], "status": k["definition_status"],
                                  "approval": k["approval_status"], "owner_id": k["owner_id"]})
    for mid, m in measures.items():
        m["keywords"] = sorted({m["name"].lower(), *MEASURE_ALIASES.get(mid, [])})
        m["owner"] = owners.get(m["owner_id"], {}).get("owner_name")
        m["fact_column"], m["fact_unit"] = FACT_COLUMNS.get(mid, (None, None))
        m["lower_is_better"] = mid in LOWER_IS_BETTER

    # Data quality and signals indexed by record.
    dq = defaultdict(list)
    for d in sheets["data_quality"]:
        dq[d["record_id"]].append({"id": d["issue_id"], "field": d["field"], "value": d["issue_value"],
                                   "severity": d["severity"], "impact": d["impact"]})
    signals = defaultdict(list)
    for s in sheets["governance_signals"]:
        signals[s["asset_id"]].append({"id": s["signal_id"], "code": s["signal_code"], "severity": s["severity"],
                                       "status": s["status"], "detected_by": s["detected_by"]})
    migration = {m["source_asset_id"]: m for m in sheets["migration_backlog"]}

    # Usage: last USAGE_MONTHS months.
    months = sorted({u["month"] for u in sheets["asset_usage"]})
    window = set(months[-USAGE_MONTHS:])
    usage = defaultdict(lambda: Counter())
    for u in sheets["asset_usage"]:
        if u["month"] in window:
            c = usage[u["asset_id"]]
            c["views"] += u["views"] or 0
            c["users"] += u["unique_users"] or 0
            c["errors"] += u["query_errors"] or 0
            c["load_ms"] += u["avg_load_ms"] or 0
            c["months"] += 1

    asset_kpis = defaultdict(list)
    for r in sheets["asset_kpi_map"]:
        asset_kpis[r["asset_id"]].append((r["kpi_id"], r["usage_role"]))

    # Semantic models.
    models: dict[str, dict[str, Any]] = {}
    for sm in sheets["semantic_models"]:
        o = owners.get(sm["owner_id"], {})
        models[sm["model_id"]] = {
            **{k: sm[k] for k in ("model_name", "workspace_id", "product_scope", "region_scope", "model_type", "endorsement",
                                  "refresh_frequency", "refresh_status", "owner_id", "table_count", "measure_count",
                                  "ai_readiness", "ai_issue_pattern")},
            "id": sm["model_id"], "name": sm["model_name"], "platform": "Tableau" if "Tableau" in sm["model_type"] else "Power BI",
            "workspace": workspaces.get(sm["workspace_id"], {}).get("workspace_name"),
            "owner": o.get("owner_name"), "owner_status": o.get("status"), "dq_issues": dq.get(sm["model_id"], []),
            "measures": [], "assets": [],
        }

    assets: list[dict[str, Any]] = []
    for a in sheets["analytics_assets"]:
        o = owners.get(a["owner_id"], {})
        used = asset_kpis.get(a["asset_id"], [])
        a_measures, conflicts, variants = [], {}, {}
        for kpi_id, _role in used:
            k = kpis.get(kpi_id)
            if not k:
                continue
            mid = measure_id(k["canonical_metric"])
            a_measures.append(mid)
            if k["definition_status"] == "definition_conflict":
                conflicts[mid] = f"Uses '{k['kpi_name']}' ({kpi_id}), a conflicting definition of {k['canonical_metric']}."
            elif k["definition_status"] != "canonical":
                variants[mid] = f"Uses '{k['kpi_name']}' ({kpi_id}, {k['definition_status'].replace('_', ' ')}) instead of the approved KPI."
        u = usage.get(a["asset_id"], Counter())
        mig = migration.get(a["asset_id"])
        model = models.get(a["model_id"])
        asset = {
            "id": a["asset_id"], "name": a["asset_name"], "asset_type": a["asset_type"], "platform": a["platform"],
            "workspace_id": a["workspace_id"], "workspace": workspaces.get(a["workspace_id"], {}).get("workspace_name"),
            "model_id": a["model_id"], "product_scope": a["product_scope"], "market_scope": a["market_scope"],
            "owner_id": a["owner_id"], "owner": o.get("owner_name") or "No owner", "owner_status": o.get("status") or "missing",
            "created": a["created_date"], "last_modified": a["last_modified"], "lifecycle": a["lifecycle_status"],
            "endorsement": a["endorsement"], "certified": a["endorsement"] in ("certified", "promoted"),
            "audience": a["estimated_audience"], "classification": a["classification"], "delivery_model": a["delivery_model"],
            "grain": "month", "kpis": [k for k, _ in used], "measures": list(dict.fromkeys(a_measures)),
            "conflicts": conflicts, "variants": variants,
            "views_90d": u["views"], "users_90d": u["users"], "errors_90d": u["errors"],
            "avg_load_ms": round(u["load_ms"] / u["months"]) if u["months"] else None,
            "signals": signals.get(a["asset_id"], []), "dq_issues": dq.get(a["asset_id"], []),
            "migration": {k: mig[k] for k in ("recommended_path_candidate", "candidate_target_model_id", "complexity",
                                              "status", "synthetic_reason")} if mig else None,
            "refresh_status": model["refresh_status"] if model else None,
            "model_ai_readiness": model["ai_readiness"] if model else None,
        }
        assets.append(asset)
        if model:
            model["assets"].append(asset["id"])
            # A model serves a measure if some report on it uses the approved KPI.
            for kpi_id, _ in used:
                k = kpis.get(kpi_id)
                if k and k["definition_status"] == "canonical":
                    model["measures"].append(measure_id(k["canonical_metric"]))
    for m in models.values():
        m["measures"] = sorted(set(m["measures"]))

    lineage = [{"source": e["source_id"], "target": e["target_id"], "type": e["edge_type"], "relationship": e["relationship"]}
               for e in sheets["lineage_edges"]]

    return {
        "source": "SinceAI 2026 Builder Data Pack (synthetic)",
        "schema": CATALOG_SCHEMA,
        "measures": measures,
        "dimensions": DIMENSIONS,
        "models": models,
        "assets": assets,
        "owners": {k: {kk: v[kk] for kk in ("owner_name", "role", "scope", "status")} for k, v in owners.items()},
        "workspaces": {k: {kk: v[kk] for kk in ("workspace_name", "scope", "environment", "platform", "governance_mode", "classification")}
                       for k, v in workspaces.items()},
        "products": {k: {"name": v["product_name"], "therapeutic_area": v["therapeutic_area"], "stage": v["portfolio_stage"]}
                     for k, v in products.items()},
        "markets": {k: {"name": v["market_name"], "region": v["region"], "currency": v["currency"]} for k, v in markets.items()},
        "lineage": lineage,
        "rules": [{"id": r["rule_id"], "name": r["rule_name"], "description": r["rule_description"], "priority": r["priority"]}
                  for r in sheets["governance_rules"]],
        "usage_window": sorted(window),
    }


def load(path: str | None = None) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    sheets = read_workbook(str(path) if path else None)
    return sheets, build_catalog(sheets)
