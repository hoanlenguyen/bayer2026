"""Read-only catalog tools the agents can call. Metadata and aggregates only, never personal data."""
from __future__ import annotations

from typing import Any

from .. import catalog as cat
from ..llm import Tool


def _asset_brief(a: dict[str, Any]) -> dict[str, Any]:
    return {k: a.get(k) for k in ("id", "name", "asset_type", "platform", "product_scope", "market_scope", "lifecycle",
                                  "endorsement", "owner", "owner_status", "views_90d", "model_id")}


def search_catalog(query: str) -> dict[str, Any]:
    q = query.lower()
    words = [w for w in q.replace(",", " ").split() if len(w) > 2]

    def hit(*texts: Any) -> bool:
        blob = " ".join(str(t) for t in texts).lower()
        return q in blob or any(w in blob for w in words)

    C = cat.CATALOG
    return {
        "measures": [{"id": k, "name": m["name"], "domain": m["domain"], "variants": len(m["variants"])}
                     for k, m in C["measures"].items() if hit(k, m["name"], " ".join(m["keywords"]))][:10],
        "models": [{"id": m["id"], "name": m["name"], "endorsement": m["endorsement"], "refresh_status": m["refresh_status"]}
                   for m in C["models"].values() if hit(m["name"], m["product_scope"], m["region_scope"])][:10],
        "reports": [_asset_brief(a) for a in sorted(C["assets"], key=lambda a: -a["views_90d"])
                    if hit(a["name"], a["product_scope"], a["market_scope"])][:10],
    }


def get_kpi(measure_id: str) -> dict[str, Any]:
    m = cat.CATALOG["measures"].get(measure_id)
    if not m:
        return {"error": f"No measure '{measure_id}' in the catalog"}
    return {"id": measure_id, **{k: m[k] for k in ("name", "kpi_id", "definition", "unit", "domain", "certified", "owner")},
            "variants": m["variants"]}


def get_model(model_id: str) -> dict[str, Any]:
    m = cat.model_by_id(model_id)
    if not m:
        return {"error": f"No semantic model '{model_id}' in the catalog"}
    keys = ("id", "name", "workspace", "platform", "product_scope", "region_scope", "endorsement", "refresh_frequency",
            "refresh_status", "ai_readiness", "ai_issue_pattern", "owner", "owner_status", "measures", "table_count", "measure_count")
    return {**{k: m.get(k) for k in keys}, "reports_on_model": len(m["assets"]), "dq_issues": m["dq_issues"]}


def get_report(report_id: str) -> dict[str, Any]:
    a = cat.asset_by_id(report_id)
    if not a:
        return {"error": f"No report '{report_id}' in the catalog"}
    return {**_asset_brief(a), **{k: a.get(k) for k in ("measures", "conflicts", "variants", "users_90d", "errors_90d",
                                                         "signals", "migration", "last_modified", "workspace")}}


def get_lineage(node_id: str) -> dict[str, Any]:
    edges = cat.CATALOG["lineage"]
    up = [e for e in edges if e["target"] == node_id]
    down = [e for e in edges if e["source"] == node_id]
    return {"node": node_id, "upstream": up[:20], "downstream": down[:20], "downstream_count": len(down)}


CATALOG_TOOLS = [
    Tool("search_catalog", "Find KPIs, semantic models and existing reports by keyword (product, market, KPI name).",
         {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}, search_catalog),
    Tool("get_kpi", "Approved definition of a canonical KPI and its local, duplicate or conflicting variants.",
         {"type": "object", "properties": {"measure_id": {"type": "string"}}, "required": ["measure_id"]}, get_kpi),
    Tool("get_model", "Shared semantic model: endorsement, refresh, AI readiness, KPIs it serves, data-quality issues.",
         {"type": "object", "properties": {"model_id": {"type": "string"}}, "required": ["model_id"]}, get_model),
    Tool("get_report", "Existing report: scope, KPIs, usage in 90 days, owner, governance signals, migration backlog.",
         {"type": "object", "properties": {"report_id": {"type": "string"}}, "required": ["report_id"]}, get_report),
    Tool("get_lineage", "Upstream and downstream dependencies of a model or report (impact analysis).",
         {"type": "object", "properties": {"node_id": {"type": "string"}}, "required": ["node_id"]}, get_lineage),
]


def catalog_brief() -> str:
    """Compact catalog summary for prompts: IDs, names, domains, products and markets."""
    C = cat.CATALOG
    measures = "\n".join(f"- {k}: {m['name']} ({m['unit']}, {m['domain']})" for k, m in C["measures"].items())
    dims = ", ".join(f"{k} ({d['name']})" for k, d in C["dimensions"].items())
    products = ", ".join(f"{p['name']} ({p['therapeutic_area']})" for p in C["products"].values())
    markets = ", ".join(f"{k}={m['name']}" for k, m in C["markets"].items())
    return (f"MEASURES (canonical KPIs)\n{measures}\n\nBREAKDOWNS\n{dims}\n\nPRODUCTS\n{products}\n\n"
            f"MARKETS\n{markets}\nREGIONS: EMEA, North America, Asia Pacific, Latin America\nGRAIN: month")
