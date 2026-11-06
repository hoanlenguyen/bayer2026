"""Builds the Estate Explorer graph ("molecular view") from the live catalog.

Entities: reports (assets), semantic models, KPIs (approved ones and their
local, duplicate or conflicting variants), owners and workspaces.
Edges: model supplies report, report uses KPI, variant duplicates or conflicts
with the approved KPI, owner owns, lineage (derived from), model in workspace.
Status, trust and flags reuse the governance scoring in decision.py, so the
graph and the decisions always agree.
"""
from __future__ import annotations

import re
from typing import Any

from . import catalog as cat
from .decision import FRESHNESS_BY_REFRESH, THRESHOLDS, governance


def _pid(name: str) -> str:
    return "p_" + re.sub(r"[^a-z0-9]+", "_", (name or "unknown").lower()).strip("_")


def _initials(name: str) -> str:
    parts = [p for p in re.split(r"[\s.()]+", name or "") if p and p[0].isalpha()]
    return "".join(p[0] for p in parts[:2]).upper() or "?"


def _asset_status(a: dict[str, Any]) -> str:
    if a.get("conflicts"):
        return "conflict"
    if a.get("owner_status") != "active":
        return "orphaned"
    if a.get("lifecycle") in ("candidate_retire", "legacy"):
        return "stale"
    return "certified" if a.get("endorsement") in ("certified", "promoted") else "uncertified"


def build_graph() -> dict[str, Any]:
    C = cat.CATALOG
    entities: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, str]] = []
    kpi_index: dict[str, tuple[str, dict[str, Any] | None]] = {}  # kpi_id -> (measure_id, variant or None)

    def edge(s: str | None, rel: str, t: str | None) -> None:
        if s and t and s in entities and t in entities:
            edges.append({"s": s, "rel": rel, "t": t})

    # Workspaces
    for wid, w in C["workspaces"].items():
        entities[wid] = {"id": wid, "uid": wid, "type": "domain", "name": w["workspace_name"], "status": "active", "trust": 1.0,
                         "updated": "", "summary": f"{w['platform']} workspace, {w['environment']}, {w['governance_mode'].replace('_', ' ')}.",
                         "props": {"Scope": w["scope"], "Environment": w["environment"], "Governance": w["governance_mode"].replace("_", " "),
                                   "Classification": w["classification"]}, "flags": []}

    # Owners
    for oid, o in C["owners"].items():
        entities[oid] = {"id": oid, "uid": oid, "type": "person", "name": o["owner_name"], "initials": _initials(o["owner_name"]),
                         "status": "active" if o["status"] == "active" else "left", "trust": 1.0 if o["status"] == "active" else 0.0,
                         "updated": "", "summary": f"{o['role']}, {o['scope']}.", "props": {"Role": o["role"], "Scope": o["scope"], "Status": o["status"]},
                         "flags": [] if o["status"] == "active" else [{"sev": "warn", "title": "Inactive owner",
                                                                       "text": "Reports still list this person as owner (RULE-003)."}]}

    # KPIs: approved ones and their variants
    for mid, m in C["measures"].items():
        if m["kpi_id"]:
            kpi_index[m["kpi_id"]] = (mid, None)
            entities[m["kpi_id"]] = {
                "id": m["kpi_id"], "uid": m["kpi_id"], "type": "metric", "name": m["name"], "status": "certified", "trust": 1.0,
                "updated": "", "summary": m["definition"],
                "props": {"KPI": m["kpi_id"], "Domain": m["domain"], "Unit": m["unit"], "Frequency": "monthly",
                          "Variants in use": str(len(m["variants"])), "Owner": m.get("owner") or "-"},
                "flags": [{"sev": "warn", "title": f"{len(m['variants'])} unapproved variants",
                           "text": ", ".join(v["name"] for v in m["variants"])}] if m["variants"] else [],
            }
        for v in m["variants"]:
            kpi_index[v["kpi_id"]] = (mid, v)
            conflict = v["status"] == "definition_conflict"
            entities[v["kpi_id"]] = {
                "id": v["kpi_id"], "uid": v["kpi_id"], "type": "metric", "name": v["name"],
                "status": "conflict" if conflict else "draft", "trust": 0.2 if conflict else 0.5, "updated": "",
                "summary": f"{v['status'].replace('_', ' ').capitalize()} of {m['name']} ({v['approval']}). Use {m['kpi_id']} instead.",
                "props": {"KPI": v["kpi_id"], "Variant of": m["name"], "Definition status": v["status"].replace("_", " "),
                          "Approval": v["approval"]},
                "flags": [{"sev": "bad" if conflict else "warn",
                           "title": "Conflicting definition" if conflict else "Unapproved variant",
                           "text": f"Reports using it may show different numbers than {m['kpi_id']} (RULE-002)."}],
            }

    # Semantic models
    for sid, s in C["models"].items():
        flags = [{"sev": "bad" if i["severity"] == "high" else "warn", "title": f"{i['field'].replace('_', ' ')}: {i['value']}",
                  "text": i["impact"]} for i in s["dq_issues"]]
        entities[sid] = {
            "id": sid, "uid": sid, "type": "dataset", "name": s["name"],
            "status": "stale" if s["refresh_status"] == "failed" else ("certified" if s["endorsement"] != "none" else "uncertified"),
            "trust": round(0.5 * FRESHNESS_BY_REFRESH.get(s["refresh_status"], 0.5)
                           + 0.3 * {"good": 1, "partial": 0.5}.get(s["ai_readiness"], 0)
                           + 0.2 * (s["endorsement"] != "none"), 2),
            "updated": "", "summary": f"{s['model_type']} in {s['workspace']}. {len(s['assets'])} reports depend on it.",
            "props": {"Model": sid, "Type": s["model_type"], "Workspace": s["workspace"], "Product scope": s["product_scope"],
                      "Region scope": s["region_scope"], "Endorsement": s["endorsement"],
                      "Refresh": f"{s['refresh_frequency']}, {s['refresh_status']}", "AI readiness": f"{s['ai_readiness']} ({s['ai_issue_pattern'].replace('_', ' ')})",
                      "Tables / measures": f"{s['table_count']} / {s['measure_count']}", "Owner": s.get("owner") or "-"},
            "flags": flags,
        }

    # Reports
    for a in C["assets"]:
        gov, checks = governance(a)
        flags = [{"sev": "bad", "title": "Conflicting KPI definition", "text": why} for why in a["conflicts"].values()]
        flags += [{"sev": "warn", "title": "Unapproved KPI variant", "text": why} for why in a["variants"].values()]
        flags += [{"sev": "bad" if s_["severity"] == "high" else "warn", "title": s_["code"].replace("_", " ").capitalize(),
                   "text": f"{s_['status']}, detected by {s_['detected_by'].replace('_', ' ')}."}
                  for s_ in a["signals"] if s_["status"] != "resolved"]
        mig = a.get("migration") or {}
        low_use = a["views_90d"] < THRESHOLDS["low_usage_views_90d"]
        entity = {
            "id": a["id"], "uid": a["id"], "type": "dashboard", "name": a["name"], "status": _asset_status(a), "trust": gov,
            "updated": a.get("last_modified") or "", "views": a["views_90d"],
            "summary": f"{a['platform']} {a['asset_type'].lower()} in {a.get('workspace')}, scope {a['product_scope']} / {a['market_scope']}.",
            "props": {"Asset": a["id"], "Type": f"{a['platform']} {a['asset_type']}", "Product scope": a["product_scope"],
                      "Market scope": a["market_scope"], "Views (90 days)": f"{a['views_90d']:,}", "Users (90 days)": f"{a['users_90d']:,}",
                      "Lifecycle": a["lifecycle"].replace("_", " "), "Endorsement": a["endorsement"], "Delivery": (a.get("delivery_model") or "").replace("_", " "),
                      "Semantic model": a.get("model_id") or "-", "Owner": f"{a['owner']} ({a['owner_status']})",
                      "Governance score": f"{gov:.2f}", **({"Migration path": f"{mig['recommended_path_candidate']} → {mig['candidate_target_model_id']}"} if mig else {})},
            "flags": flags,
        }
        if a["lifecycle"] == "candidate_retire" or (low_use and a["lifecycle"] != "active") or mig.get("recommended_path_candidate") == "RETIRE":
            entity["action"] = f"Retire {a['name']}"
        entities[a["id"]] = entity

    # People that exist only as names (new reports created in this session)
    for a in C["assets"]:
        if not a.get("owner_id") and a.get("owner"):
            pid = _pid(a["owner"])
            entities.setdefault(pid, {"id": pid, "uid": pid, "type": "person", "name": a["owner"], "initials": _initials(a["owner"]),
                                      "status": "active", "trust": 1.0, "updated": "", "summary": "Owner of reports created here.",
                                      "props": {"Role": "Report owner"}, "flags": []})

    # Edges
    for mid, m in C["measures"].items():
        for v in m["variants"]:
            edge(v["kpi_id"], "conflicts_with" if v["status"] == "definition_conflict" else "duplicate_of", m["kpi_id"])
        edge(m.get("owner_id"), "owns", m["kpi_id"])
    for sid, s in C["models"].items():
        edge(s["owner_id"], "owns", sid)
        edge(sid, "belongs_to", s["workspace_id"])
    for a in C["assets"]:
        edge(a.get("model_id"), "sources", a["id"])
        edge(a.get("owner_id") or _pid(a.get("owner", "")), "owns", a["id"])
        for k in a.get("kpis", []):
            edge(a["id"], "uses", k)
    for e in C["lineage"]:
        if e["type"] in ("ASSET_TO_ASSET", "MODEL_TO_MODEL"):
            edge(e["target"], "derived_from", e["source"])

    # Land on the approved Net Sales KPI: its variants and the reports using them show the sprawl at a glance.
    focus = C["measures"].get("net_sales", {}).get("kpi_id") or C["assets"][0]["id"]
    return {"entities": list(entities.values()), "edges": edges, "focus": focus,
            "counts": {"reports": len(C["assets"]), "measures": len(C["measures"]), "models": len(C["models"])}}
