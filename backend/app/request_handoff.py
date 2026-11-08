"""Turn a saved Ask verdict into reviewable owner work without changing the source report."""
from __future__ import annotations

from datetime import date
from hashlib import sha256
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from . import actions, catalog
from .ask_metrics import metric_series, verified_reuse_preview
from .briefing_routes import Progress, StoreDep, apply_progress
from .briefings import active_owners
from .decision import score_asset
from .employee_report_match import matching_employee_report
from .report_register import published_revisions
from .store import Store

router = APIRouter(prefix="/api/conversations/{conversation_id}/runs/{run_id}/handoff")

# Each assignment concerns owner work. No endpoint here writes to a report or BI tenant.
WORK = {
    "reuse": ("Arrange access to", "Confirm the report entry point, access and requested filters with its owner."),
    "repair": ("Prepare repairs for", "Resolve the recorded governance or coverage blockers and retest before reuse."),
    "extend": ("Scope an extension to", "Review the missing measures and breakdowns before extending the report."),
    "consolidate": ("Review consolidation of", "Compare overlapping assets and dependencies before agreeing which report to keep."),
    "migrate": ("Plan Power BI migration for", "Map the source KPIs and dependencies, then reconcile the proposed replacement with its owner."),
    "retire": ("Assess retirement of", "Confirm the downstream impact and obtain owner approval before retiring the report."),
    "review": ("Review", "Resolve the recorded uncertainty with the owner before selecting a lifecycle action."),
    "new_build": ("Scope a new report", "Agree the governed measures, scope and acceptance checks before authoring a draft."),
    "create": ("Scope a new report", "Agree the governed measures, scope and acceptance checks before authoring a draft."),
    "not_feasible": ("Review the data gap", "Ask the requester whether an available governed, aggregate measure can support the decision."),
}
NO_ASSET = {"new_build", "create", "not_feasible"}
INTENT_FIELDS = ("measures", "dimensions", "filters", "grain", "scope_global", "decision", "department",
                 "migration", "unmatched_terms", "other_markets", "source_asset_id")
DEMO_ACTOR = "OWN-008"


class Assignment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    owner_id: str = Field(pattern=r"^OWN-[0-9]{3}$")
    due_date: date


def _action_id(conversation_id: str, run_id: str) -> str:
    key = sha256(f"{conversation_id}/{run_id}".encode()).hexdigest()[:24]
    return f"act_request_{key}"


async def _saved_run(store: Store, conversation_id: str, run_id: str) -> tuple[dict, str]:
    conv = await store.get(conversation_id)
    runs = (conv or {}).get("runs", [])
    for i, run in enumerate(runs):
        if run.get("id") != run_id:
            continue
        events = run.get("events", [])
        if not any(e.get("type") == "done" and e.get("state") in ("idle", "awaiting_approval") for e in events):
            raise HTTPException(409, "This run does not yet have a completed recommendation.")
        question = next((e["content"] for e in events if e.get("type") == "user_message" and e.get("content")), "")
        if not question and "msg_start" in run:
            end = runs[i + 1].get("msg_start") if i + 1 < len(runs) else None
            messages = conv["messages"][run["msg_start"]:end]
            question = next((m["content"] for m in messages if m["role"] == "user"), "")
        return run, question
    raise HTTPException(404, "No saved Ask run matches that conversation and run ID.")


def _workbook_refs(asset: dict, model_ids: set[str], kpi_ids: set[str]) -> list[dict]:
    refs = []
    sheets = (
        ("Analytics_Assets", "asset_id", {asset.get("id")}, ("asset_name", "product_scope", "market_scope", "model_id")),
        ("Semantic_Models", "model_id", model_ids, ("model_name", "product_scope", "region_scope", "refresh_status")),
        ("KPI_Catalog", "kpi_id", kpi_ids, ("kpi_name", "approval_status", "definition_status")),
        ("Lineage_Edges", "target_id", {asset.get("id")}, ("source_id", "target_id", "edge_type")),
        ("Governance_Signals", "asset_id", {asset.get("id")}, ("signal_id", "signal_code", "severity", "status")),
        ("Migration_Backlog", "source_asset_id", {asset.get("id")}, ("recommended_path_candidate", "candidate_target_model_id", "status")),
    )
    for sheet, key, ids, fields in sheets:
        for index, r in enumerate(catalog.SHEETS.get(sheet.lower(), []), 2):
            if r.get(key) and r[key] in ids:
                refs.append({"sheet": sheet, "row": index, "id": r[key],
                             "detail": " · ".join(f"{f}: {r[f]}" for f in fields if r.get(f) is not None)})
    return refs


def _receipt(conversation_id: str, run: dict, question: str) -> dict[str, Any]:
    stages = {e["stage"]: e for e in run.get("events", []) if e.get("type") == "stage" and e.get("status") == "done"}
    decision = stages.get("decision", {}).get("data") or {}
    verdict = decision.get("decision")
    if verdict not in WORK:
        raise HTTPException(409, "This saved run has no supported recommendation.")
    raw_intent = stages.get("intent", {}).get("data") or {}
    intent = {"measures": [], "dimensions": [], "filters": {}, "grain": None,
              **{k: raw_intent[k] for k in INTENT_FIELDS if k in raw_intent}}
    native = decision.get("employee_report") if verdict == "reuse" and decision.get("change_type") == "employee_report_reuse" else None
    saved = decision.get("saved_dashboard") if verdict == "reuse" and decision.get("change_type") == "saved_dashboard_reuse" else None
    candidate = None if native or saved else decision.get("candidate")
    asset = catalog.asset_by_id(candidate["asset_id"]) if candidate and candidate.get("asset_id") else None
    asset = asset or {}
    evidence = []
    step_data = {}
    for name in ("kpis", "discovery", "lineage", "governance", "migration"):
        event = stages.get(name, {})
        step = (event.get("data") or {}).get("step") or {}
        if event:
            data = step.get("data") or {}
            summary = event.get("summary") or step.get("summary", "")
            if native and name != "kpis":
                summary = f"Imported catalog search: {summary}"
            evidence.append({"stage": name, "summary": summary,
                             "sheets": step.get("sheets", []), "findings": step.get("findings", []), "data": data})
            step_data[name] = data
    model_id = None if native else decision.get("target_model_id")
    model = None if native else decision.get("target_model") or ({"id": model_id, "name": model_id} if model_id else None)
    source_refs = _workbook_refs(asset, {asset.get("model_id"), model_id},
                                 {m.get("kpi_id") for m in step_data.get("kpis", {}).get("kpis", [])})
    label, instruction = WORK[verdict]
    subject = (candidate or {}).get("name")
    action_title = f"{label} {subject}" if subject and verdict not in NO_ASSET else label
    if model and model.get("name") and verdict in ("new_build", "create"):
        action_title += f" on {model['name']}"
    plan = [instruction]
    trust = step_data.get("governance", {})
    if verdict in {"repair", "review", "extend"}:
        plan.extend(trust.get("repair_actions") or [])
        plan.extend(f"Review the recorded blocker: {gate}" for gate in (candidate or {}).get("gates_failed", []))
    if verdict == "migrate":
        migration = next((a for a in step_data.get("migration", {}).get("assets", [])
                          if a.get("id") == (candidate or {}).get("asset_id")), None)
        if migration and migration.get("destination_model"):
            plan.append(f"Validate proposed destination {migration['destination_model']} against the source model.")
    if verdict == "consolidate" and decision.get("replaces"):
        plan.append("Review the proposed consolidation set: " + ", ".join(decision["replaces"]) + ".")
    missing = (decision.get("availability") or {}).get("missing_terms") or []
    if verdict == "not_feasible" and missing:
        plan.append("Clarify alternatives to the unavailable terms: " + ", ".join(missing) + ".")
    target_owner = (catalog.model_by_id(model_id) or {}).get("owner_id") if model_id and verdict in NO_ASSET else None
    if verdict not in NO_ASSET:
        target_owner = asset.get("owner_id")
    if native:
        action_title = f"Review {native['title']} with the requester"
        plan = ["Open the published employee report for the requested KPI and filters.",
                "If follow-up is needed, assign an owner to record how the report supported the decision."]
        target_owner = native["owner_id"]
        proof = native["evidence"]
        for row, record in zip(proof["rows"], proof["records"]):
            source_refs.append({"sheet": proof["sheet"], "row": row, "id": native["report_id"],
                                "detail": " · ".join(f"{f}: {record[f]}" for f in proof["fields"] if f in record)})
        evidence.insert(0, {"stage": "employee_report", "summary": f"{native['title']} · saved revision {native['revision']}",
                            "sheets": [proof["sheet"]], "findings": [f"{native['report_id']} · {native['kpi_id']}"],
                            "data": proof})
    if saved:
        action_title = f"Assign an owner to {saved['title']}"
        plan = [f"Open the dashboard already built in Ask ({saved['url']}) and use it for this request.",
                "Assign an accountable owner in BI Portfolio, so the reused dashboard has someone who answers for it."]
        target_owner = None
        evidence.insert(0, {"stage": "saved_dashboard", "summary": f"{saved['title']} · built in Ask by {saved['created_by']}",
                            "sheets": [], "findings": [f"{saved['id']} · " + ", ".join(k["kpi_id"] for k in saved["kpis"] if k.get("kpi_id"))],
                            "data": saved})
    return _check_current_reuse({
        "conversation_id": conversation_id, "run_id": run["id"], "started_at": run.get("started_at"), "question": question,
        "verdict": verdict, "reason": decision.get("reason") or stages["decision"].get("summary", ""),
        "action_title": action_title, "plan_steps": plan, "intent": intent, "candidate": candidate,
        "candidates": (stages.get("discovery", {}).get("data") or {}).get("candidates", []),
        "target_model": model, "rules": decision.get("rules_applied", []), "evidence": evidence, "source_refs": source_refs,
        "preview": None if saved else verified_reuse_preview(intent, decision, asset),
        "employee_report": native or (None if saved else matching_employee_report(intent)), "saved_dashboard": saved,
        "metric_series": decision.get("metric_series"),
        "estate_assessment": decision.get("estate_assessment"), "change_type": decision.get("change_type"),
        "handoff_verdict": verdict, "current_review": None,
        "suggested_owner_id": target_owner, "flags": decision.get("flags", []), "replaces": decision.get("replaces", []),
    })


def _check_current_reuse(receipt: dict) -> dict:
    """Preserve the original verdict, but do not offer access to a report that now fails the reuse checks."""
    if (receipt["verdict"] != "reuse" or receipt.get("change_type") in ("employee_report_reuse", "saved_dashboard_reuse")
            or receipt.get("handoff_verdict") == "review"):
        return receipt
    old = receipt.get("candidate") or {}
    asset = catalog.asset_by_id(old.get("asset_id"))
    current = score_asset(receipt["intent"], asset, catalog.CATALOG) if asset else None
    if current and current.reusable:
        return receipt
    reason = (" ".join(current.gates_failed) or "The report no longer meets the required scope, KPI, freshness and governance checks."
              if current else "The recommended report is absent from the current catalog.")
    name = old.get("name") or "the saved report"
    return {**receipt, "handoff_verdict": "review", "action_title": f"Verify the saved reuse recommendation for {name}",
            "current_review": {"reason": reason, "scope_evidence": current.scope_evidence if current else None},
            "plan_steps": [reason, "Ask the report owner to confirm the source and coverage before arranging access."],
            "preview": None, "metric_series": None}


def _actor(owners: dict) -> dict:
    actor = owners.get(DEMO_ACTOR)
    if not actor:
        raise HTTPException(503, "The configured Ask demo actor is no longer an active workbook owner.")
    return actor


async def _validated_receipt(store: Store, conversation_id: str, run: dict, question: str, assigned: dict | None = None) -> dict:
    receipt = _check_current_reuse(assigned["request_snapshot"]) if assigned else _receipt(conversation_id, run, question)
    frozen = receipt.get("metric_series")
    if not frozen:
        return receipt  # Never add a trend to a run or assignment that did not capture it.
    saved = next((e.get("data") or {} for e in reversed(run["events"])
                  if e.get("stage") == "decision" and e.get("status") == "done"), {})
    if frozen != saved.get("metric_series") or frozen != metric_series(receipt["intent"], saved):
        return {**receipt, "metric_series": None}
    native = saved.get("employee_report")
    if native:
        current = (await published_revisions(store)).get(native["report_id"], {})
        if native.get("revision") != current.get("revision", 0) or frozen["display_mode"] != (current.get("display_mode") or "chart"):
            return {**receipt, "metric_series": None}
    return receipt


@router.get("")
async def read_handoff(conversation_id: str, run_id: str, store: StoreDep) -> dict:
    run, question = await _saved_run(store, conversation_id, run_id)
    existing = await store.get_artifact("actions", _action_id(conversation_id, run_id))
    receipt = await _validated_receipt(store, conversation_id, run, question, existing)
    owners = active_owners()
    other = await store.list_run_actions(conversation_id, run_id)
    keys = ("_id", "title", "kind", "owner", "owner_id", "status", "due_date", "asset_id", "run_id")
    covering = {}
    linked = {proposal["existing_action_id"]: proposal.get("key")
              for event in run.get("events", []) if event.get("stage") == "actions" and event.get("status") == "done"
              for proposal in (event.get("data") or {}).get("proposals", []) if proposal.get("existing_action_id")}
    for aid, key in linked.items():
        work = await store.get_artifact("actions", aid)
        if work and key and work.get("key") == key and work["status"] in ("open", "in_progress", "blocked"):
            covering[aid] = {k: work.get(k) for k in keys}
    return {**receipt, "owners": sorted(owners.values(), key=lambda r: (r["name"], r["id"])),
            "suggested_owner_id": receipt["suggested_owner_id"] if receipt["suggested_owner_id"] in owners else None,
            "actor": _actor(owners), "storage_mode": store.name, "action": actions.view(existing) if existing else None,
            "related_actions": [{k: a.get(k) for k in keys} for a in other if a["_id"] != _action_id(conversation_id, run_id)],
            "covering_actions": list(covering.values())}


@router.post("/actions")
async def assign(conversation_id: str, run_id: str, body: Assignment, store: StoreDep) -> dict:
    run, question = await _saved_run(store, conversation_id, run_id)
    action_id = _action_id(conversation_id, run_id)
    saved = await store.get_artifact("actions", action_id)
    if not saved:
        owners = active_owners()
        owner = owners.get(body.owner_id)
        if not owner:
            raise HTTPException(422, "Select an active workbook owner.")
        actor = _actor(owners)
        snapshot = await _validated_receipt(store, conversation_id, run, question)
        candidate = snapshot["candidate"] if snapshot["verdict"] not in NO_ASSET else None
        native = snapshot["employee_report"] if snapshot["change_type"] == "employee_report_reuse" else None
        target_id = native["report_id"] if native else (candidate or {}).get("asset_id")
        target_name = native["title"] if native else (candidate or {}).get("name")
        action = actions.create({"key": action_id, "kind": "business" if snapshot["handoff_verdict"] == "reuse" else "maintenance",
                                 "title": snapshot["action_title"], "reason": (snapshot["current_review"] or {}).get("reason", snapshot["reason"]),
                                 "owner": owner["name"],
                                 "due_date": body.due_date.isoformat(), "asset_id": target_id,
                                 "asset_name": target_name}, actor["name"], conversation_id, run_id)
        action.update(_id=action_id, owner_id=owner["id"], created_by_id=actor["id"], request_snapshot=snapshot)
        action["history"][0].update(by_id=actor["id"], owner_id=owner["id"])
        saved = await store.insert_action_once(action)
    if saved["owner_id"] != body.owner_id or saved["due_date"] != body.due_date.isoformat():
        raise HTTPException(409, "A follow-up is already assigned for this run. Reload to see its owner and due date.")
    return actions.view(saved)


@router.patch("/actions")
async def update_assignment(conversation_id: str, run_id: str, req: Progress, store: StoreDep) -> dict:
    current = await store.get_artifact("actions", _action_id(conversation_id, run_id))
    if not current or current.get("conversation_id") != conversation_id or current.get("run_id") != run_id:
        raise HTTPException(404, "This run has no assigned follow-up.")
    return await apply_progress(current, req, _actor(active_owners()), store)
