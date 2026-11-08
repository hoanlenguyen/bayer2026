"""BI Portfolio: one tracking table for the person accountable for the reporting estate.

A read projection keyed by asset ID over three origins:
- workbook assets (Analytics_Assets and the sheets around them), month precision for usage;
- app-defined employee reports (briefing_definitions.EMPLOYEE_REPORTS);
- dashboards employees built in Ask (the `dashboards` store, read through a metadata projection).

The employee artifacts stay authoritative. This module only reads them and adds governance records beside them:
app-open events, ownership overlays and owner-review cases. Imported facts are never overwritten.

Actors: there is no sign-in yet. Mutations take a server-configured demo identity from the X-AnalytIQ-Actor header,
resolved and permission-checked here. The client cannot grant itself a role it is not configured for.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from functools import lru_cache
from itertools import combinations
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from . import catalog, datapack
from .briefing_definitions import EMPLOYEE_REPORTS, VIEWS
from .decision import products_disagree
from .report_register import _consumers, published_titles

router = APIRouter()

OPENS, OWNERS, CASES, CASE_EVENTS = "bi_open_events", "bi_owner_events", "bi_cases", "bi_case_events"
PAIR_RULE = {"id": "PAIR-1", "version": 1,
             "text": "Same declared product and market, and at least two shared KPI IDs that are canonical and approved. "
                     "A team policy for this first version: it marks overlap worth asking the owners about, not a duplicate."}
SCOPE_RULE = {"id": "SCOPE-1", "version": 1,
              "text": "Compare the report's declared product and market with its bound model. A country is mapped to its region "
                      "through the Markets sheet. All Pharma and Global on the model side are compatible broad scopes."}
DEFINITION_RULE = {"id": "DEF-1", "version": 1,
                   "text": "The report binds a KPI the catalog marks as a definition conflict. Duplicate candidates and local "
                           "variants are shown as weaker context. Numbers are not compared: no formulas or results exist to check."}
VARIANTS = {"definition_conflict": "Definition conflict", "duplicate_candidate": "Duplicate candidate", "local_variant": "Local variant"}
ISSUES = {
    "needs_owner": "Needs an owner",
    "refresh": "Refresh issue",
    "definition": "Definition conflict",
    "scope": "Scope mismatch",
    "consolidation": "Consolidation candidate",
    "retirement": "Marked for retirement",
    "chronology": "Source date anomaly",
    "signal": "Open source signal",
}
ORIGINS = {"workbook": "Workbook asset", "app_report": "App employee report", "generated": "Employee-built dashboard"}

# --------------------------------------------------------------------------- identities (demo, server-configured)

STEWARD = {"id": "DEMO-BI-STEWARD", "name": "BI department head (demo)", "role": "bi_steward"}
EMPLOYEE = {"id": "DEMO-EMPLOYEE", "name": "Demo employee", "role": "employee"}
REVIEWER = {"id": "DEMO-GOV-REVIEWER", "name": "Governance reviewer (demo)", "role": "governance_reviewer"}
AUDITOR = {"id": "DEMO-AUDITOR", "name": "Read-only auditor (demo)", "role": "auditor"}
DEMO_PERSONAS = {p["id"]: p for p in (STEWARD, EMPLOYEE, REVIEWER, AUDITOR)}
ACTOR_HEADER = "x-analytiq-actor"


def _rows(sheet: str):
    return enumerate(catalog.SHEETS[sheet.lower()], start=2)


def people() -> dict[str, dict]:
    return {r["owner_id"]: {"id": r["owner_id"], "name": r["owner_name"], "role": r["role"], "status": r["status"],
                            "evidence": f"Owners row {i}"} for i, r in _rows("Owners")}


def resolve_actor(request: Request | None) -> dict | None:
    """The demo identity this request acts as, or None for a read-only viewer. Unknown or inactive IDs grant nothing."""
    if request is None:
        return None
    actor_id = (request.headers.get(ACTOR_HEADER) or "").strip()
    if not actor_id:
        return None
    if actor_id in DEMO_PERSONAS:
        return dict(DEMO_PERSONAS[actor_id])
    person = people().get(actor_id)
    if person and person["status"] == "active":
        return {"id": person["id"], "name": person["name"], "role": "owner"}
    raise HTTPException(403, "This demo identity is not configured for this installation.")


def creator_for_build(request: Request | None) -> dict:
    """Who built a dashboard: the resolved demo identity, else the labelled demo employee. Never fails a build."""
    try:
        actor = resolve_actor(request)
    except HTTPException:
        actor = None
    actor = actor or EMPLOYEE
    return {"id": actor["id"], "name": actor["name"], "source": "Server-configured demo identity (no sign-in yet)",
            "at": _now()}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@router.get("/api/bi-identity")
async def identities() -> dict:
    owners = sorted((p for p in people().values() if p["status"] == "active"), key=lambda p: (p["name"], p["id"]))
    return {"mode": "demo", "header": "X-AnalytIQ-Actor",
            "note": "Demo identities configured on the server. This is not a sign-in: production needs the company's identity provider.",
            "personas": [{**STEWARD, "label": "BI department head (demo steward)"},
                         {**EMPLOYEE, "label": "Demo employee"},
                         {**REVIEWER, "label": "Governance reviewer (demo)"},
                         {**AUDITOR, "label": "Read-only auditor (demo)"},
                         *({"id": p["id"], "name": p["name"], "role": "owner", "label": f"{p['name']} · {p['id']} (report owner)"}
                           for p in owners)]}


# --------------------------------------------------------------------------- workbook projection (cached per snapshot)

@lru_cache(maxsize=1)
def _workbook_sha(path: str) -> str:
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return "unknown"


def _market_region(market: str, markets: dict) -> str | None:
    if market == "Global":
        return "Global"
    return (markets.get(market) or {}).get("region")


def scope_comparison(product: str, market: str, model: dict, markets: dict) -> dict:
    """SCOPE-1: product and geography of a report against its bound model, as separate outcomes."""
    mp, mr = model.get("product_scope"), model.get("region_scope")
    if product == mp:
        p = "match"
    elif mp == "All Pharma":
        p = "compatible_broad"
    elif product == "All Pharma" or products_disagree(product, mp or ""):
        p = "mismatch"
    else:
        p = "compatible_broad"
    region = _market_region(market, markets)
    if region is None or mr is None:
        g = "insufficient_evidence"
    elif mr == "Global":
        g = "match" if market == "Global" else "compatible_broad"
    elif market == "Global":
        g = "mismatch"
    else:
        g = "match" if region == mr else "mismatch"
    return {"product": p, "geography": g, "report_region": region, "model_product": mp, "model_region": mr,
            "mismatch": "mismatch" in (p, g), "rule": SCOPE_RULE}


@lru_cache(maxsize=2)
def _projection(snapshot_key: int) -> dict[str, Any]:
    """Everything derived from the workbook, computed once per loaded snapshot."""
    owners = people()
    markets = {r["market_id"]: {**r, "row": i} for i, r in _rows("Markets")}
    products = {r["product_id"]: r for _, r in _rows("Products")}
    models = {r["model_id"]: {**r, "row": i} for i, r in _rows("Semantic_Models")}
    workspaces = {r["workspace_id"]: r for _, r in _rows("Workspaces")}
    kpis = {r["kpi_id"]: {**r, "row": i} for i, r in _rows("KPI_Catalog")}
    approved = {k for k, r in kpis.items() if r["definition_status"] == "canonical" and r["approval_status"] == "approved"}
    bindings: dict[str, list[dict]] = defaultdict(list)
    for i, r in _rows("Asset_KPI_Map"):
        bindings[r["asset_id"]].append({"kpi_id": r["kpi_id"], "usage_role": r["usage_role"], "row": i})
    usage: dict[str, list[dict]] = defaultdict(list)
    for i, r in _rows("Asset_Usage"):
        usage[r["asset_id"]].append({**r, "row": i, "month": r["month"][:7]})
    signals: dict[str, list[dict]] = defaultdict(list)
    for i, r in _rows("Governance_Signals"):
        signals[r["asset_id"]].append({**r, "row": i})
    quality: dict[str, list[dict]] = defaultdict(list)
    for i, r in _rows("Data_Quality"):
        quality[r["record_id"]].append({**r, "row": i})
    upstream: dict[str, list[dict]] = defaultdict(list)
    downstream: dict[str, list[dict]] = defaultdict(list)
    for i, r in _rows("Lineage_Edges"):
        edge = {**r, "row": i}
        upstream[r["target_id"]].append(edge)
        downstream[r["source_id"]].append(edge)
    months = sorted({u["month"] for rows in usage.values() for u in rows})

    assets: dict[str, dict] = {}
    for i, r in _rows("Analytics_Assets"):
        aid = r["asset_id"]
        model = models.get(r["model_id"], {})
        owner = owners.get(r["owner_id"])
        rows = sorted(usage[aid], key=lambda u: u["month"])
        viewed = [u for u in rows if u["views"] > 0]
        anything = [u for u in rows if any(u[k] for k in ("views", "unique_users", "exports", "subscriptions"))]
        kpi_ids = sorted({b["kpi_id"] for b in bindings[aid]})
        variants = [k for k in kpi_ids if k in kpis and kpis[k]["definition_status"] == "definition_conflict"]
        nonstandard = [k for k in kpi_ids if k in kpis and kpis[k]["definition_status"] in VARIANTS and k not in variants]
        scope = scope_comparison(r["product_scope"], r["market_scope"], model, markets)
        issues = []
        if not owner or owner["status"] != "active":
            issues.append("needs_owner")
        if model.get("refresh_status") in ("warning", "failed"):
            issues.append("refresh")
        if variants:
            issues.append("definition")
        if scope["mismatch"]:
            issues.append("scope")
        if r["lifecycle_status"] == "candidate_retire":
            issues.append("retirement")
        if r["created_date"] and r["last_modified"] and r["last_modified"] < r["created_date"]:
            issues.append("chronology")
        if any(sg["status"] == "open" for sg in signals[aid]):
            issues.append("signal")  # imported Governance_Signals, kept apart from AnalytIQ's own checks
        assets[aid] = {
            "id": aid, "original_title": r["asset_name"], "origin": "workbook", "type": r["asset_type"],
            "platform": r["platform"], "workspace": {"id": r["workspace_id"], "name": (workspaces.get(r["workspace_id"]) or {}).get("workspace_name")},
            "product": r["product_scope"], "market": r["market_scope"],
            "market_name": "Global" if r["market_scope"] == "Global" else (markets.get(r["market_scope"]) or {}).get("market_name"),
            "imported_owner": owner, "imported_owner_id": r["owner_id"],
            "creator": {"name": None, "source": "Creator unrecorded: the workbook has no creator column", "recorded": False},
            "created": {"value": r["created_date"], "precision": "day", "source": f"Analytics_Assets row {i} · created_date"},
            "modified": {"value": r["last_modified"], "precision": "day", "source": f"Analytics_Assets row {i} · last_modified"},
            "lifecycle": r["lifecycle_status"], "endorsement": r["endorsement"], "audience": r["estimated_audience"],
            "classification": r["classification"], "delivery_model": r["delivery_model"], "row": i,
            "model": {"id": r["model_id"], "name": model.get("model_name"), "product": model.get("product_scope"),
                      "region": model.get("region_scope"), "refresh_status": model.get("refresh_status"),
                      "cadence": model.get("refresh_frequency"), "endorsement": model.get("endorsement"),
                      "owner_id": model.get("owner_id"), "row": model.get("row")},
            "refresh": {"status": model.get("refresh_status") or "unknown", "cadence": model.get("refresh_frequency"),
                        "last_success": None, "overdue": "unknown",
                        "note": "The workbook records refresh status and cadence only, not refresh timestamps."},
            "usage": {"window": [rows[0]["month"], rows[-1]["month"]] if rows else [], "months": len(rows),
                      "views": sum(u["views"] for u in rows), "exports": sum(u["exports"] for u in rows),
                      "subscriptions": sum(u["subscriptions"] for u in rows),
                      "unique_users_monthly_sum": sum(u["unique_users"] for u in rows),
                      "last_view_month": viewed[-1]["month"] if viewed else None,
                      "last_view_row": viewed[-1]["row"] if viewed else None,
                      "last_view_count": viewed[-1]["views"] if viewed else None,
                      "last_activity_month": anything[-1]["month"] if anything else None,
                      "source": "Asset_Usage (imported monthly activity, not opens inside AnalytIQ)"},
            "data_through": None,
            "kpi_ids": kpi_ids, "variant_kpi_ids": variants, "nonstandard_kpi_ids": nonstandard, "scope": scope, "issues": issues,
            "signals_open": sum(1 for s in signals[aid] if s["status"] == "open"),
        }
    # PAIR-1: inverted index by declared scope, then exact approved KPI intersections. Each unordered pair once.
    by_scope: dict[tuple, list[str]] = defaultdict(list)
    for aid, a in assets.items():
        by_scope[(a["product"], a["market"])].append(aid)
    pairs: dict[str, dict] = {}
    for scope_key, ids in by_scope.items():
        for a, b in combinations(sorted(ids), 2):
            shared = sorted(set(assets[a]["kpi_ids"]) & set(assets[b]["kpi_ids"]) & approved)
            if len(shared) >= 2:
                key = pair_key(a, b)
                pairs[key] = {"id": key, "assets": [a, b], "scope": {"product": scope_key[0], "market": scope_key[1]},
                              "shared_kpi_ids": shared, "rule": PAIR_RULE}
    for p in pairs.values():
        for aid in p["assets"]:
            assets[aid].setdefault("pair_ids", []).append(p["id"])
            if "consolidation" not in assets[aid]["issues"]:
                assets[aid]["issues"].append("consolidation")
    return {"assets": assets, "pairs": pairs, "kpis": kpis, "approved": approved, "models": models, "markets": markets,
            "products": products, "bindings": bindings, "usage": usage, "signals": signals, "quality": quality,
            "upstream": upstream, "downstream": downstream, "months": months, "owners": owners}


def projection() -> dict[str, Any]:
    return _projection(id(catalog.SHEETS.get("analytics_assets")))


def pair_key(a: str, b: str) -> str:
    x, y = sorted((a, b))
    return f"{x}~{y}"


# --------------------------------------------------------------------------- store helpers (memory and MongoDB)

async def _find(store, kind: str, query: dict | None = None, sort: str | None = None) -> list[dict]:
    query = query or {}
    if store.name == "mongodb":
        cursor = store.db[kind].find(query)
        if sort:
            cursor = cursor.sort(sort, 1)
        return [r async for r in cursor]
    rows = [r for r in store.artifacts.setdefault(kind, {}).values() if all(r.get(k) == v for k, v in query.items())]
    return sorted(rows, key=lambda r: r.get(sort) or "") if sort else rows


async def _insert_once(store, kind: str, doc: dict) -> tuple[dict, bool]:
    """Insert unless the _id exists. Returns (stored document, inserted). Atomic in MongoDB through the unique _id."""
    if store.name == "mongodb":
        from pymongo.errors import DuplicateKeyError
        try:
            await store.db[kind].insert_one(dict(doc))
            return doc, True
        except DuplicateKeyError:
            return await store.db[kind].find_one({"_id": doc["_id"]}), False
    table = store.artifacts.setdefault(kind, {})
    if doc["_id"] in table:
        return dict(table[doc["_id"]]), False
    table[doc["_id"]] = dict(doc)
    return doc, True


async def _set(store, kind: str, doc_id: str, fields: dict) -> None:
    if store.name == "mongodb":
        await store.db[kind].update_one({"_id": doc_id}, {"$set": fields})
    else:
        store.artifacts.setdefault(kind, {}).setdefault(doc_id, {"_id": doc_id}).update(fields)


async def _dashboards(store) -> list[dict]:
    """Metadata of saved dashboards, without their source rows or chart points."""
    fields = ("id", "title", "created_at", "created_by", "period", "decision_goal", "scope", "columns", "conversation_id", "run_id",
              "requested_measures", "omitted_measures", "source", "dimensions", "requirements")
    if store.name == "mongodb":
        projection_ = ({k: 1 for k in fields if k not in ("columns", "requirements")}
                       | {"_id": 0, "columns.kpi_id": 1, "columns.name": 1, "columns.id": 1,
                          "requirements.products": 1, "requirements.markets": 1, "requirements.measures": 1, "requirements.dimensions": 1})
        return [d async for d in store.db["dashboards"].find({}, projection_)]
    return [{k: d.get(k) for k in fields} for d in store.artifacts.get("dashboards", {}).values()]


async def _open_stats(store) -> dict[str, dict]:
    stats: dict[str, dict] = {}
    if store.name == "mongodb":
        pipeline = [{"$group": {"_id": "$asset_id", "count": {"$sum": 1}, "last_at": {"$max": "$at"}}}]
        cursor = await store.db[OPENS].aggregate(pipeline)
        groups = [g async for g in cursor] if hasattr(cursor, "__aiter__") else list(cursor)
        for g in groups:
            stats[g["_id"]] = {"count": g["count"], "last_at": g["last_at"]}
        return stats
    for e in store.artifacts.get(OPENS, {}).values():
        s = stats.setdefault(e["asset_id"], {"count": 0, "last_at": None})
        s["count"] += 1
        s["last_at"] = max(filter(None, [s["last_at"], e["at"]]))
    return stats


async def _owner_overlays(store) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for e in await _find(store, OWNERS, sort="_id"):
        out[e["asset_id"]].append(e)
    for events in out.values():
        events.sort(key=lambda e: e["seq"])
    return out


async def _active_cases(store) -> dict[str, dict]:
    """Open cases by pair key."""
    return {c["pair_key"]: c for c in await _find(store, CASES) if c.get("status") != "closed"}


# --------------------------------------------------------------------------- the inventory

def _app_reports(proj: dict) -> dict[str, dict]:
    kpis, owners, markets = proj["kpis"], proj["owners"], proj["markets"]
    out = {}
    for aid, title, kpi_id, product in EMPLOYEE_REPORTS:
        kpi = kpis[kpi_id]
        steward = owners.get(kpi["owner_id"])
        out[aid] = {
            "id": aid, "original_title": title, "origin": "app_report", "type": "Employee report", "platform": "AnalytIQ",
            "workspace": {"id": None, "name": "Team briefings"}, "product": product, "market": "DE",
            "market_name": markets.get("DE", {}).get("market_name", "Germany"),
            "imported_owner": steward, "imported_owner_id": kpi["owner_id"],
            "owner_evidence": f"Designated steward of {kpi_id} (KPI_Catalog row {kpi['row']})",
            "creator": {"name": None, "source": "Creator unrecorded: defined with the application", "recorded": False},
            "created": {"value": None, "precision": None, "source": "App definition (no creation date recorded)"},
            "modified": {"value": None, "precision": None, "source": "See the report register for published revisions"},
            "lifecycle": "active", "endorsement": None, "model": None, "kpi_ids": [kpi_id], "variant_kpi_ids": [], "nonstandard_kpi_ids": [],
            "refresh": {"status": "not_applicable", "cadence": None, "last_success": None, "overdue": "unknown",
                        "note": "Reads the synthetic workbook directly; no semantic model refresh."},
            "usage": {"window": [], "months": 0, "views": None, "last_view_month": None,
                      "source": "No imported usage: AnalytIQ opens are counted separately"},
            "data_through": proj["months"][-1] if proj["months"] else None,
            "scope": None, "issues": [] if steward and steward["status"] == "active" else ["needs_owner"], "signals_open": 0,
        }
    return out


def _generated(d: dict, proj: dict) -> dict:
    created_by = d.get("created_by")
    scope = d.get("scope") or {}
    kpi_ids = sorted({c.get("kpi_id") for c in d.get("columns") or [] if c.get("kpi_id")})
    prods, mkts = scope.get("products") or [], scope.get("markets") or []
    return {
        "id": d["id"], "original_title": d.get("title") or d["id"], "origin": "generated", "type": "Dashboard", "platform": "AnalytIQ",
        "workspace": {"id": None, "name": "Built in Ask"},
        "product": prods[0] if len(prods) == 1 else (f"{len(prods)} products" if prods else None),
        "market": mkts[0] if len(mkts) == 1 else (f"{len(mkts)} markets" if mkts else None), "market_name": None,
        "imported_owner": None, "imported_owner_id": None, "owner_evidence": "Unassigned until a BI steward assigns an owner",
        "creator": ({"name": created_by["name"], "id": created_by.get("id"), "source": created_by.get("source"), "recorded": True}
                    if created_by else {"name": None, "source": "Creator unrecorded: built before attribution was captured", "recorded": False}),
        "created": {"value": d.get("created_at"), "precision": "timestamp", "source": "Saved dashboard record"},
        "modified": {"value": None, "precision": None, "source": "Saved dashboards are immutable snapshots"},
        "lifecycle": "active", "endorsement": None, "model": None, "kpi_ids": kpi_ids, "variant_kpi_ids": [], "nonstandard_kpi_ids": [],
        "refresh": {"status": "snapshot", "cadence": None, "last_success": None, "overdue": "not_applicable",
                    "note": "An approved snapshot of workbook rows. It shows historical data on purpose."},
        "usage": {"window": [], "months": 0, "views": None, "last_view_month": None,
                  "source": "No imported usage: only opens inside AnalytIQ"},
        "data_through": ((d.get("period") or {}).get("end") or "")[:7] or None,
        "scope": None, "issues": ["needs_owner"], "signals_open": 0, "decision_goal": d.get("decision_goal"),
        "conversation_id": d.get("conversation_id"), "run_id": d.get("run_id"), "source_table": d.get("source"),
    }


async def inventory(store) -> tuple[list[dict], dict]:
    proj = projection()
    records = {**{k: dict(v) for k, v in proj["assets"].items()}, **_app_reports(proj)}
    for d in await _dashboards(store):
        if d.get("id") and d["id"] not in records:
            records[d["id"]] = _generated(d, proj)
    aliases = await published_titles(store)
    opens = await _open_stats(store)
    overlays = await _owner_overlays(store)
    cases = await _active_cases(store)
    teams = await _consumers(store)
    owners = proj["owners"]
    for aid, r in records.items():
        r["title"] = aliases.get(aid, r["original_title"])
        r["alias"] = aid in aliases
        last = overlays[aid][-1] if overlays.get(aid) else None
        if last:
            person = owners.get(last["owner_id"])
            r["owner"] = {**(person or {"id": last["owner_id"], "name": last["owner_name"]}), "via": "assignment",
                          "assigned_at": last["at"], "assigned_by": last["actor_name"], "reason": last["reason"]}
        elif r["imported_owner"]:
            r["owner"] = {**r["imported_owner"], "via": "imported"}
        else:
            r["owner"] = None
        state = "absent" if not r["owner"] else ("active" if r["owner"].get("status") == "active" else "inactive")
        r["owner_state"] = state
        if state == "active" and "needs_owner" in r["issues"]:
            r["issues"] = [i for i in r["issues"] if i != "needs_owner"]
        elif state != "active" and "needs_owner" not in r["issues"]:
            r["issues"] = ["needs_owner", *r["issues"]]
        r["app_opens"] = opens.get(aid, {"count": 0, "last_at": None})
        r["teams"] = teams.get(aid, []) if r["origin"] == "app_report" else []
        r["case_ids"] = sorted(c["_id"] for k, c in cases.items() if aid in c["assets"])
        r["finding"] = _finding(r, proj)
    meta = {"pairs": proj["pairs"], "months": proj["months"]}
    return list(records.values()), meta


def _finding(r: dict, proj: dict) -> str:
    """One plain sentence on why this row needs attention, most actionable first."""
    if r.get("case_ids"):
        return "Owner review in progress."
    if "consolidation" in r["issues"]:
        pair = proj["pairs"][r["pair_ids"][0]]
        other = next(a for a in pair["assets"] if a != r["id"])
        return f"{len(pair['shared_kpi_ids'])} approved KPIs also appear on {other} ({pair['scope']['market']}). Ask both owners."
    if r["owner_state"] == "inactive":
        return f"Owner {r['owner']['id']} is inactive. Assign an active owner."
    if r["owner_state"] == "absent":
        return "Unassigned. A BI steward needs to assign an owner." if r["origin"] == "generated" else "No owner on record."
    if "scope" in r["issues"]:
        s = r["scope"]
        parts = [f"product {r['product']} vs {s['model_product']}" if s["product"] == "mismatch" else None,
                 f"market {r['market']} vs model region {s['model_region']}" if s["geography"] == "mismatch" else None]
        return "Report scope differs from its model: " + "; ".join(p for p in parts if p) + "."
    if "definition" in r["issues"]:
        n = len(r["variant_kpi_ids"])
        return f"Uses {n} conflicting KPI definition{'s' if n > 1 else ''}. Needs a KPI steward."
    if "refresh" in r["issues"]:
        return f"Model {r['model']['id']} refresh is {r['refresh']['status']}."
    if "retirement" in r["issues"]:
        return "Marked for retirement in the workbook (not approved or executed)."
    if "chronology" in r["issues"]:
        return "Last modified before it was created in the source. Dates kept as recorded."
    if "signal" in r["issues"]:
        open_ = [sg for sg in proj["signals"].get(r["id"], []) if sg["status"] == "open"]
        first = sorted(open_, key=lambda sg: ({"high": 0, "medium": 1}.get(sg["severity"], 2), sg["signal_id"]))[0]
        more = f" and {len(open_) - 1} more" if len(open_) > 1 else ""
        return f"Open source signal {first['signal_id']}: {first['signal_code'].replace('_', ' ').lower()} ({first['severity']}){more}."
    if r["origin"] == "generated":
        return "Built in Ask. Snapshot of workbook rows."
    return "No open finding."


# --------------------------------------------------------------------------- list

SORTS = {
    "title": lambda r: (r["title"] or "").casefold(),
    "owner": lambda r: (r["owner"] or {}).get("name", "").casefold() or None,
    "last_use": lambda r: r["usage"].get("last_view_month"),
    "opens": lambda r: r["app_opens"]["last_at"],
    "created": lambda r: r["created"]["value"],
    "issues": lambda r: len(r["issues"]) or None,
    "id": lambda r: r["id"],
}


def _matches(r: dict, q: str, origin: str | None, platform: str | None, issue: str | None, lifecycle: str | None,
             owner_state: str | None, product: str | None, market: str | None) -> bool:
    if origin and r["origin"] != origin:
        return False
    if platform and r["platform"] != platform:
        return False
    if issue and issue not in r["issues"]:
        return False
    if lifecycle and r["lifecycle"] != lifecycle:
        return False
    if owner_state and r["owner_state"] != owner_state:
        return False
    if product and r["product"] != product:
        return False
    if market and market not in (r["market"], r.get("market_name")):
        return False
    if q:
        hay = " ".join(str(x) for x in (r["id"], r["title"], r["original_title"], (r["owner"] or {}).get("name"),
                                       (r["owner"] or {}).get("id"), r["product"], r["market"], r.get("market_name"),
                                       r["platform"], (r.get("model") or {}).get("id"))).casefold()
        return all(word in hay for word in q.casefold().split())
    return True


def _row(r: dict) -> dict:
    keep = ("id", "title", "original_title", "alias", "origin", "type", "platform", "product", "market", "market_name",
            "owner", "owner_state", "creator", "created", "lifecycle", "issues", "finding", "app_opens", "case_ids", "data_through")
    out = {k: r.get(k) for k in keep}
    out["last_view_month"] = r["usage"].get("last_view_month")
    out["last_view_count"] = r["usage"].get("last_view_count")
    out["refresh"] = r["refresh"]["status"]
    out["model_id"] = (r.get("model") or {}).get("id")
    out["pair_ids"] = r.get("pair_ids", [])
    return out


@router.get("/api/bi-estate")
async def list_estate(request: Request, q: str = "", origin: str | None = None, platform: str | None = None,
                      issue: str | None = None, lifecycle: str | None = None, owner_state: str | None = None,
                      product: str | None = None, market: str | None = None,
                      sort: str = "issues", direction: Literal["asc", "desc"] = "desc",
                      page: int = Query(1, ge=1), size: int = Query(25, ge=1, le=100)) -> dict:
    store = request.app.state.pipeline.store
    records, meta = await inventory(store)
    if sort not in SORTS:
        raise HTTPException(422, f"Sort by one of: {', '.join(SORTS)}.")
    filtered = [r for r in records if _matches(r, q, origin, platform, issue, lifecycle, owner_state, product, market)]
    key = SORTS[sort]
    known = [r for r in filtered if key(r) is not None]
    unknown = sorted((r for r in filtered if key(r) is None), key=lambda r: r["id"])
    known.sort(key=lambda r: r["id"])  # stable tie-break by ID, then the chosen key
    known.sort(key=key, reverse=direction == "desc")
    ordered = known + unknown  # unknown values always sort last
    pairs_in_view = {p for r in filtered for p in r.get("pair_ids", [])}
    counts = {
        "needs_owner": {"assets": sum("needs_owner" in r["issues"] for r in records)},
        "refresh": {"assets": sum("refresh" in r["issues"] for r in records)},
        "definition": {"assets": sum("definition" in r["issues"] for r in records)},
        "scope": {"assets": sum("scope" in r["issues"] for r in records)},
        "consolidation": {"assets": sum("consolidation" in r["issues"] for r in records), "pairs": len(meta["pairs"])},
        "retirement": {"assets": sum("retirement" in r["issues"] for r in records)},
        "chronology": {"assets": sum("chronology" in r["issues"] for r in records)},
        "signal": {"assets": sum("signal" in r["issues"] for r in records)},
    }
    origins = Counter(r["origin"] for r in records)
    months = meta["months"]
    start = (page - 1) * size
    return {
        "rows": [_row(r) for r in ordered[start:start + size]], "total": len(records), "matching": len(filtered),
        "page": page, "size": size, "pages": max(1, -(-len(filtered) // size)), "sort": sort, "direction": direction,
        "counts": counts, "pairs_in_view": len(pairs_in_view), "issue_labels": ISSUES, "origin_labels": ORIGINS,
        # The newest dashboards built in Ask, whatever the sort: the default "most issues first" order puts them far down.
        "recent_from_ask": [_row(r) for r in sorted((r for r in records if r["origin"] == "generated"),
                                                    key=lambda r: r["created"]["value"] or "", reverse=True)[:3]],
        "facets": {"platform": sorted({r["platform"] for r in records}), "lifecycle": sorted({r["lifecycle"] for r in records}),
                   "product": sorted({r["product"] for r in records if r["product"]}),
                   "market": sorted({r["market"] for r in records if r["market"]})},
        "sources": {
            "origins": {k: origins.get(k, 0) for k in ORIGINS},
            "workbook": {"file": datapack.workbook_path().name, "sha256": _workbook_sha(str(datapack.workbook_path())),
                         "observation_window": [months[0], months[-1]] if months else []},
            "note": "All reporting assets visible to this installation: the imported workbook, the app's employee reports and "
                    "dashboards built in Ask. No Power BI or Tableau tenant is connected, so native opens are not recorded.",
            "store": store.name, "as_of": _now(),
        },
    }


# --------------------------------------------------------------------------- detail and pair

def _kpi(kid: str, proj: dict, role: str | None = None, row: int | None = None) -> dict:
    k = proj["kpis"].get(kid)
    if not k:
        return {"id": kid, "name": None, "known": False}
    steward = proj["owners"].get(k["owner_id"])
    return {"id": kid, "name": k["kpi_name"], "family": k["canonical_metric"], "unit": k["unit"], "domain": k["domain"],
            "definition_status": k["definition_status"], "approval_status": k["approval_status"],
            "approved_canonical": kid in proj["approved"], "description": k["description"], "steward": steward,
            "evidence": f"KPI_Catalog row {k['row']}", "binding": f"Asset_KPI_Map row {row}" if row else None,
            "usage_role": role, "known": True}


def _edge(e: dict, perspective: str, proj: dict) -> dict:
    other = e["source_id"] if perspective == "upstream" else e["target_id"]
    title = (proj["assets"].get(other) or {}).get("original_title") or (proj["models"].get(other) or {}).get("model_name")
    return {"id": other, "title": title, "edge_type": e["edge_type"], "relationship": e["relationship"],
            "evidence": f"Lineage_Edges row {e['row']}", "class": "source lineage"}


async def _events_for(store, kind: str, field: str, value: str) -> list[dict]:
    return await _find(store, kind, {field: value}, sort="_id")


async def asset_detail(store, asset_id: str) -> dict:
    records, meta = await inventory(store)
    r = next((x for x in records if x["id"] == asset_id), None)
    if not r:
        raise HTTPException(404, "No reporting asset has this ID.")
    proj = projection()
    d = dict(r)
    if r["origin"] == "workbook":
        rows = {b["kpi_id"]: b for b in proj["bindings"][asset_id]}
        d["kpis"] = [_kpi(k, proj, rows[k]["usage_role"], rows[k]["row"]) for k in r["kpi_ids"]]
        d["usage_series"] = [{"month": u["month"], "views": u["views"], "unique_users": u["unique_users"], "exports": u["exports"],
                              "subscriptions": u["subscriptions"], "row": u["row"]} for u in sorted(proj["usage"][asset_id], key=lambda u: u["month"])]
        d["upstream"] = [_edge(e, "upstream", proj) for e in proj["upstream"][asset_id]]
        d["downstream"] = [_edge(e, "downstream", proj) for e in proj["downstream"][asset_id]]
        siblings = [e["target_id"] for e in proj["downstream"].get(r["model"]["id"], []) if e["target_id"] != asset_id
                    and e["edge_type"] == "MODEL_TO_ASSET"]
        d["siblings_on_model"] = {"count": len(siblings), "ids": siblings[:12], "class": "derived: same model, not a dependency"}
        d["signals"] = [{"id": s["signal_id"], "code": s["signal_code"], "severity": s["severity"], "status": s["status"],
                         "detected_by": s["detected_by"], "evidence": f"Governance_Signals row {s['row']}"} for s in proj["signals"][asset_id]]
        d["quality"] = [{"id": q["issue_id"], "record": q["record_id"], "field": q["field"], "severity": q["severity"],
                         "impact": q["impact"], "evidence": f"Data_Quality row {q['row']}"}
                        for q in proj["quality"].get(r["model"]["id"], []) + proj["quality"].get(asset_id, [])]
        d["sources"] = [f"Analytics_Assets row {r['row']}", (r["imported_owner"] or {}).get("evidence"),
                        f"Semantic_Models row {r['model']['row']}"]
        d["downstream_coverage"] = "Only lineage recorded in the workbook. Consumers outside it are unknown."
    else:
        d["kpis"] = [_kpi(k, proj) for k in r["kpi_ids"]]
        d["usage_series"], d["upstream"], d["downstream"], d["signals"], d["quality"] = [], [], [], [], []
        d["siblings_on_model"] = None
        d["sources"] = [r.get("owner_evidence")]
        d["downstream_coverage"] = "Not tracked for app reports and built dashboards."
    d["pairs"] = [await pair_detail(store, *proj["pairs"][p]["assets"], records=records) for p in r.get("pair_ids", [])]
    d["opens"] = sorted(await _events_for(store, OPENS, "asset_id", asset_id), key=lambda e: e["at"], reverse=True)[:20]
    d["owner_history"] = await _events_for(store, OWNERS, "asset_id", asset_id)
    d["cases"] = [await case_view(store, c["_id"]) for c in await _find(store, CASES) if asset_id in c["assets"]]
    d["links"] = {"dashboard": f"/dashboards/{asset_id}" if r["origin"] == "generated" else None,
                  "register": f"/briefings?report={asset_id}" if r["origin"] in ("workbook", "app_report") else None,
                  "explorer": "/#explorer" if r["origin"] == "workbook" else None}
    return d


@router.get("/api/bi-estate/{asset_id}")
async def get_asset(asset_id: str, request: Request) -> dict:
    return await asset_detail(request.app.state.pipeline.store, asset_id)


def _side(r: dict, proj: dict) -> dict:
    return {"id": r["id"], "title": r["title"], "original_title": r["original_title"], "platform": r["platform"],
            "type": r["type"], "product": r["product"], "market": r["market"], "market_name": r.get("market_name"),
            "owner": r["owner"], "owner_state": r["owner_state"], "lifecycle": r["lifecycle"], "model": r.get("model"),
            "scope": r.get("scope"), "kpi_ids": r["kpi_ids"], "usage": r["usage"], "app_opens": r["app_opens"],
            "downstream": [_edge(e, "downstream", proj) for e in proj["downstream"].get(r["id"], [])],
            "upstream": [_edge(e, "upstream", proj) for e in proj["upstream"].get(r["id"], [])],
            "evidence": [f"Analytics_Assets row {r['row']}" if r.get("row") else None, (r["owner"] or {}).get("evidence")]}


async def pair_detail(store, a: str, b: str, records: list[dict] | None = None) -> dict:
    proj = projection()
    if records is None:
        records, _ = await inventory(store)
    by_id = {r["id"]: r for r in records}
    a, b = sorted((a, b))  # one pair, one orientation, whichever order it was asked in
    if a not in by_id or b not in by_id or a == b:
        raise HTTPException(404, "Choose two different known reporting assets.")
    ra, rb = by_id[a], by_id[b]
    ka, kb = set(ra["kpi_ids"]), set(rb["kpi_ids"])
    shared = sorted(ka & kb)
    rule_pair = proj["pairs"].get(pair_key(a, b))
    same_owner = bool(ra["owner"] and rb["owner"] and ra["owner"]["id"] == rb["owner"]["id"])
    blockers = []
    for r in (ra, rb):
        if r["owner_state"] != "active":
            blockers.append(f"{r['id']}: owner {'missing' if r['owner_state'] == 'absent' else 'inactive'}. Ownership needed first.")
        if r.get("scope") and r["scope"]["mismatch"]:
            blockers.append(f"{r['id']}: report scope differs from model {r['model']['id']}.")
    return {
        "id": pair_key(a, b), "a": _side(ra, proj), "b": _side(rb, proj),
        "shared": [_kpi(k, proj) for k in shared],
        "shared_approved_ids": sorted(set(shared) & proj["approved"]),
        "only_a": [_kpi(k, proj) for k in sorted(ka - kb)], "only_b": [_kpi(k, proj) for k in sorted(kb - ka)],
        "same_scope": (ra["product"], ra["market"]) == (rb["product"], rb["market"]),
        "same_model": (ra.get("model") or {}).get("id") == (rb.get("model") or {}).get("id") and ra.get("model") is not None,
        "same_owner": same_owner, "qualifies": rule_pair is not None, "rule": PAIR_RULE, "blockers": blockers,
        "question": _question(ra, rb, [proj["kpis"][k]["kpi_name"] for k in sorted(set(shared) & proj["approved"])]),
        "note": "Neither a larger audience nor a word like Legacy in a title decides which report stays.",
    }


def _question(ra: dict, rb: dict, names: list[str]) -> str:
    place = ra.get("market_name") or ra.get("market") or "the same scope"
    kpis = " and ".join(names) if names else "the same measures"
    return (f"These {place} reports both include {kpis}. Which decisions, audiences or measures require separate reports?")


@router.get("/api/bi-estate/pairs/{a}/{b}")
async def get_pair(a: str, b: str, request: Request) -> dict:
    store = request.app.state.pipeline.store
    pair = await pair_detail(store, a, b)
    cases = [await case_view(store, c["_id"]) for c in await _find(store, CASES, {"pair_key": pair["id"]})]
    return {**pair, "cases": sorted(cases, key=lambda c: c["generation"])}


# --------------------------------------------------------------------------- app opens

class OpenEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    view_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,64}$")
    source: Literal["dashboard", "workbook_view"] = "dashboard"


@router.post("/api/bi-estate/{asset_id}/opens", status_code=201)
async def record_open(asset_id: str, body: OpenEvent, request: Request) -> dict:
    """A visible, rendered opening of the report content. The same view_id is recorded once (retries, remounts)."""
    store = request.app.state.pipeline.store
    known = asset_id in projection()["assets"] or asset_id in {r[0] for r in EMPLOYEE_REPORTS} or (
        asset_id.startswith("dash_") and await store.get_artifact("dashboards", asset_id))
    if not known:
        raise HTTPException(404, "No reporting asset has this ID.")
    try:
        actor = resolve_actor(request)
    except HTTPException:
        actor = None
    doc = {"_id": f"{asset_id}:{body.view_id}", "asset_id": asset_id, "view_id": body.view_id, "source": body.source,
           "kind": "AnalytIQ dashboard open" if body.source == "dashboard" else "AnalytIQ workbook-view open",
           "actor_id": (actor or {}).get("id"), "at": _now()}
    saved, inserted = await _insert_once(store, OPENS, doc)
    return {"recorded": inserted, "event": {k: v for k, v in saved.items() if k != "_id"}}


# --------------------------------------------------------------------------- ownership overlay (steward only)

class OwnerAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    owner_id: str = Field(min_length=1, max_length=20)
    reason: str = Field(min_length=3, max_length=600)
    expected_seq: int = Field(ge=0)


def _require(actor: dict | None, role: str) -> dict:
    if not actor:
        raise HTTPException(401, "Choose a demo identity to make changes. Viewers can only read.")
    if actor["role"] != role:
        raise HTTPException(403, "This action needs the BI steward role." if role == "bi_steward" else "This action needs a report owner.")
    return actor


@router.post("/api/bi-estate/{asset_id}/owner", status_code=201)
async def assign_owner(asset_id: str, body: OwnerAssignment, request: Request) -> dict:
    store = request.app.state.pipeline.store
    actor = _require(resolve_actor(request), "bi_steward")
    records, _ = await inventory(store)
    if not any(r["id"] == asset_id for r in records):
        raise HTTPException(404, "No reporting asset has this ID.")
    person = people().get(body.owner_id)
    if not person or person["status"] != "active":
        raise HTTPException(422, "Assign an active owner from the Owners list.")
    events = await _events_for(store, OWNERS, "asset_id", asset_id)
    seq = max((e["seq"] for e in events), default=0)
    if body.expected_seq != seq:
        raise HTTPException(409, "Ownership changed meanwhile. Reload the asset.")
    doc = {"_id": f"{asset_id}:{seq + 1:04d}", "asset_id": asset_id, "seq": seq + 1, "owner_id": person["id"],
           "owner_name": person["name"], "reason": body.reason.strip(), "actor_id": actor["id"], "actor_name": actor["name"],
           "at": _now(), "effective_at": _now()}
    _, inserted = await _insert_once(store, OWNERS, doc)
    if not inserted:
        raise HTTPException(409, "Ownership changed meanwhile. Reload the asset.")
    return await asset_detail(store, asset_id)


# --------------------------------------------------------------------------- owner-review cases

OUTCOMES = {"keep_both": "Keep both", "remediate": "Remediate definitions or scope",
            "consolidation_plan": "Prepare consolidation plan", "dismiss": "Dismiss candidate"}
PROPOSALS = {"consolidate": "Consolidate", "more_evidence": "Request more evidence", "keep_both": "Keep both"}


def _snapshot(pair: dict) -> dict:
    side = lambda s: {"id": s["id"], "title": s["title"], "owner_id": (s["owner"] or {}).get("id"),
                      "owner_state": s["owner_state"], "model_id": (s["model"] or {}).get("id"), "kpi_ids": s["kpi_ids"],
                      "product": s["product"], "market": s["market"]}
    snap = {"a": side(pair["a"]), "b": side(pair["b"]), "shared_approved_ids": pair["shared_approved_ids"],
            "rule": f"{PAIR_RULE['id']} v{PAIR_RULE['version']}"}
    snap["hash"] = hashlib.sha256(json.dumps(snap, sort_keys=True).encode()).hexdigest()[:16]
    return snap


class CaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_a: str
    asset_b: str
    question: str = Field(min_length=10, max_length=800)
    note: str = Field(default="", max_length=800)
    due: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


@router.post("/api/bi-reviews", status_code=201)
async def create_case(body: CaseCreate, request: Request) -> dict:
    """Start one owner review for a pair. A repeat, or the same pair in the other order, returns the open case."""
    store = request.app.state.pipeline.store
    actor = _require(resolve_actor(request), "bi_steward")
    pair = await pair_detail(store, body.asset_a, body.asset_b)
    key = pair["id"]
    existing = [c for c in await _find(store, CASES, {"pair_key": key})]
    open_case = next((c for c in existing if c.get("status") != "closed"), None)
    if open_case:
        return await case_view(store, open_case["_id"])
    generation = len(existing) + 1
    previous = max(existing, key=lambda c: c["generation"]) if existing else None
    snap = _snapshot(pair)
    a, b = pair["a"], pair["b"]
    participants = []
    for side in (a, b):
        o = side["owner"]
        participants.append({"asset_id": side["id"], "role": "Accountable owner", "owner_id": (o or {}).get("id"),
                             "name": (o or {}).get("name"), "state": side["owner_state"]})
    case_id = f"CASE-{key}-{generation}"
    doc = {"_id": case_id, "pair_key": key, "assets": [a["id"], b["id"]], "generation": generation, "status": "open",
           "kind": "consolidation_review", "created_at": _now(), "created_by": actor["id"], "previous_case": previous["_id"] if previous else None}
    saved, inserted = await _insert_once(store, CASES, doc)
    if not inserted:
        return await case_view(store, saved["_id"])
    changed = []
    if previous:
        prev_open = (await _events_for(store, CASE_EVENTS, "case_id", previous["_id"]))[0]
        before = prev_open["snapshot"]
        changed = [k for k in ("a", "b", "shared_approved_ids") if before.get(k) != snap.get(k)] or ["nothing in the compared evidence"]
    opened = {"_id": f"{case_id}:0001", "case_id": case_id, "seq": 1, "kind": "opened", "actor_id": actor["id"],
              "actor_name": actor["name"], "at": _now(), "question": body.question.strip(), "note": body.note.strip(),
              "due": body.due, "coordinator": actor["name"], "participants": participants, "snapshot": snap,
              "reopened_from": previous["_id"] if previous else None, "changed_since_previous": changed}
    await _insert_once(store, CASE_EVENTS, opened)
    return await case_view(store, case_id)


async def case_view(store, case_id: str) -> dict:
    case = next(iter(await _find(store, CASES, {"_id": case_id})), None)
    if not case:
        raise HTTPException(404, "No review case has this ID.")
    events = sorted(await _events_for(store, CASE_EVENTS, "case_id", case_id), key=lambda e: e["seq"])
    opened = events[0]
    pair = await pair_detail(store, *case["assets"])
    current = _snapshot(pair)
    responses = {}
    for e in events:
        if e["kind"] == "response":
            for aid in e["asset_ids"]:
                responses[aid] = {k: e[k] for k in ("actor_id", "actor_name", "at", "proposal", "purpose", "consumers",
                                                    "essential_kpis", "blockers", "seq")} | {"asset_id": aid}
    decision = next((e for e in reversed(events) if e["kind"] == "decision"), None)
    ownership_needed = [p["asset_id"] for p in (pair["a"], pair["b"]) if p["owner_state"] != "active"]
    status = "closed" if decision else ("ownership_needed" if ownership_needed else
                                         "awaiting_responses" if len(responses) < 2 else "ready_for_decision")
    owners = [{"asset_id": s["id"], "owner": s["owner"], "owner_state": s["owner_state"]} for s in (pair["a"], pair["b"])]
    return {"id": case_id, "pair_key": case["pair_key"], "assets": case["assets"], "generation": case["generation"],
            "status": status, "status_label": {"closed": "Decided", "ownership_needed": "Ownership needed",
                                               "awaiting_responses": "Awaiting owner responses",
                                               "ready_for_decision": "Ready for decision"}[status],
            "question": opened["question"], "note": opened["note"], "due": opened["due"], "coordinator": opened["coordinator"],
            "created_at": case["created_at"], "owners": owners, "same_owner": pair["same_owner"],
            "responses": responses, "decision": decision, "events": events, "seq": events[-1]["seq"],
            "snapshot": opened["snapshot"], "current_hash": current["hash"],
            "needs_reassessment": current["hash"] != opened["snapshot"]["hash"],
            "reopened_from": opened.get("reopened_from"), "changed_since_previous": opened.get("changed_since_previous"),
            "brief": _brief(case_id, pair, opened)}


def _brief(case_id: str, pair: dict, opened: dict) -> str:
    side = lambda s: (f"- {s['id']} · {s['title']} ({s['platform']}, {s['product']} / {s['market']}), "
                      f"owner {(s['owner'] or {}).get('name', 'unassigned')} {(s['owner'] or {}).get('id', '')}".rstrip())
    shared = ", ".join(f"{k['name']} ({k['id']})" for k in pair["shared"] if k["id"] in pair["shared_approved_ids"])
    return "\n".join([f"Owner review {case_id}", opened["question"], "", "Reports:", side(pair["a"]), side(pair["b"]),
                      f"Shared approved KPIs: {shared or 'none'}",
                      f"Respond in AnalytIQ under BI Portfolio. Due {opened['due'] or 'not set'}.",
                      "Copying this text does not send it to anyone."])


class CaseEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["response", "decision"]
    expected_seq: int = Field(ge=1)
    # response
    asset_id: str | None = None
    proposal: Literal["consolidate", "more_evidence", "keep_both"] | None = None
    purpose: str = Field(default="", max_length=800)
    consumers: str = Field(default="", max_length=400)
    essential_kpis: list[str] = Field(default_factory=list, max_length=20)
    blockers: str = Field(default="", max_length=600)
    # decision
    outcome: Literal["keep_both", "remediate", "consolidation_plan", "dismiss"] | None = None
    reason: str = Field(default="", max_length=1200)
    survivor: str | None = None
    affected: str = Field(default="", max_length=400)
    validation: str = Field(default="", max_length=600)
    accountable_owner_id: str | None = None
    checkpoint: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    acknowledge_changes: bool = False


@router.get("/api/bi-reviews/{case_id}")
async def get_case(case_id: str, request: Request) -> dict:
    return await case_view(request.app.state.pipeline.store, case_id)


@router.post("/api/bi-reviews/{case_id}/events", status_code=201)
async def case_event(case_id: str, body: CaseEvent, request: Request) -> dict:
    store = request.app.state.pipeline.store
    actor = resolve_actor(request)
    if not actor:
        raise HTTPException(401, "Choose a demo identity to take part. Viewers can only read.")
    view = await case_view(store, case_id)
    if view["status"] == "closed":
        raise HTTPException(409, "This review is decided. Start a new review to reopen the pair.")
    if body.expected_seq != view["seq"]:
        raise HTTPException(409, "The review changed meanwhile. Reload it before submitting.")
    seq = view["seq"] + 1
    base = {"_id": f"{case_id}:{seq:04d}", "case_id": case_id, "seq": seq, "kind": body.kind, "actor_id": actor["id"],
            "actor_name": actor["name"], "at": _now()}
    if body.kind == "response":
        if actor["role"] != "owner":
            raise HTTPException(403, "Only an accountable owner of a report in this review can respond.")
        owned = [o["asset_id"] for o in view["owners"] if o["owner"] and o["owner"]["id"] == actor["id"] and o["owner_state"] == "active"]
        if not owned or (body.asset_id and body.asset_id not in owned):
            raise HTTPException(403, "You can respond only for a report you are the active accountable owner of.")
        if not body.proposal or not body.purpose.strip():
            raise HTTPException(422, "Describe the report's purpose and choose a proposal.")
        # The same person owning both reports gives one response that covers both roles.
        asset_ids = owned if view["same_owner"] else [body.asset_id or owned[0]]
        doc = base | {"asset_ids": asset_ids, "proposal": body.proposal, "purpose": body.purpose.strip(),
                      "consumers": body.consumers.strip(), "essential_kpis": body.essential_kpis, "blockers": body.blockers.strip(),
                      "represents_both": view["same_owner"]}
    else:
        if actor["role"] != "bi_steward":
            raise HTTPException(403, "Only the BI steward records the decision.")
        if not body.outcome or len(body.reason.strip()) < 5:
            raise HTTPException(422, "Choose an outcome and give a reason.")
        if view["needs_reassessment"] and not body.acknowledge_changes:
            raise HTTPException(409, "An owner or binding changed since the review started. Reassess, then confirm.")
        if body.outcome != "dismiss" and view["status"] != "ready_for_decision":
            raise HTTPException(409, "Both owners must respond first. Only Dismiss candidate is allowed before that.")
        plan = None
        if body.outcome == "consolidation_plan":
            if body.survivor not in view["assets"] or not body.accountable_owner_id or not body.checkpoint:
                raise HTTPException(422, "A plan names the surviving report, an accountable owner and a checkpoint date.")
            owner = people().get(body.accountable_owner_id)
            if not owner or owner["status"] != "active":
                raise HTTPException(422, "The plan's accountable owner must be an active owner.")
            plan = {"survivor": body.survivor, "affected": body.affected.strip(), "validation": body.validation.strip(),
                    "accountable_owner": {"id": owner["id"], "name": owner["name"]}, "checkpoint": body.checkpoint}
        proposals = {r["proposal"] for r in view["responses"].values()}
        doc = base | {"outcome": body.outcome, "outcome_label": OUTCOMES[body.outcome], "reason": body.reason.strip(),
                      "plan": plan, "owner_disagreement": len(proposals) > 1, "responses_at_decision": view["responses"],
                      "evidence_hash": view["current_hash"], "acknowledged_changes": view["needs_reassessment"],
                      "execution": "Not executed. Retiring or changing a report needs a separately authorised action."}
    _, inserted = await _insert_once(store, CASE_EVENTS, doc)
    if not inserted:
        raise HTTPException(409, "The review changed meanwhile. Reload it before submitting.")
    if body.kind == "decision":
        await _set(store, CASES, case_id, {"status": "closed", "closed_at": doc["at"]})
    return await case_view(store, case_id)
