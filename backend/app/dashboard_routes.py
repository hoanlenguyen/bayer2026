"""Clarify, approve and reopen a source-backed dashboard from a saved Ask run."""
import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request as HttpRequest
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from . import catalog
from .actions import now
from .bi_estate import creator_for_build
from .briefing_routes import StoreDep
from .dashboard_builder import build_receipt, calculate, check_reuse, fingerprint, resolve, select_source, validate_answer
from .request_handoff import _saved_run

router = APIRouter()
log = logging.getLogger(__name__)
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


def _draft_id(conversation_id, run_id):
    return fingerprint([conversation_id, run_id])[:32]


def _token(req, source):
    """The review token fingerprints the approved content, so changed source rows or KPI definitions invalidate a review."""
    normalized = {k: sorted(v) if isinstance(v, list) and k != "dimensions" else v for k, v in req.items()}
    normalized["decision_goal"] = " ".join(req["decision_goal"].casefold().split())
    return fingerprint([normalized, sorted(source["columns"], key=lambda c: c["id"]), source["records"]])


def _dashboard_id(token, conversation_id, run_id):
    # Every newly approved run saves its own immutable dashboard, and a retry within the same run returns that same one.
    # Runs built before this rule keep the dashboard they were bound to (their draft's built_id).
    return "dash_" + fingerprint([token, conversation_id, run_id])[:28]


async def _brief(conversation_id, run_id, store):
    """This run's saved recommendation, current draft and approved requirements, without reading workbook rows.
    A run counts as built only through its committed draft binding (built_id), never from a dashboard record alone."""
    draft_id = _draft_id(conversation_id, run_id)
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
    return {**state, "status": "ready"}, doc, req


def _ready(state, req, artifact, token):
    return {**state, "status": "ready", "summary": _summary(req, artifact), "review_token": token,
            "receipt": build_receipt(artifact), "guided": req.get("guided"), "dashboard_id": None, "reused": False}


async def _state(conversation_id, run_id, store):
    """The reviewable brief: requirements, preview receipt and the review token for the current source evidence."""
    state, doc, req = await _brief(conversation_id, run_id, store)
    if not req:
        return state, doc, None
    try:
        source = select_source(req)
    except ValueError as exc:
        return {**state, "status": "blocked", "reason": str(exc)}, doc, None
    token = _token(req, source)
    did = _dashboard_id(token, conversation_id, run_id)
    artifact = calculate(req, source, did, conversation_id, run_id, state["request"])
    artifact.update(id=did, review_token=token, requirements=req)
    return _ready(state, req, artifact, token), doc, artifact


class BuildError(Exception):
    """A build that cannot finish. `kind` tells the client what to offer: review (reload the brief), retry, reload."""
    def __init__(self, status: int, message: str, kind: str = "review") -> None:
        super().__init__(message)
        self.status, self.message, self.kind = status, message, kind


def _stage(phase, status, **facts):
    return {"type": "build_stage", "phase": phase, "status": status, **({"facts": facts} if facts else {})}


def _month(period):
    from .guided_examples import _month_label
    return _month_label(period)


async def build_events(conversation_id, run_id, version, review_token, store, creator):
    """The one approved-build path: each checkpoint is announced before its work and completed with that work's facts.
    Ends with exactly one `build_result` (the committed, bound state) or raises BuildError. JSON and SSE share it."""
    import asyncio
    yield _stage("brief", "running")
    try:
        state, doc, req = await _brief(conversation_id, run_id, store)
    except HTTPException as exc:
        raise BuildError(exc.status_code, exc.detail, "reload" if exc.status_code == 404 else "review") from exc
    if doc.get("built_id"):  # already committed: return the real result without replaying work it did not do
        if state.get("review_token") != review_token:
            raise BuildError(409, "The reviewed requirements or source rows changed. Reload before building.")
        yield {"type": "build_result", "state": state, "replayed": True}
        return
    reserved = doc.get("reserved") or {}
    same_approval = reserved.get("token") == review_token and version in (doc["version"], reserved.get("from_version"))
    if not req or (version != doc["version"] and not same_approval):
        raise BuildError(409, "The dashboard is not ready to build from this version.")
    C = catalog.CATALOG
    yield _stage("brief", "complete", products=[C["products"][k]["name"] for k in req["products"]],
                 markets=[C["markets"][k]["name"] for k in req["markets"]], period=req["period"],
                 measures=[C["measures"].get(k, {}).get("name", k) for k in req["measures"]])

    yield _stage("source", "running")
    try:
        source = await asyncio.to_thread(select_source, req)
    except ValueError as exc:
        raise BuildError(409, str(exc)) from exc
    token = _token(req, source)
    if token != review_token:
        raise BuildError(409, "The reviewed requirements or source rows changed. Reload before building.")
    rows = source["records"]
    actual = sum(r["value_type"] == "actual_like_synthetic" for r in rows)
    yield _stage("source", "complete", sheet="Product_Market_Monthly", months=len(source["months"]),
                 first=_month(source["months"][0]), last=_month(source["months"][-1]),
                 rows=len(rows), actual_like=actual, forecast_like=len(rows) - actual)

    yield _stage("calculate", "running")
    did = _dashboard_id(token, conversation_id, run_id)
    artifact = await asyncio.to_thread(calculate, req, source, did, conversation_id, run_id, state["request"])
    artifact.update(id=did, review_token=token, requirements=req)
    receipt = build_receipt(artifact)
    yield _stage("calculate", "complete", groups=[g["label"] for g in artifact["groups"]],
                 points=sum(len(g["points"]) for g in artifact["groups"]),
                 measures=[f"{c['name']} ({c['kpi_id']})" for c in artifact["columns"]],
                 layout=receipt.get("layout"), arrangement=receipt["arrangement"])

    yield _stage("save", "running")
    # Reserve this approval on the draft first, so competing approvals of one run converge on one dashboard.
    if not same_approval:
        claim = {**doc, "version": doc["version"] + 1, "reserved": {"token": token, "id": did, "from_version": doc["version"]}}
        if await store.advance_dashboard(claim, doc["version"]):
            doc = claim
        else:
            doc = await store.get_artifact("dashboard_drafts", doc["_id"]) or {}
            if doc.get("built_id") == did:
                yield {"type": "build_result", "state": {**doc["built_state"], "storage_mode": store.name}, "replayed": True}
                return
            if (doc.get("reserved") or {}).get("token") != token:
                raise BuildError(409, "Another answer was saved. Reload the brief.")
    # Who built it is recorded once, at first publication: a retry keeps the original attribution.
    saved = await store.publish_dashboard_once({**artifact, "_id": did, "created_at": now(), "created_by": creator})
    if (saved["conversation_id"], saved["run_id"]) != (conversation_id, run_id):
        raise BuildError(409, "This dashboard belongs to another request. Reload the brief.")
    built = {**_ready(state, req, artifact, token), "status": "built", "version": doc["version"] + 1,
             "dashboard_id": saved["id"], "receipt": build_receipt(saved)}
    bound = {**{k: v for k, v in doc.items() if k != "reserved"}, "version": built["version"], "built_id": saved["id"], "built_state": built}
    await store.advance_dashboard(bound, doc["version"])
    # Success only from the committed binding, read back: a published record alone proves nothing.
    committed = await store.get_artifact("dashboard_drafts", doc["_id"]) or {}
    if committed.get("built_id") != saved["id"]:
        raise BuildError(409, "The brief changed while saving. Reload it to continue.")
    result = {**committed["built_state"], "storage_mode": store.name}
    yield _stage("save", "complete", dashboard_id=saved["id"], title=saved["title"])
    yield {"type": "build_result", "state": result, "replayed": False}


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
async def build_dashboard(conversation_id: str, run_id: str, request: Build, store: StoreDep, http: HttpRequest) -> Any:
    """Build the approved dashboard. JSON by default (unchanged contract and HTTP errors); with `Accept: text/event-stream`
    the same operation streams `build_stage` checkpoints and ends with one `build_result` or `build_error`."""
    events = build_events(conversation_id, run_id, request.version, request.review_token, store, creator_for_build(http))
    if "text/event-stream" in (http.headers.get("accept") or ""):
        return StreamingResponse(_sse(events), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    try:
        async for ev in events:
            if ev["type"] == "build_result":
                return ev["state"]
    except BuildError as exc:
        raise HTTPException(exc.status, exc.message) from exc
    raise HTTPException(500, "The build ended without a result.")


async def _sse(events):
    def frame(ev):
        return f"event: {ev['type']}\ndata: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"
    try:
        async for ev in events:
            yield frame(ev)
    except BuildError as exc:  # known outcome after the headers went out: an in-stream error with its recovery
        yield frame({"type": "build_error", "kind": exc.kind, "status": exc.status, "message": exc.message})
    except Exception:
        log.exception("dashboard build failed")
        yield frame({"type": "build_error", "kind": "retry", "status": 500,
                     "message": "The dashboard could not be saved. Check it again before trying once more."})


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
