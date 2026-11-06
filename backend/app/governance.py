"""Explicit synthetic-demo policy, versioned reviews and immutable audit events.

This is application policy, not a permission mapping supplied by Bayer.
All configured demo actors may read the shared synthetic estate. Only the
configured reviewer/publisher may review requests; requester identity never
comes from a display name in a mutation payload.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, Request

from . import catalog as cat
from .datapack import workbook_path

ACTORS = {"OWN-008": "requester", "OWN-022": "reviewer", "OWN-026": "publisher"}
REPORT_OWNER_ID = "OWN-039"
_SECRET = os.getenv("SESSION_SECRET") or secrets.token_hex(32)


def demo_enabled() -> bool:
    return os.getenv("DEMO_MODE", "true").lower() == "true"


def actor_for(actor_id: str) -> dict:
    owner = cat.CATALOG.get("owners", {}).get(actor_id)
    if actor_id not in ACTORS or not owner or owner.get("status") != "active":
        raise HTTPException(403, "This actor is not enabled by the demo permission policy.")
    return {"id": actor_id, "name": owner["owner_name"], "role": ACTORS[actor_id],
            "can_review": ACTORS[actor_id] in ("reviewer", "publisher"), "demo": True}


def issue_session(actor_id: str) -> dict:
    if not demo_enabled():
        raise HTTPException(503, "Demo sign-in is disabled. Configure a production identity adapter before use.")
    actor = actor_for(actor_id)
    data = base64.urlsafe_b64encode(json.dumps({"sub": actor_id, "exp": int(time.time()) + 28800}).encode()).decode()
    sig = hmac.new(_SECRET.encode(), data.encode(), hashlib.sha256).hexdigest()
    return {"token": data + "." + sig, "actor": actor, "policy": "Shared synthetic estate; explicit demo roles only"}


def require_actor(request: Request) -> dict:
    if not demo_enabled():
        raise HTTPException(503, "Production identity adapter is not configured; demo access is disabled.")
    token = request.headers.get("Authorization", "").removeprefix("Bearer ")
    try:
        data, sig = token.split(".")
        expected = hmac.new(_SECRET.encode(), data.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            raise ValueError("signature")
        payload = json.loads(base64.urlsafe_b64decode(data))
        if payload["exp"] < time.time():
            raise ValueError("expired")
        return actor_for(payload["sub"])
    except (ValueError, KeyError, TypeError):
        raise HTTPException(401, "Select a demo actor to start a signed session.")


def require_review(actor: dict, requester_id: str | None = None) -> None:
    if not actor.get("can_review") or actor["id"] == requester_id:
        raise HTTPException(403, "A different authorised demo reviewer must review this request.")


def check_request_access(conv: dict, actor: dict) -> None:
    if conv.get("requester_id") != actor["id"] and not actor.get("can_review"):
        raise HTTPException(403, "This request belongs to another requester.")


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def spec_digest(spec: dict) -> str:
    return digest({k: v for k, v in spec.items() if k not in {"approved_by", "approved_at", "approval"}})


def source_digest() -> str:
    # Conservative invalidation: any catalogue or workbook change requires review again.
    catalog = {**cat.CATALOG, "assets": [a for a in cat.CATALOG["assets"] if not a.get("created_from_spec") or a.get("artifact_state") == "published"]}
    return digest({"workbook": hashlib.sha256(workbook_path().read_bytes()).hexdigest(), "catalog": catalog})


async def audit(store, actor_id: str, object_id: str, event: str, **evidence) -> None:
    transitions = {
        "request_submitted": (None, "assessing"),
        "plan_approved": ("awaiting_review", "approved"), "plan_rejected": ("awaiting_review", "rejected"),
        "execution_blocked": ("approved", "execution_blocked"), "artifact_generated": ("approved", "validation_pending"),
        "generation_failed": ("approved", "generation_failed"), "action_created": (None, "open"),
    }
    previous, current = transitions.get(event, (None, None))
    await store.save_artifact("audit", {"_id": uuid.uuid4().hex, "actor_id": actor_id, "object_id": object_id,
        "event": event, "previous_state": previous, "new_state": current,
        "created_at": datetime.now(timezone.utc).isoformat(), **evidence})
