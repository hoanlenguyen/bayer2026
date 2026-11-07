"""HTTP API. Pipeline progress is streamed to the browser as Server-Sent Events."""
from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from . import actions as act
from . import catalog as cat
from . import guided_examples
from .bi_estate import router as bi_estate_router
from .governance import router as governance_router
from .briefing_routes import router as briefing_router
from .dashboard_routes import router as dashboard_router
from .report_register import router as report_register_router
from .request_handoff import router as request_handoff_router
from .graph import build_graph
from .decider import get_decider
from .llm import get_llm
from .pipeline import STAGES, Pipeline
from .settings import settings
from .simulator import turn
from .store import create_store

logging.basicConfig(level=logging.INFO)


class ChatRequest(BaseModel):
    conversation_id: str | None = None
    message: str = ""
    preset_id: str | None = None
    guided_id: str | None = None   # a guided example chip on the start screen
    choice_id: str | None = None   # an offered answer in a guided example


class ActionCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    kind: str = "business"
    owner: str = Field(min_length=1, max_length=80)
    due_date: str | None = None
    reason: str = ""
    asset_id: str | None = None
    asset_name: str | None = None
    key: str | None = None
    verify: dict[str, Any] | None = None
    conversation_id: str | None = None
    by: str = "You"


class ActionUpdate(BaseModel):
    status: str | None = None
    owner: str | None = None
    due_date: str | None = None
    blocker: str | None = None
    outcome: str | None = None
    verification: dict[str, Any] | None = None
    by: str = "You"


class ClassifyRequest(BaseModel):
    request: str = Field(max_length=2000)


class SimulatorMessage(BaseModel):
    speaker: Literal["A", "B", "C"]
    text: str = Field(max_length=2000)
    label: str | None = None        # what the gate decided about this sentence
    kind: str | None = None         # C only: "question" or "answer"
    answer_key: str | None = None   # C only: lets the system avoid repeating itself


class SimulatorTurn(BaseModel):
    speaker: Literal["A", "B"]
    text: str = Field(max_length=2000)
    history: list[SimulatorMessage] = Field(default_factory=list, max_length=200)


@asynccontextmanager
async def lifespan(app: FastAPI):
    store = await create_store()
    await cat.init(store)
    app.state.pipeline = Pipeline(store, get_llm(), get_decider())
    yield


app = FastAPI(title="AnalytIQ intelligence", version="0.1.0", lifespan=lifespan)
app.include_router(bi_estate_router)
app.include_router(governance_router)
app.include_router(briefing_router)
app.include_router(dashboard_router)
app.include_router(report_register_router)
app.include_router(request_handoff_router)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])


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
    return {"ok": True, "provider": p.llm.name, "store": p.store.name, "jev": p.gate_agent.jev_on(),
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


@app.get("/api/requests/similar")
async def requests_similar(q: str, k: int = 30) -> dict[str, Any]:
    """Earlier Business_Requests that ask the same thing as `q` (vector search)."""
    from .vectors import similar_requests

    return await similar_requests(pipeline().vectors, q, k)


@app.get("/api/requests/clusters")
async def requests_clusters() -> dict[str, Any]:
    """The intake queue grouped into distinct asks, with the dataset's label mix per group."""
    from .vectors import request_clusters

    clusters = await request_clusters(pipeline().vectors)
    return {"requests": sum(c["count"] for c in clusters), "distinct_asks": len(clusters), "clusters": clusters,
            "embedder": pipeline().vectors.embedder.name}


@app.get("/api/requests/label-check")
async def requests_label_check() -> dict[str, Any]:
    """How predictable urgency and status are from the request text (why triage uses rules, not a classifier)."""
    from .triage import label_predictability

    return label_predictability(cat.SHEETS.get("business_requests", []))


@app.get("/api/datapack")
async def datapack_summary() -> dict[str, Any]:
    """What was loaded from the SinceAI data pack."""
    C = cat.CATALOG
    return {"source": C.get("source"), "sheets": {k: len(v) for k, v in cat.SHEETS.items()},
            "assets": len(C["assets"]), "models": len(C["models"]), "measures": len(C["measures"]),
            "usage_window": C.get("usage_window"), "rules": C.get("rules")}


@app.get("/api/graph")
async def graph() -> dict[str, Any]:
    """Entities and relationships for the Estate Explorer, built from the live catalog."""
    return build_graph()


@app.get("/api/specs")
async def specs(conversation_id: str | None = None) -> list[dict[str, Any]]:
    return await pipeline().store.list_artifacts("specs", conversation_id)


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
async def create_action(req: ActionCreate) -> dict[str, Any]:
    store = pipeline().store
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
        action = act.create(req.model_dump(exclude={"by", "conversation_id"}), req.by, req.conversation_id, run_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    await store.save_artifact("actions", action)
    return act.view(action)


@app.get("/api/actions/{action_id}")
async def get_action(action_id: str) -> dict[str, Any]:
    action = await pipeline().store.get_artifact("actions", action_id)
    if not action:
        raise HTTPException(404, "Action not found")
    return act.view(action)


@app.patch("/api/actions/{action_id}")
async def update_action(action_id: str, req: ActionUpdate) -> dict[str, Any]:
    store = pipeline().store
    action = await store.get_artifact("actions", action_id)
    if not action:
        raise HTTPException(404, "Action not found")
    if action.get("briefing_snapshot"):
        raise HTTPException(409, "Update this action from its team briefing so the named actor and evidence stay linked.")
    if action.get("request_snapshot"):
        raise HTTPException(409, "Update this action from the saved Ask decision so its owner and evidence stay linked.")
    try:
        updated = act.apply_update(action, req.model_dump(exclude={"by"}, exclude_none=True), req.by)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    await store.save_artifact("actions", updated)
    return act.view(updated)


@app.get("/api/agent-runs")
async def agent_runs(conversation_id: str | None = None) -> list[dict[str, Any]]:
    """Audit log of every agent run: mode, model, steps and duration."""
    return await pipeline().store.list_artifacts("agent_runs", conversation_id)


@app.post("/api/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    if req.guided_id is not None:
        example = guided_examples.get(req.guided_id)
        if not example:
            raise HTTPException(400, "Unknown guided example.")
        if req.preset_id or req.choice_id or (req.message.strip() and req.message.strip() != example["text"]):
            raise HTTPException(400, "A guided example starts with its own text only.")
    elif not req.message.strip() and not req.preset_id and not req.choice_id:
        raise HTTPException(400, "Send a message or choose a preset.")
    if req.choice_id is not None and not req.conversation_id:
        raise HTTPException(400, "An answer needs the conversation it answers.")
    return stream(pipeline().chat(req.conversation_id, req.message, req.preset_id, req.guided_id, req.choice_id))


@app.get("/api/guided-examples")
async def guided_example_list() -> dict:
    """The start screen's guided dashboard examples, in order, with their offered choices."""
    return guided_examples.public()


@app.post("/api/v2/chat")
async def chat_v2(req: ChatRequest) -> dict[str, Any]:
    """Shows the input as the API understood it. Runs no agents and saves nothing, so it costs nothing to call."""
    message = req.message.strip()
    preset = cat.preset_by_id(req.preset_id)
    if not message and not req.preset_id:
        raise HTTPException(400, "Send a message or choose a preset.")
    if not message and not preset:
        raise HTTPException(400, f"Unknown preset: {req.preset_id}")
    question = message or preset["prompt"]
    return {"received": req.model_dump(), "question": question, "source": "message" if message else "preset",
            "length": len(question), "new_conversation": req.conversation_id is None}


@app.post("/api/v2/classify")
async def classify(req: ClassifyRequest) -> dict[str, Any]:
    """Tags for one business request. Runs no chat model and saves nothing; only the embedding is an outside call."""
    from .classify import classify_request

    text = req.request.strip()
    if not text:
        raise HTTPException(400, "Send a business request.")
    return await classify_request(text, pipeline().vectors, pipeline().decider)


@app.post("/api/simulator/turn")
async def simulator_turn(req: SimulatorTurn) -> StreamingResponse:
    """One sentence of the chat simulator. Streams what was decided, and C's message if it speaks. Saves nothing."""
    text = req.text.strip()
    if not text:
        raise HTTPException(400, "Send a sentence.")
    return stream(turn(pipeline(), req.speaker, text, [m.model_dump() for m in req.history]))


@app.get("/api/conversations")
async def conversations(limit: int = Query(50, ge=1, le=200)) -> list[dict[str, Any]]:
    return await pipeline().store.list(limit)


@app.delete("/api/conversations/{conv_id}", status_code=204)
async def delete_conversation(conv_id: str) -> None:
    """Removes a chat and what it produced. Accepted follow-up actions, SinceAI's data and the catalog stay."""
    if not await pipeline().store.delete(conv_id):
        raise HTTPException(404, "Conversation not found")
    await pipeline().vectors.remove_conversation_requests(conv_id)


@app.get("/api/conversations/{conv_id}")
async def conversation(conv_id: str) -> dict[str, Any]:
    conv = await pipeline().store.get(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    return conv
