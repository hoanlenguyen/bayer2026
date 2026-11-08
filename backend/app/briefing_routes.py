"""Team views, shared selections and source-linked follow-ups."""
from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from . import actions, briefings
from .store import Store

router = APIRouter(prefix="/api/briefings")


def _store(request: Request) -> Store:
    return request.app.state.pipeline.store


StoreDep = Annotated[Store, Depends(_store)]


class Selection(BaseModel):
    view_ids: list[briefings.ViewId] = Field(min_length=1, max_length=3)


class FollowUp(BaseModel):
    version: str = Field(pattern=r"^[0-9a-f]{16}$")
    view_id: briefings.ViewId | None = None
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=200)] | None = None
    owner_id: str = Field(pattern=r"^OWN-[0-9]{3}$")
    due_date: date
    market_id: str | None = Field(default=None, max_length=8)


class Verification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    result: Literal["improved", "not_improved", "confirmed"]
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] = ""


class Progress(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["open", "in_progress", "blocked", "done", "verified", "dismissed"]
    outcome: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)] | None = None
    blocker: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)] | None = None
    verification: Verification | None = None


@router.get("/{team}")
async def get_briefing(team: briefings.Team, store: StoreDep, market: str | None = None) -> dict[str, Any]:
    try:
        return await briefings.read_briefing(store, team, market)
    except ValueError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.put("/{team}/selection")
async def select_views(team: briefings.Team, selection: Selection, store: StoreDep, market: str | None = None) -> dict[str, Any]:
    ids = selection.view_ids
    if len(set(ids)) != len(ids):
        raise HTTPException(422, "Choose each report view only once.")
    await store.save_artifact("briefing_selections", {"_id": team, "view_ids": ids})
    return await get_briefing(team, store, market)


@router.post("/{team}/actions")
async def follow_up(team: briefings.Team, req: FollowUp, store: StoreDep) -> dict[str, Any]:
    try:
        return await briefings.save_followup(store, team, req.version, req.view_id, req.title, req.owner_id, req.due_date, req.market_id)
    except KeyError as exc:
        raise HTTPException(422, exc.args[0]) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.patch("/{team}/actions/{action_id}")
async def update_follow_up(team: briefings.Team, action_id: str, req: Progress, store: StoreDep) -> dict[str, Any]:
    current = await store.get_artifact("actions", action_id)
    if not current or current.get("briefing_snapshot", {}).get("team") != team:
        raise HTTPException(404, "This team has no such briefing action.")
    return await apply_progress(current, req, current["briefing_snapshot"]["actor"], store)


async def apply_progress(current: dict[str, Any], req: Progress, actor: dict[str, Any], store: Store) -> dict[str, Any]:
    """Apply an audited owner-work transition, preserving exact retries and rejecting conflicting edits."""
    fields = req.model_dump(exclude_none=True)
    for field, status in (("outcome", "done"), ("blocker", "blocked"), ("verification", "verified")):
        if field in fields and req.status != status:
            raise HTTPException(422, f"Supply {field} only with the {status} transition.")
    if current["status"] != req.status:
        try:
            updated = actions.apply_update(current, fields, actor["name"])
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        updated["history"][-1]["by_id"] = actor["id"]
        if req.status == "verified":
            updated["verify"]["checked_by_id"] = actor["id"]
        if await store.replace_briefing_action(updated, current["history"]):
            return actions.view(updated)
        current = await store.get_artifact("actions", current["_id"])

    # An identical retry can return the committed result. A conflicting writer must reload.
    if current:
        verification = current.get("verify") or {}
        committed = {**current, "verification": {key: verification.get(key) for key in ("result", "note")}}
        if all(committed.get(key) == value for key, value in fields.items()):
            return actions.view(current)
    raise HTTPException(409, "This action already changed. Reload its history before recording another update.")
