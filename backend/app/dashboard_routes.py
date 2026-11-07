"""Clarify, approve and reopen a source-backed dashboard from a saved Ask run."""
from typing import Any

from fastapi import APIRouter, HTTPException, Request as HttpRequest
from pydantic import BaseModel, ConfigDict, Field

from . import catalog
from .actions import now
from .bi_estate import creator_for_build
from .briefing_routes import StoreDep
from .dashboard_builder import assemble, build_receipt, check_reuse, fingerprint, resolve, validate_answer
from .request_handoff import _saved_run

router = APIRouter()
PATH = "/api/conversations/{conversation_id}/runs/{run_id}/dashboard"


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=0)
    key: str = Field(min_length=1, max_length=40)
    value: str | list[str] | dict[str, str]


class Build(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=0)
    review_token: str = Field(min_length=1, max_length=128)


def _guided_summary(req, artifact):
    """The reviewable brief for a guided example: what was chosen, what will be built, and from which rows."""
    C = catalog.CATALOG
    names = [C["markets"][m]["name"] for m in req["markets"]]
    lead = req["lead_measure"]
    kpis = sorted(artifact["columns"], key=lambda c: c["id"] != lead)
    rows = artifact["source_records"]
    actual = sum(r["value_type"] == "actual_like_synthetic" for r in rows)
    months = len({r["month"][:7] for r in rows})
    receipt = build_receipt(artifact)
    from .guided_examples import _month_label
    unit = lambda u: "€m" if u in ("M EUR", "EUR") else u
    return [f"Purpose: {req['decision_goal']}",
            f"Product: {', '.join(C['products'][k]['name'] for k in req['products'])} · Countries: {' and '.join(names)}, shown side by side",
            "KPIs: " + "; ".join(f"{c['name']} ({c['kpi_id']}, {unit(c['unit'])}){' · lead metric' if c['id'] == lead else ''}" for c in kpis),
            f"Months: {_month_label(receipt['first_month'])} to {_month_label(receipt['last_month'])}, {months} monthly points per country",
            f"Source: {artifact['source']}, {len(rows)} rows ({actual} actual-like and {len(rows) - actual} forecast-like synthetic)",
            f"Visuals: {receipt['arrangement']}"]


def _summary(req, artifact=None):
    C = catalog.CATALOG
    if artifact and req.get("presentation"):
        return _guided_summary(req, artifact)
    lines = []
    if req.get("decision_goal"):
        lines.append(req["decision_goal"])
    if req.get("measures"):
        lines.append("Measures: " + ", ".join(C["measures"].get(k, {}).get("name", k) for k in req["measures"]))
    if req.get("omitted_measures"):
        lines.append("Outside this dashboard: " + ", ".join(C["measures"].get(k, {}).get("name", k) for k in req["omitted_measures"]))
    for key in ("products", "markets"):
        if req.get(key):
            lines.append(key.capitalize() + ": " + ", ".join(C[key][k]["name"] for k in req[key]))
    if req.get("period"):
        lines.append(f"Monthly, {req['period']['start']} through {req['period']['end']}")
    if req.get("dimensions"):
        lines.append("Breakdown: " + ", ".join(req["dimensions"]))
    if artifact:
        lines.extend(f"{c['name']}: {c['aggregation']}" for c in artifact["columns"])
        rows = artifact["source_records"]
        actual = sum(r["value_type"] == "actual_like_synthetic" for r in rows)
        lines.append(f"{len(rows)} rows from {artifact['source']}: {actual} actual-like and {len(rows) - actual} forecast-like synthetic observations.")
    return lines


async def _state(conversation_id, run_id, store):
    draft_id = fingerprint([conversation_id, run_id])[:32]
    doc = await store.get_artifact("dashboard_drafts", draft_id) or {"_id": draft_id, "version": 0, "answers": {}}
    if doc.get("built_id"):
        return {**doc["built_state"], "storage_mode": store.name}, doc, None
    run, request = await _saved_run(store, conversation_id, run_id)
    events = run.get("events", [])
    stages = {e["stage"]: e.get("data") or {} for e in events if e.get("type") == "stage" and e.get("status") == "done"}
    decision = stages.get("decision") or {}
    if not decision.get("decision"):
        raise HTTPException(409, "This run has no completed recommendation.")
    turns = [e["content"] for i, e in enumerate(events) if e.get("type") == "user_message"
             and not (i + 1 < len(events) and events[i + 1].get("rejected"))]
    intent_stage = stages.get("intent") or {}
    # A guided run's answers are offered choices, not text to read for scope or format: check only its starter text.
    text = request if (intent_stage.get("dashboard_brief") or {}).get("guided") else "\n".join(turns or [request])
    req, question, reason = resolve(intent_stage, decision["decision"], doc["answers"], text)
    verdict = decision["decision"]
    state = {"status": "blocked" if reason else "clarifying", "version": doc["version"], "verdict": verdict,
             "request": request, "requirements": req, "question": question, "reason": reason, "dashboard_id": None,
             "review_token": None, "reuse_url": None, "reused": False, "summary": _summary(req), "storage_mode": store.name}
    if reason or question:
        return state, doc, None
    reason, link = check_reuse(req)
    if reason:
        return {**state, "status": "blocked", "reason": reason, "reuse_url": link}, doc, None
    try:
        artifact = assemble(req, None, conversation_id, run_id, request)
    except ValueError as exc:
        return {**state, "status": "blocked", "reason": str(exc)}, doc, None
    # The review token fingerprints the approved content, so changed source rows or KPI definitions invalidate a review.
    # The dashboard identity adds this run: every newly approved run saves its own immutable dashboard, and a retry
    # within the same run returns that same one. Runs built before this rule keep the dashboard they were bound to.
    normalized = {k: sorted(v) if isinstance(v, list) and k != "dimensions" else v for k, v in req.items()}
    normalized["decision_goal"] = " ".join(req["decision_goal"].casefold().split())
    token = fingerprint([normalized, sorted(artifact["columns"], key=lambda c: c["id"]), artifact["source_records"]])
    did = "dash_" + fingerprint([token, conversation_id, run_id])[:28]
    artifact.update(id=did, review_token=token, requirements=req)
    existing = await store.get_artifact("dashboards", did)  # only this run's own earlier save can exist under this ID
    state.update(status="built" if existing else "ready", summary=_summary(req, artifact), review_token=token,
                 receipt=build_receipt(existing or artifact), guided=req.get("guided"),
                 dashboard_id=did if existing else None, reused=False)
    return state, doc, artifact


@router.get(PATH)
async def dashboard_brief(conversation_id: str, run_id: str, store: StoreDep) -> dict:
    state, _, _ = await _state(conversation_id, run_id, store)
    return state


@router.post(PATH + "/answers")
async def dashboard_answer(conversation_id: str, run_id: str, answer: Answer, store: StoreDep) -> dict:
    state, doc, _ = await _state(conversation_id, run_id, store)
    q = state["question"]
    if state["status"] != "clarifying" or answer.version != doc["version"] or not q or q["key"] != answer.key:
        raise HTTPException(409, "The brief changed. Reload the current question.")
    try:
        value = validate_answer(q, answer.value)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if answer.key == "metric_scope":
        value = {"keep": state["requirements"]["measures"], "omit": state["requirements"]["omitted_measures"]}
    new_doc = {**doc, "version": doc["version"] + 1, "answers": {**doc["answers"], answer.key: value}}
    if not await store.advance_dashboard(new_doc, doc["version"]):
        raise HTTPException(409, "Another answer was saved. Reload the brief.")
    return await dashboard_brief(conversation_id, run_id, store)


@router.post(PATH + "/build")
async def build_dashboard(conversation_id: str, run_id: str, request: Build, store: StoreDep, http: HttpRequest) -> dict:
    state, doc, artifact = await _state(conversation_id, run_id, store)
    if state.get("review_token") != request.review_token:
        raise HTTPException(409, "The reviewed requirements or source rows changed. Reload before building.")
    if doc.get("built_id"):
        return state
    if state["status"] not in ("ready", "built") or request.version != doc["version"] or not artifact:
        raise HTTPException(409, "The dashboard is not ready to build from this version.")
    # Who built it is recorded once, at first publication: a retry or a reused build keeps the original attribution.
    saved = await store.publish_dashboard_once({**artifact, "_id": artifact["id"], "created_at": now(),
                                                "created_by": creator_for_build(http)})
    same_run = (saved["conversation_id"], saved["run_id"]) == (conversation_id, run_id)
    if not same_run:  # cannot happen with run-scoped IDs; never bind another run's dashboard to this one
        raise HTTPException(409, "This dashboard belongs to another request. Reload the brief.")
    built = {**state, "status": "built", "version": doc["version"] + 1, "dashboard_id": saved["id"], "reused": False}
    if not await store.advance_dashboard({**doc, "version": built["version"], "built_id": saved["id"], "built_state": built}, doc["version"]):
        latest, _, _ = await _state(conversation_id, run_id, store)
        if latest.get("dashboard_id") == saved["id"]:
            return latest
        raise HTTPException(409, "The brief changed. Reload it to continue.")
    return built


@router.get("/api/dashboards")
async def dashboards(store: StoreDep) -> dict:
    records = await store.dashboard_directory()
    return {"items": [{**r, "url": f"/dashboards/{r['id']}"} for r in records], "storage_mode": store.name}


@router.get("/api/dashboards/{dashboard_id}")
async def opened_dashboard(dashboard_id: str, store: StoreDep) -> dict[str, Any]:
    saved = await store.get_artifact("dashboards", dashboard_id)
    if not saved:
        raise HTTPException(404, "No built dashboard has this ID.")
    return {**{k: v for k, v in saved.items() if k != "_id"}, "receipt": build_receipt(saved), "storage_mode": store.name}
