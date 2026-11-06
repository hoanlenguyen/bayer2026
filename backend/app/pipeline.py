"""Orchestrates the processing flow and streams events to the UI.

Flow: intent agent → discovery → governance → decision
        → reuse: deliver
        → repair / consolidate / migrate / new build:
              evidence agent → spec agent → human approval → PBIP render (thin report) → register
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
from .decision import THRESHOLDS, Decision, data_availability, decide, rank_candidates
from .facts import preview as facts_preview
from .llm import LLM, explain
from .pbip import render_pbip
from .governance import actor_for, audit, check_request_access, digest, require_review, source_digest, spec_digest
from .agents.spec import validate
from .bindings import contract
from .settings import settings
from .store import Store

STAGES = {
    "intent": "Understand the request",
    "discovery": "Find existing analytics",
    "governance": "Check governance",
    "decision": "Decide the lifecycle action",
    "actions": "Propose follow-up actions",
    "deliver": "Inspect the existing report",
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
        self.mutation_lock = asyncio.Lock()
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
    async def chat(self, conv_id: str | None, message: str, preset_id: str | None, actor: dict | None = None) -> AsyncIterator[Event]:
        actor = actor or actor_for("OWN-008")
        conv = await self._load(conv_id)
        if conv.get("requester_id"):
            check_request_access(conv, actor)
        else:
            conv["requester_id"] = actor["id"]
        try:
            preset = cat.preset_by_id(preset_id)
            text = message.strip() or (preset["prompt"] if preset else "")
            conv["title"] = conv["title"] or text[:70]
            yield {"type": "conversation", "id": conv["_id"], "provider": self.llm.name, "store": self.store.name,
                   "revision": conv.get("revision", 0) + int(conv["state"] != "clarifying")}

            new_run = conv["state"] != "clarifying"
            if new_run:
                conv["revision"] = conv.get("revision", 0) + 1
                await audit(self.store, actor["id"], conv["_id"], "request_submitted", revision=conv["revision"],
                            previous_state=conv.get("request_state", conv["state"]), text=text)
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
                                          grain="month", decision=preset["decision"],
                                          filters={k: list(v) for k, v in (preset.get("filters") or {}).items()},
                                          scope_global=bool(preset.get("scope_global")), migration=preset.get("migration"),
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
                conv["request_state"] = "clarifying"
                yield self._stage(conv, "intent", "waiting", f"Clarification {conv['asked']}",
                                  {**public(intent), "agent": agent_run.trace()})
                yield self._say(conv, result["question"], kind="question", suggestions=result.get("suggestions", []))
                yield self._event(conv, "done", state=conv["state"])
                return

            intent.pop("_pending", None)
            intent["grain"] = "month"
            intent["requester_id"] = conv["requester_id"]
            intent["request_revision"] = conv.get("revision", 1)
            intent["decision"] = intent.get("decision") or f"Monitor {label_list(intent['measures'], 'm') or 'the requested numbers'}"
            intent["department"] = intent.get("department") or cat.department_for(intent["measures"])
            conv["intent"] = intent
            await self._artifact(conv, "intents", public(intent), preset_id=conv["preset_id"])
            scope = ", ".join(v for vals in (intent.get("filters") or {}).values() for v in vals) or ("global" if intent.get("scope_global") else "")
            summary = (f"{label_list(intent['measures'], 'm') or 'No governed KPIs'}"
                       f"{' by ' + label_list(intent['dimensions'], 'd') if intent['dimensions'] else ''}"
                       f"{' · ' + scope if scope else ''}{' · Tableau migration' if intent.get('migration') else ''}")
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
        candidates = rank_candidates(intent, cat.CATALOG)
        availability = data_availability(intent, cat.CATALOG)
        shown = candidates[: THRESHOLDS["max_candidates_shown"]]
        in_scope = sum(1 for c in candidates if c.scope_score >= THRESHOLDS["min_scope"])
        yield self._stage(conv, "discovery", "done",
                          f"{len(candidates)} of {len(cat.CATALOG['assets'])} reports use a requested KPI; {in_scope} fit the product and market scope",
                          {"candidates": [c.to_dict() for c in shown], "total_candidates": len(candidates), "in_scope": in_scope,
                           "availability": availability, "searched": len(cat.CATALOG["assets"])})
        await self._pause()

        # ---- 3. Governance check
        yield self._stage(conv, "governance", "running", "Scoring each candidate")
        await self._pause()
        passing = sum(1 for c in candidates if c.gates_pass and c.governance >= THRESHOLDS["reuse_governance"])
        yield self._stage(conv, "governance", "done", f"{passing} of {len(candidates)} candidates pass every governance check",
                          {"candidates": [{"asset_id": c.asset_id, "name": c.name, "governance": c.governance,
                                           "checks": [vars(k) for k in c.checks], "gates_failed": c.gates_failed}
                                          for c in shown]})
        await self._pause()

        # ---- 4. Decision (deterministic)
        result = decide(candidates, availability, intent, cat.CATALOG)
        decision = result.to_dict()
        missing = availability["missing_terms"]
        decision["availability"] = availability
        if result.decision != Decision.NOT_FEASIBLE:
            decision["preview"] = facts_preview(intent)
        conv["plan"] = {"decision": decision}
        label = {"reuse": "Reuse", "repair": "Repair", "consolidate": "Consolidate", "migrate": "Migrate",
                 "new_build": "New build", "not_feasible": "Not feasible"}[result.decision.value]
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
            yield self._stage(conv, "deliver", "done", f"Existing match: '{c.name}'",
                              {"asset": cat.asset_by_id(c.asset_id), "filters": intent.get("filters", {}),
                               "preview": decision.get("preview")})
            yield self._say(conv, explanation + " Inspect the source evidence before opening it in your organisation. The demo grants synthetic metadata access only; live report access has not been verified.", kind="result", decision="reuse", asset_id=c.asset_id)
            conv["state"] = "idle"
            conv["request_state"] = "existing_asset_identified" if result.decision == Decision.REUSE else "unsupported"
            yield self._event(conv, "done", state="idle")
            return

        if result.decision == Decision.NOT_FEASIBLE:
            yield self._say(conv, explanation + " You can rephrase the request using the governed KPIs.",
                            kind="result", decision="not_feasible",
                            suggestions=["Show Xarelto on-time-in-full and market access coverage for Mexico.",
                                         "How are Eylea net sales and digital engagement developing in Japan?"])
            conv["state"] = "idle"
            conv["request_state"] = "existing_asset_identified" if result.decision == Decision.REUSE else "unsupported"
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
                                            "preset": cat.preset_by_id(conv.get("preset_id")), "requester_id": conv["requester_id"]})
        await self._audit(conv, "spec", sp_run)
        spec = sp_run.output
        spec_id = await self._artifact(conv, "specs", spec, status="draft", evidence_id=evidence_id, version=conv.get("revision", 1))
        conv["plan"].update(spec=spec, spec_id=spec_id, spec_hash=spec_digest(spec), source_hash=source_digest())
        conv["request_state"] = "awaiting_review"
        n_vis = sum(len(p["visuals"]) for p in spec["pages"])
        valid = spec["validation"]["passed"]
        yield self._stage(conv, "spec", "done",
                          (f"Repair plan for {spec['name']}" if spec["decision_type"] == "repair" else
                           f"{len(spec['measures'])} approved KPIs, {n_vis} visuals on {spec['semantic_model']['id'] if spec.get('semantic_model') else 'no model'}")
                          + (", all checks pass" if valid else ", some checks need review"),
                          {**spec, "agent": sp_run.trace()})
        await self._pause()

        # ---- 7. Human approval
        conv["state"] = "awaiting_approval"
        approver = "Configured demo reviewer"
        yield self._stage(conv, "approval", "waiting", f"Waiting for {approver}", {"approver": approver, "spec_id": spec_id, "spec_hash": conv["plan"]["spec_hash"],
                           "source_hash": conv["plan"]["source_hash"], "can_generate": valid and spec["execution_contract"]["supported"],
                           "note": "Approval records a plan. Generation, runtime acceptance and publication are separate."})
        note = "" if valid else " The spec did not pass every check, so review the failed checks before approving."
        yield self._say(conv, explanation + " Review the plan and its prerequisites. Approval records the plan; only complete executable bindings allow generation." + note,
                        kind="approval", decision=result.decision.value)
        yield self._event(conv, "done", state=conv["state"])

    # ------------------------------------------------------------ review → gated generation
    async def approve(self, conv_id: str, approved: bool, actor: dict, expected_hash: str) -> AsyncIterator[Event]:
        from fastapi import HTTPException
        conv = await self._load(conv_id)
        check_request_access(conv, actor)
        require_review(actor, conv.get("requester_id"))
        plan = conv.get("plan") or {}
        if not plan.get("spec"):
            raise HTTPException(409, "There is no specification to review.")
        if expected_hash != plan.get("spec_hash") or spec_digest(plan["spec"]) != expected_hash:
            raise HTTPException(409, "The specification changed. Reload and review it again.")
        if plan.get("approval"):
            if plan["approval"]["approved"] != approved:
                raise HTTPException(409, "This version already has a different review decision.")
            for event in plan.get("approval_events", []):
                yield event
            return
        if conv["state"] != "awaiting_approval" or source_digest() != plan.get("source_hash"):
            raise HTTPException(409, "The request or source changed. Reassess it before approval.")
        spec, spec_id = plan["spec"], plan["spec_id"]
        start = len(conv["runs"][-1]["events"])
        yield {"type": "conversation", "id": conv["_id"], "provider": self.llm.name, "store": self.store.name}
        try:
            decision = {"approved": approved, "actor_id": actor["id"], "at": now(),
                        "spec_hash": expected_hash, "source_hash": plan["source_hash"]}
            plan["approval"] = decision
            await audit(self.store, actor["id"], spec_id, "plan_approved" if approved else "plan_rejected", review=decision)
            await self.store.update_artifact("specs", spec_id, {"status": "approved" if approved else "rejected", "approval": decision})
            if not approved:
                conv["request_state"] = "rejected"
                yield self._stage(conv, "approval", "rejected", "Plan rejected", {"approver": actor["name"]})
                yield self._say(conv, "Plan rejected. Edit the request to prepare a new version.", kind="result")
            else:
                spec.update(approved_by=actor["id"], approved_at=decision["at"])
                yield self._stage(conv, "approval", "done", "Plan approved", {"approver": actor["name"], "approved_at": decision["at"], "spec_hash": expected_hash})
                checks = validate(spec)
                execution = contract(spec)
                blockers = [c["text"] for c in checks if not c["ok"]]
                if not execution["supported"]:
                    blockers.append("Executable demo bindings unavailable for this change" + (": " + ", ".join(execution["missing"]) if execution["missing"] else "; external execution required"))
                if execution != spec.get("execution_contract"):
                    blockers.append("Execution contract changed since review")
                if blockers:
                    conv["request_state"] = "execution_blocked"
                    action = act.create({"title": "Resolve prerequisites: " + spec["name"], "kind": "maintenance",
                        "key": "execute:" + spec_id, "owner": spec["owner"], "reason": "; ".join(blockers),
                        "asset_id": spec.get("base_asset_id")}, actor["id"], conv_id, conv["runs"][-1]["id"])
                    action.update(owner_id=spec.get("owner_id"), spec_id=spec_id, status="blocked", blocker="; ".join(blockers))
                    await self.store.save_artifact("actions", action)
                    await audit(self.store, actor["id"], spec_id, "execution_blocked", blockers=blockers, action_id=action["_id"])
                    yield self._stage(conv, "render", "done", "Approved plan; execution blocked", {"files": [], "preview": {"model": ""},
                        "maintenance": True, "validated_in_power_bi": False, "artifact_state": "execution_blocked", "blockers": blockers,
                        "action_id": action["_id"]})
                    yield self._say(conv, "The plan is recorded. Prerequisites are tracked in Actions; no source health or trusted catalogue status was changed.", kind="result")
                else:
                    fingerprint = digest({k: conv["intent"].get(k) for k in ("measures", "dimensions", "filters", "grain", "scope_global")})
                    previous = next((o for o in await self.store.list_artifacts("outputs", limit=10000)
                        if o.get("fingerprint") == fingerprint and o.get("source_hash") == plan["source_hash"] and o.get("requester_id") == conv["requester_id"]), None)
                    if previous:
                        output, entry = previous["output"], previous["asset"]
                        yield self._stage(conv, "render", "done", "Existing generated package; validation still pending", output)
                    else:
                        yield self._stage(conv, "render", "running", "Generating schema-checked demo PBIR with explicit bindings")
                        output = render_pbip(spec, settings.output_dir, spec_id)
                        output["download_url"] = "/api/outputs/" + spec_id + "/download"
                        entry = await self._register_pending(spec, spec_id)
                        await self.store.save_artifact("outputs", {"_id": spec_id, "conversation_id": conv_id, "created_at": now(),
                            "requester_id": conv["requester_id"], "fingerprint": fingerprint, "source_hash": plan["source_hash"],
                            "output": output, "asset": entry})
                        await audit(self.store, actor["id"], spec_id, "artifact_generated", state="validation_pending", spec_hash=expected_hash,
                                    hashes=output["validation"]["artifact_hashes"])
                        yield self._stage(conv, "render", "done", "Generated; Power BI runtime validation pending", output)
                    plan["output_asset_id"] = entry["id"]
                    plan["output"] = output
                    conv["request_state"] = "validation_pending"
                    yield self._stage(conv, "register", "done", "Draft registered; excluded from trusted reuse", entry)
                    yield self._say(conv, "Download the validation package. Automated schema and binding checks passed. Power BI rendering, numerical reconciliation and publication remain pending.", kind="result")
            conv["state"] = "idle"
            yield self._event(conv, "done", state="idle")
            plan["approval_events"] = conv["runs"][-1]["events"][start:]
        except Exception as exc:
            conv["request_state"] = "generation_failed"
            conv["state"] = "idle"
            await audit(self.store, actor["id"], spec_id, "generation_failed", reason=str(exc), spec_hash=expected_hash)
            yield self._event(conv, "error", message="Generation failed; the review is retained. Reassess after resolving: " + str(exc))
            yield self._event(conv, "done", state="idle")
            plan["approval_events"] = conv["runs"][-1]["events"][start:]
        finally:
            await self._save(conv)

    async def _register_pending(self, spec: dict, spec_id: str) -> dict:
        model = cat.model_by_id((spec.get("semantic_model") or {}).get("id")) or {}
        entry = {"id": "GEN-" + spec_id, "name": spec["name"], "asset_type": "Report", "platform": "Power BI",
            "workspace_id": model.get("workspace_id"), "workspace": "Local synthetic validation package",
            "model_id": None, "execution_model": "BayerDemo", "proposed_source_model_id": model.get("id"),
            "product_scope": spec["product_scope"], "market_scope": spec["market_scope"],
            "owner_id": spec["owner_id"], "owner": spec["owner"], "business_owner_id": spec.get("business_owner_id"),
            "owner_status": "active", "created": date.today().isoformat(), "last_modified": date.today().isoformat(),
            "artifact_state": "validation_pending", "validated_in_power_bi": False, "lifecycle": "draft",
            "endorsement": "none", "certified": False, "classification": "synthetic_demo", "delivery_model": "demo",
            "grain": "month", "kpis": [m["kpi_id"] for m in spec["measures"]], "measures": [m["id"] for m in spec["measures"]],
            "conflicts": {}, "variants": {}, "views_90d": 0, "users_90d": 0, "signals": [], "dq_issues": [],
            "refresh_status": None, "model_ai_readiness": "unknown", "created_from_spec": True,
            "next_review": spec["review_date"], "replaces": [], "spec_id": spec_id}
        cat.CATALOG["assets"].append(entry)
        await self.store.upsert_asset(entry)
        return entry
