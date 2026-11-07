"""Shared team briefings over the Nubeqa/Germany slice of the synthetic workbook."""
from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any, Literal

from . import actions, catalog
from .briefing_definitions import DEFAULTS, FILTERS, VIEWS
from .report_register import published_revisions
from .store import Store

Team = Literal["commercial", "supply"]
ViewId = Literal["sales", "shipments", "otif"]

ACTOR_IDS = {"commercial": "OWN-008", "supply": "OWN-005"}
SUGGESTIONS = {
    "commercial": "Reconcile the sales and shipment changes before revising the next forecast.",
    "supply": "Review the shipment changes with the supply planner and check the dispatch records.",
}


def _version(content: Any) -> str:
    encoded = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()[:16]


def active_owners() -> dict[str, dict[str, str]]:
    return {r["owner_id"]: {"id": r["owner_id"], "name": r["owner_name"], "role": r["role"]}
            for r in catalog.SHEETS["owners"] if r["status"] == "active"}


def _scope(sheet: str) -> list[tuple[int, dict[str, Any]]]:
    return [(i, r) for i, r in enumerate(catalog.SHEETS.get(sheet.lower(), []), start=2)
            if all(r.get(k) == v for k, v in FILTERS.items())]


def _evidence(sheet: str, rows: list[tuple[int, dict[str, Any]]], fields: list[str]) -> dict[str, Any]:
    return {"sheet": sheet, "rows": [i for i, _ in rows], "filters": dict(FILTERS), "fields": fields,
            "records": [{k: r[k] for k in fields} for _, r in rows]}


def report_views(revisions: dict[str, dict[str, Any]]) -> tuple[str, str, list[dict[str, Any]]]:
    monthly = sorted(_scope("Product_Market_Monthly"), key=lambda entry: entry[1]["month"])
    if len(monthly) < 2:
        raise ValueError("Two distinct monthly source records are required for this briefing.")
    if len({r["month"][:7] for _, r in monthly}) != len(monthly):
        raise ValueError("The workbook has multiple observations for the same product, market and month.")
    comparison = monthly[-2:]
    previous, current = (r for _, r in comparison)
    views = []
    for view_id, (report_id, name, title, kpi_id, unit, column) in VIEWS.items():
        fields = ["month", "value_type", column]
        if view_id == "sales":
            fields.append("forecast_m_eur_syn")
        if any(r.get(k) is None for _, r in monthly for k in fields):
            raise ValueError(f"Source values are missing for {title}.")
        points = [{"row": row, "period": r["month"][:7], "value": r[column], "value_type": r["value_type"],
                   **({"forecast": r["forecast_m_eur_syn"]} if view_id == "sales" else {})} for row, r in monthly]
        history = {"sheet": "Product_Market_Monthly", "filters": dict(FILTERS), "unit": unit, "fields": list(fields),
                   "start_period": points[0]["period"], "end_period": points[-1]["period"], "points": points}
        if view_id == "sales":
            fields.append("forecast_variance_pct")
        a, b = previous[column], current[column]
        revision = revisions.get(report_id, {})
        view = {
            "id": view_id, "report_id": report_id, "report": revision.get("title") or name, "title": title,
            "revision": revision.get("revision", 0), "display_mode": revision.get("display_mode") or "chart",
            "kpi_id": kpi_id, "unit": unit, "current": b, "previous": a,
            "forecast": current.get("forecast_m_eur_syn") if view_id == "sales" else None,
            "forecast_variance_pct": current.get("forecast_variance_pct") if view_id == "sales" else None,
            "change_pct": round(100 * (b - a) / a, 1) if a and view_id != "otif" else None,
            "change_pp": round(b - a, 1) if view_id == "otif" else None,
            "evidence": _evidence("Product_Market_Monthly", comparison, fields), "history": history,
        }
        view["version"] = _version(view)
        views.append(view)
    return current["month"][:7], previous["month"][:7], views


async def briefing_snapshot(store: Store, team: Team) -> dict[str, Any]:
    period, previous, views = report_views(await published_revisions(store))
    selection = await store.get_artifact("briefing_selections", team)
    route = None
    if team == "supply":
        routing = _scope("Supply_Operations")
        if len(routing) == 1:
            ref = routing[0][1]
            route = {"source": ref["supply_source"], "mode": ref["primary_mode"], "period": None,
                     "evidence": _evidence("Supply_Operations", routing, ["supply_source", "primary_mode"])}
    actor = active_owners().get(ACTOR_IDS[team])
    if not actor:
        raise ValueError("The configured demo actor is no longer active in the workbook.")
    selected = selection["view_ids"] if selection else DEFAULTS[team]
    suggestion = SUGGESTIONS[team] if set(selected) == set(DEFAULTS[team]) else (
        f"Review {', '.join(VIEWS[key][2] for key in selected)} for Nubeqa in Germany.")
    briefing = {
        "team": team, "product": "Nubeqa", "market": "Germany", "period": period, "previous_period": previous,
        "synthetic": True, "selected_view_ids": selected,
        "views": views, "route": route, "suggested_action": suggestion, "actor": actor,
    }
    briefing["version"] = _version(briefing)
    return briefing


def _action_id(team: Team, version: str, view_id: ViewId | None) -> str:
    return f"act_brief_{team}_{version}_{view_id or 'team'}"


async def read_briefing(store: Store, team: Team) -> dict[str, Any]:
    result = await briefing_snapshot(store, team)
    result["storage_mode"] = store.name
    result["owners"] = sorted(active_owners().values(), key=lambda r: (r["name"], r["id"]))
    recent = await store.list_briefing_actions(team, limit=20)
    result["recent_actions"] = [actions.view(a) for a in recent]
    by_id = {a["_id"]: a for a in recent}
    for obj in [result, *result["views"]]:
        key = _action_id(team, result["version"], obj.get("id"))
        existing = by_id.get(key)
        if not existing and len(recent) == 20:
            existing = await store.get_artifact("actions", key)
        obj["action"] = actions.view(existing) if existing else None
    return result


async def save_followup(store: Store, team: Team, version: str, view_id: ViewId | None, title: str | None,
                        owner_id: str, due_date: date) -> dict[str, Any]:
    owner = active_owners().get(owner_id)
    if not owner:
        raise KeyError("Select an active owner from the workbook.")
    action_id = _action_id(team, version, view_id)
    existing = await store.get_artifact("actions", action_id)
    if existing:
        return actions.view(existing)
    snapshot = await briefing_snapshot(store, team)
    if snapshot["version"] != version:
        raise ValueError("The briefing changed. Refresh it and review the current figures before assigning an action.")
    ids = [view_id] if view_id else snapshot["selected_view_ids"]
    lookup = {view["id"]: view for view in snapshot["views"]}
    snapshot["views"] = [lookup[vid] for vid in ids]
    snapshot["scope_view_id"] = view_id
    source = lookup[view_id] if view_id else None
    if source:
        snapshot["route"] = None
    else:
        # The shared meeting cards show the two most recent observations.
        for view in snapshot["views"]:
            view.pop("history")
    suggestion = snapshot.pop("suggested_action")
    action = actions.create({
        "kind": "business", "owner": owner["name"], "due_date": due_date.isoformat(), "key": action_id,
        "title": title or (f"Review {source['title']} for Nubeqa in Germany" if source else suggestion),
        "reason": f"{team.capitalize()} briefing · Nubeqa, Germany · {snapshot['period']}",
        "asset_id": source["report_id"] if source else None, "asset_name": source["report"] if source else None,
    }, by=snapshot["actor"]["name"])
    action["_id"] = action_id
    action["owner_id"] = owner_id
    action["created_by_id"] = snapshot["actor"]["id"]
    action["history"][0]["by_id"] = action["created_by_id"]
    action["history"][0]["owner_id"] = owner_id
    action["briefing_snapshot"] = snapshot
    return actions.view(await store.insert_action_once(action))
