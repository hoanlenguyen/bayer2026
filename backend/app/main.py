"""HTTP API. Pipeline progress is streamed to the browser as Server-Sent Events."""
from __future__ import annotations

import json
import logging
import io
import zipfile
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field, ConfigDict

from . import actions as act
from . import catalog as cat
from .graph import build_graph
from .llm import get_llm
from .pipeline import STAGES, Pipeline
from .settings import settings
from .store import create_store
from .governance import ACTORS, actor_for, issue_session, require_actor, require_review, check_request_access, audit, source_digest, spec_digest

logging.basicConfig(level=logging.INFO)


class ChatRequest(BaseModel):
    conversation_id: str | None = None
    message: str = ""
    preset_id: str | None = None
    submission_id: str | None = Field(default=None, min_length=8, max_length=80)
    expected_revision: int | None = None


class ActionCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    kind: str = "business"
    owner_id: str
    due_date: str | None = None
    reason: str = ""
    asset_id: str | None = None
    asset_name: str | None = None
    key: str | None = None
    verify: dict[str, Any] | None = None
    conversation_id: str | None = None


class ActionUpdate(BaseModel):
    status: str | None = None
    owner_id: str | None = None
    version: int
    due_date: str | None = None
    blocker: str | None = None
    outcome: str | None = None
    verification: dict[str, Any] | None = None
    model_config = ConfigDict(extra="forbid")


class ApprovalRequest(BaseModel):
    conversation_id: str
    approved: bool = True
    spec_hash: str
    model_config = ConfigDict(extra="forbid")


@asynccontextmanager
async def lifespan(app: FastAPI):
    store = await create_store()
    await cat.init(store)
    app.state.pipeline = Pipeline(store, get_llm())
    yield
    if getattr(store, "connection", None):
        store.connection.close()


app = FastAPI(title="Agentic Analytics Manager", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def demo_identity(request: Request, call_next):
    if request.url.path.startswith("/api/") and request.url.path not in ("/api/health", "/api/session") and request.method != "OPTIONS":
        try:
            request.state.actor = require_actor(request)
        except HTTPException as exc:
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    return await call_next(request)


class DemoSessionRequest(BaseModel):
    actor_id: str
    model_config = ConfigDict(extra="forbid")


@app.get("/api/session")
async def demo_actors():
    from .governance import demo_enabled
    if not demo_enabled():
        raise HTTPException(503, "Production identity integration is not configured.")
    return {"demo": True, "actors": [actor_for(i) for i in ACTORS],
            "notice": "Synthetic demo role switching, not Bayer authentication. All actors may inspect the synthetic estate."}


@app.post("/api/session")
async def demo_session(req: DemoSessionRequest):
    return issue_session(req.actor_id)


async def checked_conversation(conv_id: str, actor: dict):
    conv = await pipeline().store.get(conv_id)
    if not conv:
        raise HTTPException(404, "Request not found")
    check_request_access(conv, actor)
    return conv


async def locked_events(events):
    async with pipeline().mutation_lock:
        async for event in events:
            yield event


def pipeline() -> Pipeline:
    return app.state.pipeline


async def sse(events: AsyncIterator[dict[str, Any]]) -> AsyncIterator[str]:
    try:
        async for ev in events:
            yield f"event: {ev['type']}\ndata: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"
    except Exception as exc:  # report instead of silently closing the stream
        logging.exception("pipeline failed")
        yield f"event: error\ndata: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"


def stream(events: AsyncIterator[dict[str, Any]]) -> StreamingResponse:
    return StreamingResponse(sse(events), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/health")
async def health() -> dict[str, Any]:
    p = pipeline()
    return {"ok": True, "provider": p.llm.name, "store": p.store.name,
            "models": {"reasoning": settings.model_reasoning, "fast": settings.model_fast} if p.llm.name == "openai" else None}


@app.get("/api/presets")
async def presets() -> list[dict[str, Any]]:
    return cat.PRESETS


@app.get("/api/stages")
async def stages() -> dict[str, str]:
    return STAGES


@app.get("/api/catalog")
async def catalog() -> dict[str, Any]:
    return cat.CATALOG


@app.get("/api/requests")
async def business_requests() -> list[dict[str, Any]]:
    """The 150 synthetic business requests from the data pack."""
    return cat.SHEETS.get("business_requests", [])


@app.get("/api/datapack")
async def datapack_summary() -> dict[str, Any]:
    """What was loaded from the Bayer data pack."""
    C = cat.CATALOG
    return {"source": C.get("source"), "sheets": {k: len(v) for k, v in cat.SHEETS.items()},
            "assets": len(C["assets"]), "models": len(C["models"]), "measures": len(C["measures"]),
            "usage_window": C.get("usage_window"), "rules": C.get("rules")}


@app.get("/api/graph")
async def graph(request: Request) -> dict[str, Any]:
    """Entities and relationships for the Estate Explorer, built from the live catalog."""
    actions = await pipeline().store.list_artifacts("actions", limit=500)
    requests = []
    for item in await pipeline().store.list(500):
        conv = await pipeline().store.get(item["_id"])
        if request.state.actor["can_review"] or conv.get("requester_id") == request.state.actor["id"]:
            requests.append(conv)
    return build_graph(actions, requests)


@app.get("/api/specs")
async def specs(request: Request, conversation_id: str | None = None) -> list[dict[str, Any]]:
    if conversation_id:
        await checked_conversation(conversation_id, request.state.actor)
    records = await pipeline().store.list_artifacts("specs", conversation_id)
    return await filter_request_records(records, request.state.actor)


@app.get("/api/actions")
async def list_actions(status: str | None = None, kind: str | None = None, owner: str | None = None,
                       conversation_id: str | None = None) -> dict[str, Any]:
    items = await pipeline().store.list_artifacts("actions", conversation_id, limit=500)
    summary = act.summary(items)
    if status:
        items = [a for a in items if a["status"] in status.split(",")]
    if kind:
        items = [a for a in items if a["kind"] == kind]
    if owner:
        items = [a for a in items if a["owner"] == owner]
    return {"items": [act.view(a) for a in items], "summary": summary}


@app.post("/api/actions", status_code=201)
async def create_action(req: ActionCreate, request: Request) -> dict[str, Any]:
    async with pipeline().mutation_lock:
        return await _create_action(req, request)


def active_owner(owner_id):
    owner = cat.CATALOG["owners"].get(owner_id)
    if not owner or owner.get("status") != "active":
        raise HTTPException(400, "Choose an active owner ID from the registry.")
    return owner["owner_name"]


async def _create_action(req: ActionCreate, request: Request) -> dict[str, Any]:
    store = pipeline().store
    if req.conversation_id:
        await checked_conversation(req.conversation_id, request.state.actor)
    if req.key:
        existing = await store.list_artifacts("actions", limit=500)
        dup = next((a for a in existing if a.get("key") == req.key and a["status"] not in act.CLOSED), None)
        if dup:
            raise HTTPException(409, f"An open action already covers this: '{dup['title']}' ({dup['_id']}).")
    run_id = None
    if req.conversation_id:
        conv = await store.get(req.conversation_id)
        run_id = conv["runs"][-1]["id"] if conv and conv.get("runs") else None
    try:
        payload = {**req.model_dump(exclude={"conversation_id"}), "owner": active_owner(req.owner_id)}
        action = act.create(payload, request.state.actor["id"], req.conversation_id, run_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    action.update(owner_id=req.owner_id, version=1)
    await store.save_artifact("actions", action)
    await audit(store, request.state.actor["id"], action["_id"], "action_created", conversation_id=req.conversation_id)
    return act.view(action)


@app.get("/api/actions/{action_id}")
async def get_action(action_id: str) -> dict[str, Any]:
    action = await pipeline().store.get_artifact("actions", action_id)
    if not action:
        raise HTTPException(404, "Action not found")
    return act.view(action)


@app.patch("/api/actions/{action_id}")
async def update_action(action_id: str, req: ActionUpdate, request: Request) -> dict[str, Any]:
    async with pipeline().mutation_lock:
        return await _update_action(action_id, req, request)


async def _update_action(action_id: str, req: ActionUpdate, request: Request) -> dict[str, Any]:
    store = pipeline().store
    action = await store.get_artifact("actions", action_id)
    if not action:
        raise HTTPException(404, "Action not found")
    actor = request.state.actor
    if not actor["can_review"] and action.get("owner_id") != actor["id"] and action.get("created_by") != actor["id"]:
        raise HTTPException(403, "Only the responsible actor or reviewer may change this action.")
    if req.version != action.get("version", 1):
        raise HTTPException(409, "This action changed. Reload it before saving.")
    changes = req.model_dump(exclude={"version", "owner_id"}, exclude_none=True)
    if req.owner_id:
        changes["owner"] = active_owner(req.owner_id)
    try:
        updated = act.apply_update(action, changes, actor["id"])
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    updated.update(owner_id=req.owner_id or action.get("owner_id"), version=req.version + 1)
    await store.save_artifact("actions", updated)
    await audit(store, actor["id"], action_id, "action_updated", previous_state=action["status"], new_state=updated["status"],
                version=updated["version"], changes=req.model_dump(exclude_none=True))
    return act.view(updated)


@app.get("/api/agent-runs")
async def agent_runs(request: Request, conversation_id: str | None = None) -> list[dict[str, Any]]:
    """Audit log of every agent run: mode, model, steps and duration."""
    if conversation_id:
        await checked_conversation(conversation_id, request.state.actor)
    return await filter_request_records(await pipeline().store.list_artifacts("agent_runs", conversation_id), request.state.actor)


@app.post("/api/chat")
async def chat(req: ChatRequest, request: Request) -> StreamingResponse:
    if not req.message.strip() and not req.preset_id:
        raise HTTPException(400, "Send a message or choose a preset.")
    if req.conversation_id:
        conv = await checked_conversation(req.conversation_id, request.state.actor)
        if req.expected_revision is None:
            raise HTTPException(409, "Include the request revision before editing this request.")
    return stream(submit_request(req, request.state.actor))


async def submit_request(req: ChatRequest, actor: dict):
    from .governance import digest
    async with pipeline().mutation_lock:
        key = actor["id"] + ":" + req.submission_id if req.submission_id else None
        request_hash = digest(req.model_dump(exclude={"submission_id"}))
        existing = await pipeline().store.get_artifact("submissions", key) if key else None
        if existing:
            if existing["request_hash"] != request_hash:
                raise HTTPException(409, "Submission ID already used for different requirements.")
            for event in existing["events"]:
                yield event
            return
        if req.conversation_id:
            conv = await checked_conversation(req.conversation_id, actor)
            if conv.get("revision", 1) != req.expected_revision:
                raise HTTPException(409, "This request changed. Reload before reassessing.")
        events = []
        async for event in pipeline().chat(req.conversation_id, req.message, req.preset_id, actor):
            events.append(event)
            yield event
        if key:
            await pipeline().store.save_artifact("submissions", {"_id": key, "request_hash": request_hash, "events": events})


@app.post("/api/approve")
async def approve(req: ApprovalRequest, request: Request) -> StreamingResponse:
    conv = await checked_conversation(req.conversation_id, request.state.actor)
    require_review(request.state.actor, conv.get("requester_id"))
    plan = conv.get("plan") or {}
    if not plan.get("spec") or req.spec_hash != plan.get("spec_hash") or req.spec_hash != spec_digest(plan["spec"]):
        raise HTTPException(409, "This specification version is stale or missing. Reload the request.")
    if not plan.get("approval") and (conv["state"] != "awaiting_approval" or plan.get("source_hash") != source_digest()):
        raise HTTPException(409, "The source changed. Reassess the request before review.")
    return stream(locked_events(pipeline().approve(req.conversation_id, req.approved, request.state.actor, req.spec_hash)))


@app.get("/api/conversations")
async def conversations(request: Request) -> list[dict[str, Any]]:
    result = []
    for item in await pipeline().store.list(500):
        conv = await pipeline().store.get(item["_id"])
        if request.state.actor["can_review"] or conv.get("requester_id") == request.state.actor["id"]:
            result.append({**item, "state": conv["state"], "request_state": conv.get("request_state", conv["state"]),
                           "requester_id": conv.get("requester_id"), "revision": conv.get("revision", 1)})
    return result


@app.get("/api/conversations/{conv_id}")
async def conversation(conv_id: str, request: Request) -> dict[str, Any]:
    return await checked_conversation(conv_id, request.state.actor)


@app.get("/api/source")
async def source_metadata():
    from .workbook_source import metadata
    return metadata()


@app.get("/api/source/{sheet}")
async def source_records(sheet: str, offset: int = 0, limit: int = 50, row: int | None = None):
    from .workbook_source import records, snapshot, source
    snap=snapshot()
    if sheet not in snap["sheets"]:
        raise HTTPException(404, "Worksheet not found.")
    if offset < 0 or not 1 <= limit <= 200:
        raise HTTPException(400, "Use a nonnegative offset and a limit from 1 to 200.")
    table=snap["sheets"][sheet]; values=records(sheet)
    if row == 1 and table["layout"] == "table":
        selected=[{"columns":table["columns"],"_source":source(sheet,1)}]
    else:
        selected=[r for r in values if r["_source"]["row"]==row] if row is not None else values[offset:offset+limit]
    if row is not None and not selected:
        raise HTTPException(404,"Source row not found.")
    return {"sheet":sheet,"columns":table["columns"],"rows":selected,"total":len(values),"offset":offset,"limit":limit,"snapshot":snap["sha256"]}


async def filter_request_records(records, actor):
    if actor["can_review"]:
        return records
    result = []
    for row in records:
        conv = await pipeline().store.get(row.get("conversation_id"))
        if conv and conv.get("requester_id") == actor["id"]:
            result.append(row)
    return result


@app.get("/api/outputs/{output_id}/download")
async def download_output(output_id: str, request: Request):
    output = await pipeline().store.get_artifact("outputs", output_id)
    if not output:
        raise HTTPException(404, "Output not found")
    await checked_conversation(output["conversation_id"], request.state.actor)
    root = (settings.output_dir / output["output"]["folder"]).resolve()
    if not root.is_relative_to(settings.output_dir.resolve()) or not root.is_dir():
        raise HTTPException(404, "Artifact files are unavailable on this host")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for item in output["output"]["files"]:
            path = (root / item["path"]).resolve()
            if not path.is_relative_to(root):
                raise HTTPException(400, "Invalid artifact path")
            archive.write(path, item["path"])
    buffer.seek(0)
    return StreamingResponse(buffer, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="Bayer-demo-{output_id}.zip"'})


@app.get("/api/audit")
async def audit_events(request: Request):
    require_review(request.state.actor)
    return await pipeline().store.list_artifacts("audit", limit=1000)
