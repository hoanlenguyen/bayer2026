"""Workbook-backed estate inventory and independently reviewed local report revisions."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from . import catalog
from .briefing_definitions import DEFAULTS, EMPLOYEE_REPORTS, VIEWS

router = APIRouter(prefix="/api/report-register")
EVENTS = "report_change_events"


def _rows(sheet: str):
    return enumerate(catalog.SHEETS[sheet.lower()], start=2)


def _people() -> dict:
    return {r["owner_id"]: {"id": r["owner_id"], "name": r["owner_name"], "status": r["status"],
                            "evidence": f"Owners row {i}"} for i, r in _rows("Owners")}


def inventory() -> dict[str, dict]:
    people = _people()
    models = {r["model_id"]: (i, r) for i, r in _rows("Semantic_Models")}
    kpis = {r["kpi_id"]: (i, r) for i, r in _rows("KPI_Catalog")}
    usage = defaultdict(list)
    for i, r in _rows("Asset_Usage"):
        usage[r["asset_id"]].append((i, r))
    signals = defaultdict(list)
    for i, r in _rows("Governance_Signals"):
        signals[r["asset_id"]].append((i, r))
    reports = {}
    for i, r in _rows("Analytics_Assets"):
        aid = r["asset_id"]
        owner = people.get(r["owner_id"])
        model_row, model = models[r["model_id"]]
        months = sorted(usage[aid], key=lambda x: x[1]["month"])
        active = [(n, u) for n, u in months if any(u[key] for key in ("views", "unique_users", "exports", "subscriptions"))]
        evidence = {f"Analytics_Assets row {i}": f"{aid} · {r['asset_name']} · {r['product_scope']} / {r['market_scope']} · {r['lifecycle_status']}",
                    f"Semantic_Models row {model_row}": f"{r['model_id']} · {model['product_scope']} · {model['refresh_frequency']} · {model['refresh_status']}"}
        if owner:
            evidence[owner["evidence"]] = f"{owner['id']} · {owner['name']} · {owner['status']}"
        if active:
            n, u = active[-1]
            evidence[f"Asset_Usage row {n}"] = (f"{u['month'][:7]} · {u['views']} views · {u['unique_users']} unique users"
                                                 f" · {u['exports']} exports · {u['subscriptions']} subscriptions")
        issues = []
        if (r["product_scope"] != model["product_scope"]
                and "All Pharma" not in (r["product_scope"], model["product_scope"])):
            issues.append("Product scope mismatch")
        if not owner or owner["status"] != "active":
            issues.append("Ownership")
        if model["refresh_status"] in {"warning", "failed"}:
            issues.append("Model refresh")
        if r["lifecycle_status"] == "candidate_retire":
            issues.append("Retirement review")
        if any(s["status"] == "open" for _, s in signals[aid]):
            issues.append("Open governance signal")
        for n, s in signals[aid]:
            evidence[f"Governance_Signals row {n}"] = f"{s['signal_id']} · {s['signal_code']} · {s['status']}"
        reports[aid] = {
            "id": aid, "title": r["asset_name"], "kind": r["asset_type"], "platform": r["platform"], "origin": "Estate",
            "owner": owner, "product": r["product_scope"], "market": r["market_scope"], "created": r["created_date"],
            "modified": r["last_modified"], "last_use_month": active[-1][1]["month"][:7] if active else None,
            "usage_window": [months[0][1]["month"][:7], months[-1][1]["month"][:7]] if months else [],
            "views": sum(u["views"] for _, u in months) if months else None,
            "model_id": r["model_id"], "refresh": model["refresh_status"], "cadence": model["refresh_frequency"],
            "lifecycle": r["lifecycle_status"], "issues": issues, "model_product": model["product_scope"], "evidence": evidence,
        }
    for aid, title, kpi_id, product in EMPLOYEE_REPORTS:
        n, kpi = kpis[kpi_id]
        owner = people[kpi["owner_id"]]
        reports[aid] = {
            "id": aid, "title": title, "kind": "Employee report", "platform": "SinceAI", "origin": "Employee",
            "owner": owner, "product": product, "market": "Germany", "created": None, "modified": None,
            "last_use_month": None, "usage_window": [], "views": None, "model_id": None,
            "model_product": None, "refresh": None, "cadence": None, "lifecycle": "active", "issues": [],
            "evidence": {
                "App report definition": f"{aid} · {title} · designated steward from {kpi_id}",
                f"KPI_Catalog row {n}": f"{kpi_id} · {kpi['kpi_name']} · {kpi['approval_status']} · {kpi['owner_id']}",
                owner["evidence"]: f"{owner['id']} · {owner['name']} · {owner['status']}",
                "Product_Market_Monthly": "Synthetic product, market and month observations",
            },
        }
    return reports


async def _consumers(store) -> dict[str, list[str]]:
    by_report = defaultdict(list)
    for team, default in DEFAULTS.items():
        saved = await store.get_artifact("briefing_selections", team)
        for vid in saved["view_ids"] if saved else default:
            by_report[VIEWS[vid][0]].append(team.capitalize())
    return by_report


async def _events(store, aid: str | None = None, kind: str | None = None) -> list[dict]:
    query = {}
    if aid:
        query["report_id"] = aid
    if kind:
        query["kind"] = kind
    if store.name == "mongodb":
        return [r async for r in store.db[EVENTS].find(query).sort("seq", 1)]
    rows = store.artifacts.get(EVENTS, {}).values()
    return sorted((r for r in rows if all(r[k] == v for k, v in query.items())), key=lambda r: r["seq"])


async def _append(store, event: dict) -> None:
    # The report-scoped sequence in _id also guards against concurrent reviews across workers.
    if store.name == "mongodb":
        from pymongo.errors import DuplicateKeyError
        try:
            await store.db[EVENTS].insert_one(event)
            return
        except DuplicateKeyError:
            pass
    else:
        events = store.artifacts.setdefault(EVENTS, {})
        if event["_id"] not in events:
            events[event["_id"]] = event
            return
    raise HTTPException(409, "This report changed. Reload the current revision.")


async def published_revisions(store) -> dict[str, dict]:
    return {e["report_id"]: {"title": e["title"], "display_mode": e["display_mode"], "revision": e["revision"]}
            for e in await _events(store, kind="approved")}


async def published_titles(store) -> dict[str, str]:
    """Titles from accepted revisions, suitable for employee and shared source views."""
    return {aid: r["title"] for aid, r in (await published_revisions(store)).items()}


def _detail(record: dict, events: list[dict]) -> dict:
    approved = [e for e in events if e["kind"] == "approved"]
    return {**record, "baseline_title": record["title"], "title": approved[-1]["title"] if approved else record["title"],
            "display_mode": approved[-1]["display_mode"] if approved else ("chart" if record["origin"] == "Employee" else None),
            "revision": len(approved), "published_at": approved[-1]["at"] if approved else None, "history": events}


@router.get("")
async def register(request: Request):
    store = request.app.state.pipeline.store
    records = inventory()
    consumers = await _consumers(store)
    events = await _events(store)
    history = defaultdict(list)
    for e in events:
        history[e["report_id"]].append(e)
    reports = []
    for aid, record in records.items():
        detail = _detail({**record, "teams": consumers[aid] if record["origin"] == "Employee" else None}, history[aid])
        reports.append({k: v for k, v in detail.items() if k not in ("evidence", "history")} |
                       {"change_status": history[aid][-1]["kind"] if history[aid] else None})
    return {"reports": reports, "people": [p for p in _people().values() if p["status"] == "active"],
            "store": store.name}


@router.get("/titles")
async def titles(request: Request):
    return {"titles": await published_titles(request.app.state.pipeline.store)}


async def _linked_actions(store, report_id: str, limit: int = 20) -> list[dict]:
    """Retrieve recent follow-ups attached directly or through the saved team snapshot."""
    if store.name == "mongodb":
        query = {"$or": [{"asset_id": report_id}, {"briefing_snapshot.views.report_id": report_id}]}
        cursor = store.db["actions"].find(query).sort([("created_at", -1), ("_id", -1)]).limit(limit)
        return [row async for row in cursor]
    rows = (row for row in store.artifacts["actions"].values()
            if row.get("asset_id") == report_id or any(v["report_id"] == report_id
                for v in (row.get("briefing_snapshot") or {}).get("views", [])))
    return sorted(rows, key=lambda row: (row["created_at"], row["_id"]), reverse=True)[:limit]


async def _record(report_id: str, store) -> dict:
    r = inventory().get(report_id)
    if not r:
        raise HTTPException(404, "Unknown report ID.")
    r["teams"] = (await _consumers(store))[report_id] if r["origin"] == "Employee" else None
    if r["teams"] is not None:
        r["evidence"]["Shared briefing selections"] = ", ".join(r["teams"]) or "No team currently pins this report."
    r["linked_actions"] = await _linked_actions(store, report_id)
    for action in r["linked_actions"]:
        snapshot = action.get("briefing_snapshot")
        if snapshot:
            r["evidence"][f"Saved action {action['_id']}"] = (
                f"{action['title']} · {action['owner']} · {snapshot['team']} · source version {snapshot['version']}"
            )
    return r


@router.get("/{report_id}")
async def detail(report_id: str, request: Request):
    store = request.app.state.pipeline.store
    return _detail(await _record(report_id, store), await _events(store, report_id))


class Change(BaseModel):
    kind: Literal["requested", "prepared", "approved", "returned"]
    actor_id: str = Field(min_length=1, max_length=40)
    note: str = Field(min_length=1, max_length=800)
    title: str | None = Field(default=None, max_length=150)
    display_mode: Literal["chart", "table"] | None = None
    evidence_ref: str = Field(min_length=1, max_length=150)
    expected_seq: int = Field(ge=0)


@router.post("/{report_id}/changes", status_code=201)
async def change(report_id: str, body: Change, request: Request):
    store = request.app.state.pipeline.store
    record = await _record(report_id, store)
    events = await _events(store, report_id)
    last = events[-1] if events else {}
    if body.expected_seq != last.get("seq", 0):
        raise HTTPException(409, "This report changed. Reload the current revision.")
    allowed = {None: {"requested"}, "approved": {"requested"}, "requested": {"prepared"},
               "prepared": {"approved", "returned"}, "returned": {"prepared"}}
    if body.kind not in allowed[last.get("kind")]:
        raise HTTPException(409, "This step is unavailable in the current review state.")
    if body.kind != "prepared" and (body.title is not None or body.display_mode is not None):
        raise HTTPException(422, "Only the owner preparation step accepts report edits.")
    person = _people().get(body.actor_id)
    if not person or person["status"] != "active":
        raise HTTPException(403, "Choose an active named participant.")
    if body.kind == "requested" and record["owner"] and person["id"] == record["owner"]["id"]:
        raise HTTPException(403, "Choose a requester distinct from the report owner.")
    note = body.note.strip()
    if not note or body.evidence_ref not in record["evidence"]:
        raise HTTPException(422, "Enter a note and select a source from this report.")
    current = _detail(record, events)
    current_title = current["title"]
    display_mode = current["display_mode"]
    title = None
    if body.kind == "prepared":
        if not record["owner"] or person["id"] != record["owner"]["id"]:
            raise HTTPException(403, "The active designated report owner must prepare the edit.")
        if body.display_mode and record["origin"] != "Employee":
            raise HTTPException(422, "Display settings apply to employee reports only.")
        title = current_title if body.title is None else body.title.strip()
        display_mode = body.display_mode or current["display_mode"]
        if not title or (title == current_title and display_mode == current["display_mode"]):
            raise HTTPException(422, "Prepare a change to the shared title or report display.")
    elif body.kind in ("approved", "returned"):
        if person["id"] in (last["actor_id"], last["requester_id"]):
            raise HTTPException(403, "Choose a reviewer independent of the requester and owner.")
        title = last["title"]
        display_mode = last["display_mode"]
    seq = len(events) + 1
    event = {"_id": f"{report_id}:{seq}", "report_id": report_id, "seq": seq, "previous": last.get("_id"),
             "request_id": str(uuid4()) if body.kind == "requested" else last["request_id"],
             "requester_id": person["id"] if body.kind == "requested" else last["requester_id"],
             "kind": body.kind, "actor_id": person["id"], "actor_name": person["name"], "note": note,
             "at": datetime.now(timezone.utc).isoformat(), "base_title": current_title, "title": title,
             "base_display_mode": current["display_mode"], "display_mode": display_mode,
             "revision": current["revision"] + (1 if body.kind == "approved" else 0),
             "evidence_ref": body.evidence_ref, "evidence_value": record["evidence"][body.evidence_ref]}
    await _append(store, event)
    return _detail(record, [*events, event])
