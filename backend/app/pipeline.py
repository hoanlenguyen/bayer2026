"""Orchestrates the processing flow and streams events to the UI.

Flow: intent agent → discovery → governance → decision
        → reuse: deliver
        → extend/create: evidence agent → spec agent → human approval → PBIP render → register
        → not feasible: explain

Agents propose; Python verifies and decides. Every stage emits ``stage`` events
(running / waiting / done) with a payload for the UI, and every agent run,
intent, evidence record and spec is saved for audit.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timezone
from typing import Any, AsyncIterator

from . import actions as act
from . import catalog as cat
from .agents import AgentRun, EvidenceAgent, IntentAgent, SpecAgent
from .agents.intent import sanitize_intent
from .decision import Decision, data_availability, decide, rank_candidates
from .llm import LLM, explain
from .pbip import render_pbip, slug
from .settings import settings
from .store import Store

STAGES = {
    "intent": "Understand the request",
    "discovery": "Find existing analytics",
    "governance": "Check governance",
    "decision": "Decide: reuse, extend or create",
    "actions": "Propose follow-up actions",
    "deliver": "Open the existing report",
    "evidence": "Gather evidence",
    "spec": "Write the specification",
    "approval": "Human approval",
    "render": "Generate PBIP files",
    "register": "Register in the catalog",
}

Event = dict[str, Any]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def public(intent: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in intent.items() if not k.startswith("_")}


def label_list(ids: list[str], kind: str) -> str:
    src = cat.CATALOG["measures" if kind == "m" else "dimensions"]
    return ", ".join(src[i]["name"] for i in ids if i in src)


class Pipeline:
    def __init__(self, store: Store, llm: LLM) -> None:
        self.store = store
        self.llm = llm
        self.intent_agent = IntentAgent(llm)
        self.evidence_agent = EvidenceAgent(llm)
        self.spec_agent = SpecAgent(llm)

    # ------------------------------------------------------------ helpers
    def _event(self, conv: dict[str, Any], type_: str, **data: Any) -> Event:
        ev = {"type": type_, "ts": now(), **data}
        if conv["runs"]:
            conv["runs"][-1]["events"].append(ev)
        return ev

    def _stage(self, conv: dict[str, Any], stage: str, status: str, summary: str = "", data: Any = None) -> Event:
        return self._event(conv, "stage", stage=stage, title=STAGES[stage], status=status, summary=summary, data=data)

    def _say(self, conv: dict[str, Any], text: str, **extra: Any) -> Event:
        msg = {"role": "assistant", "content": text, "ts": now(), **extra}
        conv["messages"].append(msg)
        return self._event(conv, "message", **msg)

    async def _pause(self) -> None:
        if settings.stage_delay:
            await asyncio.sleep(settings.stage_delay)

    async def _audit(self, conv: dict[str, Any], stage: str, run: AgentRun) -> None:
        await self.store.save_artifact("agent_runs", {
            "_id": uuid.uuid4().hex, "conversation_id": conv["_id"], "run_id": conv["runs"][-1]["id"],
            "stage": stage, "created_at": now(), **run.trace()})

    async def _artifact(self, conv: dict[str, Any], kind: str, body: dict[str, Any], **extra: Any) -> str:
        doc_id = uuid.uuid4().hex[:16]
        await self.store.save_artifact(kind, {"_id": doc_id, "conversation_id": conv["_id"], "run_id": conv["runs"][-1]["id"],
                                              "created_at": now(), **extra, "body": body})
        return doc_id

    async def _load(self, conv_id: str | None) -> dict[str, Any]:
        conv = await self.store.get(conv_id) if conv_id else None
        if conv:
            return conv
        return {"_id": conv_id or uuid.uuid4().hex[:12], "title": None, "created_at": now(), "updated_at": now(),
                "state": "idle", "messages": [], "intent": {}, "asked": 0, "preset_id": None, "plan": None, "runs": []}

    async def _save(self, conv: dict[str, Any]) -> None:
        conv["updated_at"] = now()
        await self.store.save(conv)

    # ------------------------------------------------------------ chat turn
    async def chat(self, conv_id: str | None, message: str, preset_id: str | None) -> AsyncIterator[Event]:
        conv = await self._load(conv_id)
        try:
            preset = cat.preset_by_id(preset_id)
            text = message.strip() or (preset["prompt"] if preset else "")
            conv["title"] = conv["title"] or text[:70]
            yield {"type": "conversation", "id": conv["_id"], "provider": self.llm.name, "store": self.store.name}

            new_run = conv["state"] != "clarifying"
            if new_run:
                if conv["state"] == "awaiting_approval" and conv.get("plan", {}).get("spec_id"):
                    await self.store.update_artifact("specs", conv["plan"]["spec_id"], {"status": "superseded"})
                conv["plan"] = None
                conv["runs"].append({"id": uuid.uuid4().hex[:8], "started_at": now(), "events": [],
                                     "msg_start": len(conv["messages"])})
                conv["preset_id"] = preset["id"] if preset else None
                conv["asked"] = 0
                conv["intent"] = {"question": text, "measures": [], "dimensions": [], "grain": None, "filters": {},
                                  "unmatched_terms": [], "decision": None}
                if preset:
                    conv["intent"].update(measures=list(preset["measures"]), dimensions=list(preset["dimensions"]),
                                          grain=preset["grain"], decision=preset["decision"],
                                          unmatched_terms=list(preset.get("requested_terms", [])),
                                          department=preset["department"])
            run = conv["runs"][-1]
            conv["messages"].append({"role": "user", "content": text, "ts": now(), "preset_id": conv["preset_id"]})
            yield self._event(conv, "user_message", content=text)
            if new_run:
                yield self._stage(conv, "intent", "running", "Intent agent is reading your request")
                await self._pause()

            # ---- 1. Intent agent (/grill-me)
            transcript = [{"role": m["role"], "content": m["content"]} for m in conv["messages"][run["msg_start"]:]]
            agent_run = await self.intent_agent.run({"transcript": transcript, "intent": conv["intent"], "asked": conv["asked"],
                                                     "preset": cat.preset_by_id(conv["preset_id"])})
            await self._audit(conv, "intent", agent_run)
            result = agent_run.output
            pending = result["intent"].get("_pending")
            intent = sanitize_intent(result["intent"])
            if pending:
                intent["_pending"] = pending
            conv["intent"] = intent

            if result["status"] == "ask" and result.get("question"):
                conv["asked"] += 1
                conv["state"] = "clarifying"
                yield self._stage(conv, "intent", "waiting", f"Question {conv['asked']} of up to 2",
                                  {**public(intent), "agent": agent_run.trace()})
                yield self._say(conv, result["question"], kind="question", suggestions=result.get("suggestions", []))
                yield self._event(conv, "done", state=conv["state"])
                return

            intent.pop("_pending", None)
            if not intent.get("grain"):
                first = intent["measures"][0] if intent["measures"] else None
                intent["grain"] = cat.measure(first)["default_grain"] if first else "day"
            intent["decision"] = intent.get("decision") or f"Monitor {label_list(intent['measures'], 'm') or 'the requested numbers'}"
            intent["department"] = intent.get("department") or cat.department_for(intent["measures"])
            conv["intent"] = intent
            await self._artifact(conv, "intents", public(intent), preset_id=conv["preset_id"])
            summary = (f"{label_list(intent['measures'], 'm') or 'No catalog measures'}"
                       f"{' by ' + label_list(intent['dimensions'], 'd') if intent['dimensions'] else ''}, per {intent['grain']}")
            yield self._stage(conv, "intent", "done", summary, {**public(intent), "agent": agent_run.trace()})
            await self._pause()

            async for ev in self._plan(conv):
                yield ev
        finally:
            await self._save(conv)

    # ------------------------------------------------------------ discovery → decision → branch
    async def _plan(self, conv: dict[str, Any]) -> AsyncIterator[Event]:
        intent = conv["intent"]

        # ---- 2. Discovery (catalog search + scoring)
        yield self._stage(conv, "discovery", "running", "Searching the catalog")
        await self._pause()
        candidates = rank_candidates(intent, cat.CATALOG["assets"])
        availability = data_availability(intent, cat.CATALOG)
        yield self._stage(conv, "discovery", "done",
                          f"{len(candidates)} related report{'s' if len(candidates) != 1 else ''} found in {len(cat.CATALOG['assets'])} catalog assets",
                          {"candidates": [c.to_dict() for c in candidates], "availability": availability,
                           "searched": len(cat.CATALOG["assets"])})
        await self._pause()

        # ---- 3. Governance check
        yield self._stage(conv, "governance", "running", "Scoring each candidate")
        await self._pause()
        passing = sum(1 for c in candidates if c.gates_pass and c.governance >= 0.8)
        yield self._stage(conv, "governance", "done", f"{passing} of {len(candidates)} candidates are well governed",
                          {"candidates": [{"asset_id": c.asset_id, "name": c.name, "governance": c.governance,
                                           "checks": [vars(k) for k in c.checks], "gates_failed": c.gates_failed}
                                          for c in candidates]})
        await self._pause()

        # ---- 4. Decision (deterministic)
        result = decide(candidates, availability["available"])
        decision = result.to_dict()
        missing = availability["missing_terms"] + [cat.CATALOG["dimensions"][d]["name"] for d in availability["missing_dimensions"]]
        decision["availability"] = availability
        conv["plan"] = {"decision": decision}
        label = {"reuse": "Reuse", "extend": "Extend", "create": "Create", "not_feasible": "Not feasible"}[result.decision.value]
        if result.change_type:
            label += f" ({result.change_type})"
        yield self._stage(conv, "decision", "done", label, decision)
        explanation = await explain(self.llm, {"decision": decision, "intent": public(intent),
                                               "missing_text": ("Missing: " + ", ".join(missing) + ".") if missing else ""})
        await self._pause()

        # ---- 4b. Follow-up actions (proposed by Python, accepted by a person)
        existing = await self.store.list_artifacts("actions", limit=500)
        proposals = act.propose({**intent, "preset_id": conv.get("preset_id")}, decision, existing)
        conv["plan"]["proposed_actions"] = proposals
        n_biz = sum(1 for p in proposals if p["kind"] == "business")
        yield self._stage(conv, "actions", "done",
                          f"{n_biz} business, {len(proposals) - n_biz} maintenance proposal(s). Nothing is assigned until you accept.",
                          {"proposals": proposals})

        if result.decision == Decision.REUSE:
            c = result.candidate
            yield self._stage(conv, "deliver", "done", f"Opened '{c.name}'",
                              {"asset": cat.asset_by_id(c.asset_id), "filters": intent.get("filters", {})})
            yield self._say(conv, explanation, kind="result", decision="reuse", asset_id=c.asset_id)
            conv["state"] = "idle"
            yield self._event(conv, "done", state="idle")
            return

        if result.decision == Decision.NOT_FEASIBLE:
            yield self._say(conv, explanation + " You can rephrase the request, or ask the data team to add a source.",
                            kind="result", decision="not_feasible",
                            suggestions=["Which deliveries need action today?", "What needs attention on my lines this shift?"])
            conv["state"] = "idle"
            yield self._event(conv, "done", state="idle")
            return

        # ---- 5. Evidence agent (/explore)
        yield self._stage(conv, "evidence", "running", "Evidence agent is checking sources")
        ev_run = await self.evidence_agent.run({"intent": intent, "decision": decision, "availability": availability})
        await self._audit(conv, "evidence", ev_run)
        evidence = ev_run.output
        evidence_id = await self._artifact(conv, "evidence", evidence)
        conv["plan"]["evidence"] = evidence
        corrections = sum(1 for v in evidence["verification"] if not v["ok"])
        yield self._stage(conv, "evidence", "done",
                          f"{len(evidence['proofs'])} checks on {len(evidence['datasets'])} source table(s)"
                          + (f", {corrections} correction(s) by Python" if corrections else ""),
                          {**evidence, "agent": ev_run.trace()})
        await self._pause()

        # ---- 6. Spec agent (/to-spec)
        yield self._stage(conv, "spec", "running", "Spec agent is drafting the DashboardSpec")
        sp_run = await self.spec_agent.run({"intent": intent, "decision": decision, "evidence": evidence,
                                            "preset": cat.preset_by_id(conv.get("preset_id"))})
        await self._audit(conv, "spec", sp_run)
        spec = sp_run.output
        spec_id = await self._artifact(conv, "specs", spec, status="draft", evidence_id=evidence_id, version=1)
        conv["plan"].update(spec=spec, spec_id=spec_id)
        n_vis = sum(len(p["visuals"]) for p in spec["pages"])
        valid = spec["validation"]["passed"]
        yield self._stage(conv, "spec", "done",
                          f"{len(spec['measures'])} certified measures, {n_vis} visuals, "
                          + ("all checks pass" if valid else "validation failed"),
                          {**spec, "agent": sp_run.trace()})
        await self._pause()

        # ---- 7. Human approval
        conv["state"] = "awaiting_approval"
        approver = spec.get("approver", "Report owner")
        yield self._stage(conv, "approval", "waiting", f"Waiting for {approver}", {"approver": approver, "spec_id": spec_id})
        note = "" if valid else " The spec did not pass every check, so review the failed checks before approving."
        yield self._say(conv, explanation + " Review the evidence and specification, then approve to generate the PBIP files." + note,
                        kind="approval", decision=result.decision.value)
        yield self._event(conv, "done", state=conv["state"])

    # ------------------------------------------------------------ approval → render → register
    async def approve(self, conv_id: str, approved: bool, approver: str) -> AsyncIterator[Event]:
        conv = await self._load(conv_id)
        try:
            yield {"type": "conversation", "id": conv["_id"], "provider": self.llm.name, "store": self.store.name}
            plan = conv.get("plan") or {}
            if conv["state"] != "awaiting_approval" or not plan.get("spec"):
                yield {"type": "error", "message": "There is nothing waiting for approval in this conversation."}
                return
            spec, spec_id = plan["spec"], plan.get("spec_id")
            if not approved:
                await self.store.update_artifact("specs", spec_id, {"status": "rejected", "decided_by": approver, "decided_at": now()})
                yield self._stage(conv, "approval", "rejected", f"Rejected by {approver}", {"approver": approver})
                yield self._say(conv, "Understood. Nothing was built. Tell me what to change, or ask a new question.", kind="result")
                conv["state"] = "idle"
                yield self._event(conv, "done", state="idle")
                return

            spec.update(approved_by=approver, approved_at=now())
            await self.store.update_artifact("specs", spec_id, {"status": "approved", "decided_by": approver,
                                                                "decided_at": spec["approved_at"]})
            yield self._stage(conv, "approval", "done", f"Approved by {approver}", {"approver": approver, "approved_at": spec["approved_at"]})
            await self._pause()

            yield self._stage(conv, "render", "running", "Writing PBIP files (plain Python, no AI)")
            await self._pause()
            output = render_pbip(spec, settings.output_dir, conv["_id"])
            await self.store.update_artifact("specs", spec_id, {"pbip": {"folder": output["folder"], "files": output["files"]}})
            yield self._stage(conv, "render", "done", f"{len(output['files'])} files in {output['folder']}", output)
            await self._pause()

            entry = await self._register(spec)
            yield self._stage(conv, "register", "done", f"'{entry['name']}' is now in the catalog with owner and review date", entry)
            yield self._say(conv, f"Done. **{entry['name']}** is generated as a PBIP project and registered with owner "
                                  f"{entry['owner']} and a review date of {entry['next_review']}. Ask the same question again and I will reuse it.",
                            kind="result", decision=spec["decision_type"], asset_id=entry["id"])
            conv["state"] = "idle"
            yield self._event(conv, "done", state="idle")
        finally:
            await self._save(conv)

    async def _register(self, spec: dict[str, Any]) -> dict[str, Any]:
        today = date.today().isoformat()
        base = cat.asset_by_id(spec["base_asset_id"]) if spec.get("base_asset_id") else None
        if base:
            if spec["change_type"] == "maintenance":
                base["refresh_age_hours"] = 1
                for ds in base["datasets"]:
                    if ds in cat.CATALOG["datasets"]:
                        cat.CATALOG["datasets"][ds]["refresh_age_hours"] = 1
                        await self.store.update_dataset(ds, {"refresh_age_hours": 1})
            else:
                base["measures"] = list(dict.fromkeys(base["measures"] + spec["change"].get("add_measures", [])))
                base["dimensions"] = list(dict.fromkeys(base["dimensions"] + spec["change"].get("add_dimensions", [])))
                base["grain"] = spec["change"].get("grain", base["grain"])
            base["last_review"] = today
            await self.store.upsert_asset(base)
            return {**base, "next_review": spec["review_date"], "change": spec["change"]}

        asset = {
            "id": "rpt_" + slug(spec["name"]).lower(), "name": spec["name"], "workspace": "Generated · Pending certification",
            "grain": next(iter(spec["grain"].values()), "day"), "measures": [m["id"] for m in spec["measures"]],
            "dimensions": list(dict.fromkeys(spec["dimensions"] + ["date"])), "datasets": spec["entities"],
            "certified": False, "owner": spec["owner"], "owner_status": "active", "backup_owner": "Data steward",
            "refresh_age_hours": 1, "last_review": today, "documented": True, "tests_passing": True,
            "conflicts": {}, "restricted": False, "views_90d": 0, "created_from_spec": True,
        }
        existing = cat.asset_by_id(asset["id"])
        if existing:
            existing.update(asset)
        else:
            cat.CATALOG["assets"].append(asset)
        await self.store.upsert_asset(asset)
        return {**asset, "next_review": spec["review_date"]}
