"""HTTP API. Pipeline progress is streamed to the browser as Server-Sent Events."""
from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from . import catalog as cat
from .llm import get_provider
from .pipeline import STAGES, Pipeline
from .settings import settings
from .store import create_store

logging.basicConfig(level=logging.INFO)


class ChatRequest(BaseModel):
    conversation_id: str | None = None
    message: str = ""
    preset_id: str | None = None


class ApprovalRequest(BaseModel):
    conversation_id: str
    approved: bool = True
    approver: str = Field(default="Report owner", max_length=80)


@asynccontextmanager
async def lifespan(app: FastAPI):
    store = await create_store()
    app.state.pipeline = Pipeline(store, get_provider())
    yield


app = FastAPI(title="Agentic Analytics Manager", version="0.1.0", lifespan=lifespan)
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


@app.post("/api/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    if not req.message.strip() and not req.preset_id:
        raise HTTPException(400, "Send a message or choose a preset.")
    return stream(pipeline().chat(req.conversation_id, req.message, req.preset_id))


@app.post("/api/approve")
async def approve(req: ApprovalRequest) -> StreamingResponse:
    return stream(pipeline().approve(req.conversation_id, req.approved, req.approver))


@app.get("/api/conversations")
async def conversations() -> list[dict[str, Any]]:
    return await pipeline().store.list()


@app.get("/api/conversations/{conv_id}")
async def conversation(conv_id: str) -> dict[str, Any]:
    conv = await pipeline().store.get(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    return conv
