"""Orchestrates the processing flow and streams events to the UI.

Flow: parse the request (intent agent) → resolve KPIs → find analytics → trace lineage → check trust → Tableau
        → recommend: reuse, consolidation, migration, retirement or new build, with its evidence

The assessment records a recommendation. The dashboard builder can then use the reviewed brief to create a
workbook-backed view. Agents propose and Python verifies. Every stage emits ``stage`` events
(running / waiting / done) with a payload for the UI, and every agent run, intent and recommendation is saved for audit.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from . import actions as act
from . import catalog as cat
from . import guided_examples as guided
from .ask_metrics import metric_series
from .agents import AgentRun, IntentAgent, RelevanceAgent
from .agents.base import Step
from .agents.gate import ConversationGateAgent
from .agents.intent import sanitize_intent
from .agents.relevance import EXAMPLES, retry_message
from .decision import THRESHOLDS, Decision
from .facts import preview as facts_preview
from .employee_report_match import native_reuse, supports_monthly_workbook
from .assessment import Assessment
from .decider import Decider
from .vectors import VectorStore, get_embedder, similar_requests, suggest_kpis
from .llm import LLM, explain, merge_usage, usage_scope, usage_total
from .store import Store

log = logging.getLogger(__name__)

STAGES = {
    "intent": "Parse business question",
    "kpis": "Resolve metric definitions",
    "discovery": "Find existing analytics",
    "lineage": "Trace data dependencies",
    "governance": "Check trust and ownership",
    "migration": "Handle Tableau to Power BI",
    "decision": "Recommend what to do",
    "actions": "Suggest follow-up work",
    "deliver": "Show the matched catalogue record",
}

Event = dict[str, Any]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def public(intent: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in intent.items() if not k.startswith("_")}


def classification(intent: dict[str, Any]) -> dict[str, Any]:
    """The first step's tags: what the intent alone says. The semantic model and existing report depend on the catalog
    assessment, so they arrive with the discovery stage (its `classification`), never by running it early."""
    return Assessment(intent).scope()


def run_question(conv: dict[str, Any], run: dict[str, Any]) -> str:
    """The request that opened this run (later messages are answers to grill-me questions)."""
    return next((m["content"] for m in conv["messages"][run["msg_start"]:] if m["role"] == "user"), "")


def label_list(ids: list[str], kind: str) -> str:
    src = cat.CATALOG["measures" if kind == "m" else "dimensions"]
    return ", ".join(src[i]["name"] for i in ids if i in src)


ANALYSIS_STAGES = (("kpis", 2, "Resolving metric definitions"), ("discovery", 3, "Ranking reports and checking data availability"),
                   ("lineage", 4, "Tracing data dependencies"), ("governance", 5, "Checking trust and ownership"),
                   ("migration", 6, "Checking for Tableau reports"))
STAGE_STEP = {stage: n for stage, n, _ in ANALYSIS_STAGES}


def intent_summary(intent: dict[str, Any]) -> str:
    scope = ", ".join(v for vals in (intent.get("filters") or {}).values() for v in vals) or ("global" if intent.get("scope_global") else "")
    return (f"{label_list(intent['measures'], 'm') or 'No governed KPIs'}"
            f"{' by ' + label_list(intent['dimensions'], 'd') if intent['dimensions'] else ''}"
            f"{' · ' + scope if scope else ''}{' · Tableau migration' if intent.get('migration') else ''}")


def stage_payload(a: Assessment, stage: str) -> dict[str, Any]:
    """A completed stage's summary and evidence, from the assessment's own result for that stage."""
    n = STAGE_STEP[stage]
    step = a.steps[n]
    extra: dict[str, Any] = {}
    if stage == "discovery":
        shown = a.candidates[: THRESHOLDS["max_candidates_shown"]]
        extra = {"candidates": [c.to_dict() for c in shown], "total_candidates": len(a.candidates),
                 "in_scope": sum(1 for c in a.candidates if c.scope_score >= THRESHOLDS["min_scope"]),
                 "availability": a.availability, "searched": len(cat.CATALOG["assets"]),
                 # The model and existing report are known from here on: the intent step's classification gains them.
                 "classification": {**a.scope(), **a.assessed}}
    elif stage == "governance":
        shown = a.candidates[: THRESHOLDS["max_candidates_shown"]]
        extra = {"candidates": [{"asset_id": c.asset_id, "name": c.name, "governance": c.governance,
                                 "checks": [vars(k) for k in c.checks], "gates_failed": c.gates_failed} for c in shown]}
    return {"summary": step["summary"], "data": {**extra, "step": step}}


def recommend(a: Assessment) -> dict[str, Any]:
    """The rules decision with its evidence, once every stage has run."""
    intent, result, tags = a.intent, a.result, a.tags()
    decision = result.to_dict()
    decision["availability"] = a.availability
    decision["recommendation"] = tags["recommendation"]
    # A new build has no report yet: the shared model it would sit on, and whoever owns that, is who to talk to.
    target_model = cat.model_by_id(result.target_model_id) if result.decision == Decision.NEW_BUILD else None
    if target_model:
        decision["target_model"] = {k: target_model.get(k) for k in ("id", "name", "owner", "owner_status")}
    # No preview for a country without data: the rows would be other countries' numbers.
    if result.decision not in (Decision.NOT_FEASIBLE, Decision.RETIRE) and not intent.get("other_markets"):
        decision["preview"] = facts_preview(intent)
    return decision


def analyse(intent: dict[str, Any]) -> dict[str, Any]:
    """Steps 2 to 6 and the recommendation for a complete intent, in one call. Pure: reads the catalog, saves nothing.
    The Ask flow runs the same Assessment stage by stage; the conversation simulation uses this, so both agree."""
    a = Assessment(intent).run()
    stages = {stage: {"running": running, **stage_payload(a, stage)} for stage, _n, running in ANALYSIS_STAGES}
    return {"result": a.result, "tags": a.tags(), "stages": stages, "decision": recommend(a)}


class Pipeline:
    def __init__(self, store: Store, llm: LLM, decider: Decider | None = None) -> None:
        self.store = store
        self.llm = llm
        self.decider = decider or Decider()
        self.relevance_agent = RelevanceAgent(llm, self.decider)
        self.intent_agent = IntentAgent(llm, self.decider)
        self.gate_agent = ConversationGateAgent(llm, self.decider)
        # Atlas Vector Search when the store is MongoDB and the index exists; in-memory otherwise.
        self.vectors = VectorStore(get_embedder(llm), getattr(store, "db", None))

    async def _triage(self, conv: dict[str, Any], status: str | None) -> dict[str, Any]:
        """Triage tags for this request. Urgency comes from the intent. Status is a workflow tag set later:
        None while the request is being understood, "new" once it is created, "triaged" at the decision."""
        run = conv["runs"][-1]
        tri = {"status": status, "urgency": conv["intent"].get("urgency") or {"value": "normal", "source": "default", "evidence": None},
               "similar": run.get("similar"), "request_id": run.get("request_id"),
               "request_store": run.get("request_store")}
        conv["triage"] = tri
        if run.get("intent_id") and status:
            await self.store.update_artifact("intents", run["intent_id"], {"status": status, "urgency": tri["urgency"]["value"]})
        if run.get("request_id") and status:
            try:
                await self.vectors.set_request_status(run["request_id"], status, urgency=tri["urgency"]["value"])
            except Exception as exc:  # retrieval upkeep must never block a request
                log.warning("Could not update request %s in the vector store: %s", run["request_id"], exc)
        return tri

    async def _register_request(self, conv: dict[str, Any], run: dict[str, Any], intent: dict[str, Any]) -> None:
        """Add the request to the vector store, so the next person asking the same thing sees it as a duplicate."""
        run["request_id"] = f"REQ-APP-{run['intent_id'][:6].upper()}"
        filters = intent.get("filters") or {}
        try:
            run["request_store"] = await self.vectors.add_request({
                "_id": run["request_id"], "text": run_question(conv, run), "request_date": now()[:10],
                "product_context": ", ".join(filters.get("product", [])) or None,
                "market_context": ", ".join(filters.get("market", [])) or None,
                "urgency": (intent.get("urgency") or {}).get("value", "normal"), "status": "new",
                "conversation_id": conv["_id"]})
        except Exception as exc:
            run["request_store"] = None
            log.warning("Could not add request %s to the vector store: %s", run["request_id"], exc)

    # ------------------------------------------------------------ helpers
    def _event(self, conv: dict[str, Any], type_: str, **data: Any) -> Event:
        ev = {"type": type_, "ts": now(), **data}
        if type_ == "done" and conv["runs"] and conv["runs"][-1].get("tokens"):
            ev["tokens"] = conv["runs"][-1]["tokens"]
        if conv["runs"]:
            conv["runs"][-1]["events"].append(ev)
        return ev

    def _stage(self, conv: dict[str, Any], stage: str, status: str, summary: str = "", data: Any = None) -> Event:
        return self._event(conv, "stage", stage=stage, title=STAGES[stage], status=status, summary=summary, data=data)

    def _say(self, conv: dict[str, Any], text: str, **extra: Any) -> Event:
        msg = {"role": "assistant", "content": text, "ts": now(), **extra}
        conv["messages"].append(msg)
        return self._event(conv, "message", **msg)

    def _count_tokens(self, conv: dict[str, Any], calls: list[dict[str, Any]]) -> None:
        """Adds to this question's running total. A rejected message before any question has nowhere to count."""
        if conv["runs"] and calls:
            conv["runs"][-1]["tokens"] = merge_usage(conv["runs"][-1].get("tokens"), usage_total(calls))

    async def _audit(self, conv: dict[str, Any], stage: str, run: AgentRun) -> None:
        if conv["runs"] and run.usage:
            conv["runs"][-1]["tokens"] = merge_usage(conv["runs"][-1].get("tokens"), run.usage)
        await self.store.save_artifact("agent_runs", {
            "_id": uuid.uuid4().hex, "conversation_id": conv["_id"], "run_id": conv["runs"][-1]["id"] if conv["runs"] else None,
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

    async def _done(self, conv: dict[str, Any], state: str) -> Event:
        """The terminal event, sent only after the run (with this event) is saved, so a client that sees `done` can rely
        on reading the run back. A failed save raises instead, and the stream ends with an error, never after `done`."""
        ev = self._event(conv, "done", state=state)
        if conv["runs"]:  # a chat that only ever held rejected messages stays out of the history
            await self._save(conv)
        return ev

    def _saved(self, event: Event, conv: dict[str, Any]) -> Event:
        """The outgoing user_message for an accepted, already saved message carries the conversation's summary,
        so a client can add it to its own history. The stored transcript event stays as it was."""
        return {**event, "history": {"_id": conv["_id"], "title": conv["title"], "updated_at": conv["updated_at"]}}

    # ------------------------------------------------------------ message check
    async def _check_message(self, conv: dict[str, Any], text: str) -> AgentRun:
        open_question = None
        if conv["state"] == "clarifying":
            open_question = next((m for m in reversed(conv["messages"]) if m.get("kind") == "question"), None)
        return await self.relevance_agent.run({
            "text": text, "question": open_question["content"] if open_question else None,
            "suggestions": open_question.get("suggestions", []) if open_question else [],
            "pending": conv["intent"].get("_pending") if open_question else None,
            "request": run_question(conv, conv["runs"][-1]) if open_question else None})

    def _reject(self, conv: dict[str, Any], text: str, check: AgentRun) -> list[Event]:
        """Ask the user to try again. Marked messages stay in the chat but never reach the intent agent."""
        open_question = None
        if conv["state"] == "clarifying":
            open_question = next((m for m in reversed(conv["messages"]) if m.get("kind") == "question"), None)
        conv["messages"].append({"role": "user", "content": text, "ts": now(), "rejected": True})
        return [
            self._event(conv, "user_message", content=text),
            self._say(conv, retry_message(check.output["verdict"], open_question["content"] if open_question else None),
                      kind="retry", rejected=True, verdict=check.output["verdict"],
                      suggestions=open_question.get("suggestions", []) if open_question else EXAMPLES),
        ]

    # ------------------------------------------------------------ chat turn
    async def chat(self, conv_id: str | None, message: str, preset_id: str | None, guided_id: str | None = None,
                   choice_id: str | None = None) -> AsyncIterator[Event]:
        conv = await self._load(conv_id)
        run_ = conv["runs"][-1] if conv["runs"] else {}
        if guided_id or (conv["state"] == "clarifying" and run_.get("guided")):
            try:
                async for ev in self._guided(conv, message, guided_id, choice_id):
                    yield ev
            finally:
                if conv["runs"]:
                    await self._save(conv)
            return
        try:
            preset = cat.preset_by_id(preset_id)
            text = message.strip() or (preset["prompt"] if preset else "")
            yield {"type": "conversation", "id": conv["_id"], "provider": self.llm.name, "store": self.store.name}

            # ---- 0. Is this a usable business message? A preset's own prompt always is.
            check = None
            if not (preset and text == preset["prompt"]):
                yield {"type": "processing", "phase": "relevance"}  # not stored: the message check is running
                check = await self._check_message(conv, text)
            if check and check.output["verdict"] != "accept":
                await self._audit(conv, "relevance", check)
                for ev in self._reject(conv, text, check):
                    yield ev
                yield await self._done(conv, conv["state"])
                return

            conv["title"] = conv["title"] or text[:70]
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
                                          grain="month", decision=preset["decision"],
                                          filters={k: list(v) for k, v in (preset.get("filters") or {}).items()},
                                          scope_global=bool(preset.get("scope_global")), migration=preset.get("migration"),
                                          unmatched_terms=list(preset.get("requested_terms", [])),
                                          department=preset["department"])
            run = conv["runs"][-1]
            if check:
                await self._audit(conv, "relevance", check)
            conv["messages"].append({"role": "user", "content": text, "ts": now(), "preset_id": conv["preset_id"]})
            await self._save(conv)  # in the history from now on, even if the answer gets cut off
            yield self._saved(self._event(conv, "user_message", content=text), conv)
            if new_run:
                yield self._stage(conv, "intent", "running", "Intent agent is reading your request")
            else:  # an answer to the open question: the same intent stage continues, so no new stage starts
                yield {"type": "processing", "phase": "intent"}

            # ---- 1. Intent agent (/grill-me)
            transcript = [{"role": m["role"], "content": m["content"]} for m in conv["messages"][run["msg_start"]:] if not m.get("rejected")]
            if "similar" not in run:
                with usage_scope() as used:
                    try:
                        run["similar"] = await similar_requests(self.vectors, run_question(conv, run))
                        run["kpi_suggestions"] = [] if conv["preset_id"] else await suggest_kpis(self.vectors, run_question(conv, run))
                    except Exception as exc:  # retrieval must never block a request
                        run["similar"], run["kpi_suggestions"] = None, []
                        run["retrieval_error"] = str(exc)[:200]
                self._count_tokens(conv, used)
            agent_run = await self.intent_agent.run({"transcript": transcript, "intent": conv["intent"], "asked": conv["asked"],
                                                     "kpi_suggestions": run.get("kpi_suggestions"),
                                                     "preset": cat.preset_by_id(conv["preset_id"])})
            await self._audit(conv, "intent", agent_run)
            if check:
                agent_run.steps[:0] = check.steps  # the flow panel's trace shows the check too
            result = agent_run.output
            pending = result["intent"].get("_pending")
            intent = sanitize_intent(result["intent"])
            if pending:
                intent["_pending"] = pending
            conv["intent"] = intent

            if result["status"] == "ask" and result.get("question"):
                conv["asked"] += 1
                conv["state"] = "clarifying"
                tri = await self._triage(conv, None)
                yield self._stage(conv, "intent", "waiting", f"Clarifying question {conv['asked']}",
                                  {**public(intent), "triage": tri, "agent": agent_run.trace(),
                                   **({"classification": classification(intent)} if intent["measures"] else {})})
                yield self._say(conv, result["question"], kind="question", suggestions=result.get("suggestions", []))
                yield await self._done(conv, conv["state"])
                return

            intent.pop("_pending", None)
            intent["grain"] = "month"
            intent["decision"] = intent.get("decision") or f"Monitor {label_list(intent['measures'], 'm') or 'the requested numbers'}"
            intent["department"] = intent.get("department") or cat.department_for(intent["measures"])
            conv["intent"] = intent
            run["intent_id"] = await self._artifact(conv, "intents", public(intent), preset_id=conv["preset_id"],
                                                    status="new", urgency=(intent.get("urgency") or {}).get("value", "normal"))
            await self._register_request(conv, run, intent)
            tri = await self._triage(conv, "new")
            tri_public = {**tri, "status": None}  # status is shown from the decision step on
            yield self._stage(conv, "intent", "done", intent_summary(intent), {**public(intent), "triage": tri_public,
                                                                 "classification": classification(intent), "agent": agent_run.trace()})

            async for ev in self._plan(conv, [m["content"] for m in transcript if m["role"] == "user"]):
                yield ev
        finally:
            if conv["runs"]:  # a chat that only ever held rejected messages stays out of the history
                await self._save(conv)

    # ------------------------------------------------------------ guided examples (start screen)
    async def _guided(self, conv: dict[str, Any], text: str, guided_id: str | None, choice_id: str | None) -> AsyncIterator[Event]:
        """A starter chip: fixed scope from the registry, then two offered-choice questions, then the normal analysis.
        Replies are matched to the offered options only, so no model or classifier can change the brief. The period
        choices are resolved from the comparison's covered months once, stored on the run, and used as offered."""
        yield {"type": "conversation", "id": conv["_id"], "provider": self.llm.name, "store": self.store.name}
        if guided_id:
            yield {"type": "processing", "phase": "scope"}
            ex = guided.get(guided_id)
            conv["title"] = conv["title"] or ex["text"][:70]
            conv["plan"], conv["preset_id"], conv["asked"] = None, None, 0
            conv["runs"].append({"id": uuid.uuid4().hex[:8], "started_at": now(), "events": [], "msg_start": len(conv["messages"]),
                                 "guided": {"id": ex["id"], "step": "purpose"}, "similar": None, "kpi_suggestions": []})
            first = guided.period_options(ex)[0]
            conv["intent"] = {**guided.intent_for(ex, ex["purposes"][0][0], first), "decision": None, "dashboard_brief": {},
                              "_pending": "guided_purpose"}
            conv["messages"].append({"role": "user", "content": ex["text"], "ts": now(), "guided_id": ex["id"]})
            await self._save(conv)
            yield self._saved(self._event(conv, "user_message", content=ex["text"]), conv)
            yield self._stage(conv, "intent", "running", "Reading the example's fixed scope")
            async for ev in self._guided_ask(conv, ex, "purpose"):
                yield ev
            return
        run = conv["runs"][-1]
        g = run["guided"]
        ex = guided.BY_ID.get(g["id"])
        if g["step"] == "purpose":
            options = guided.purpose_options(ex)
        else:
            # Older conversations saved no offered dates: they cannot be established, so offer the current ones afresh.
            options = g.get("offered") or []
        choice = guided.choose(options, choice_id, text) if options else None
        if g["step"] == "period" and not options:
            conv["messages"].append({"role": "user", "content": text, "ts": now(), "rejected": True})
            yield self._event(conv, "user_message", content=text)
            async for ev in self._guided_ask(conv, ex, "period", note="The reporting periods for this example have been checked again. "
                                             "Please choose one of the current periods."):
                yield ev
            return
        if not choice:  # anything else repeats the same step; nothing about the run changes
            conv["messages"].append({"role": "user", "content": text, "ts": now(), "rejected": True})
            yield self._event(conv, "user_message", content=text)
            yield self._say(conv, "Please pick one of the two answers below. To ask something else, choose New question.",
                            kind="retry", rejected=True, verdict="guided_choice", suggestions=[o["label"] for o in options],
                            choices=options, guided_step=g["step"])
            yield await self._done(conv, conv["state"])
            return
        if g["step"] == "period" and not guided.still_covered(ex, choice):
            conv["messages"].append({"role": "user", "content": choice["label"], "ts": now(), "rejected": True})
            yield self._event(conv, "user_message", content=choice["label"])
            async for ev in self._guided_ask(conv, ex, "period", note="The workbook coverage changed since these periods were offered, "
                                             "so the dates you saw no longer hold. Please choose one of the current periods."):
                yield ev
            return
        conv["messages"].append({"role": "user", "content": choice["label"], "ts": now(), "choice_id": choice["id"]})
        await self._save(conv)
        yield self._saved(self._event(conv, "user_message", content=choice["label"]), conv)
        if g["step"] == "purpose":
            g.update(purpose=choice["id"], step="period")
            conv["intent"]["decision"] = choice["label"]
            yield {"type": "processing", "phase": "periods"}
            async for ev in self._guided_ask(conv, ex, "period"):
                yield ev
            return
        window = {k: choice[k] for k in ("id", "start", "end", "count")}
        g.update(period=choice["id"], window=window, step="done")
        intent = guided.intent_for(ex, g["purpose"], window)
        intent["department"] = cat.department_for(intent["measures"])
        conv["intent"] = intent
        trace = self._guided_trace(ex, g)
        run["intent_id"] = await self._artifact(conv, "intents", public(intent), preset_id=None, guided_id=ex["id"],
                                                status="new", urgency="normal")
        await self._register_request(conv, run, intent)
        tri = await self._triage(conv, "new")
        yield self._stage(conv, "intent", "done", intent_summary(intent), {**public(intent), "triage": {**tri, "status": None},
                                                                          "classification": classification(intent), "agent": trace.trace()})
        async for ev in self._plan(conv, [ex["text"]]):
            yield ev

    def _guided_trace(self, ex: dict[str, Any], g: dict[str, Any]) -> AgentRun:
        steps = [Step("rule", "Fixed scope from the guided example", ex["id"])]
        if g.get("purpose"):
            steps.append(Step("check", "Purpose matched an offered choice", g["purpose"]))
        if g.get("period"):
            steps.append(Step("check", "Period matched the dates offered for this run", g["period"]))
        return AgentRun(agent="guided", mode="rules", model="Guided example registry", steps=steps, output=None)

    async def _guided_ask(self, conv: dict[str, Any], ex: dict[str, Any], step: str, note: str | None = None) -> AsyncIterator[Event]:
        g = conv["runs"][-1]["guided"]
        if step == "period":
            g["offered"] = guided.period_options(ex)  # bound to this run: the answer resolves against exactly these dates
            if not g["offered"]:
                conv["state"] = "idle"
                yield self._say(conv, "This example's workbook coverage has a gap now, so it cannot be built as offered. "
                                      "Choose New question to pick another example or ask your own question.", kind="result")
                yield await self._done(conv, "idle")
                return
        conv["asked"] += 1
        conv["state"] = "clarifying"
        conv["intent"]["_pending"] = "guided_" + step
        trace = self._guided_trace(ex, g)
        await self._audit(conv, "intent", trace)
        tri = await self._triage(conv, None)
        yield self._stage(conv, "intent", "waiting", f"Clarifying question {min(conv['asked'], 2)} of 2",
                          {**public(conv["intent"]), "triage": tri, "agent": trace.trace(), "classification": classification(conv["intent"])})
        options = guided.purpose_options(ex) if step == "purpose" else g["offered"]
        question = guided.PURPOSE_QUESTION if step == "purpose" else guided.PERIOD_QUESTION
        if note:
            question = f"{note} {question}"
        yield self._say(conv, question, kind="question", suggestions=[o["label"] for o in options], choices=options, guided_step=step,
                        facts=guided.scope_facts(ex))
        yield await self._done(conv, conv["state"])

    # ------------------------------------------------------------ the analysis steps → recommendation
    async def _plan(self, conv: dict[str, Any], user_turns: list[str]) -> AsyncIterator[Event]:
        """Steps 2 to 6, then the recommendation. Each stage's `running` is sent before its operation starts and its `done`
        carries that operation's own result, which the next stage uses. Catalog work runs off the event loop, so the
        `running` event is delivered while the work is still going."""
        intent = conv["intent"]
        a = Assessment(intent)
        a.parse()
        # ---- 2 to 6: KPI_Catalog, Analytics_Assets, Semantic_Models, Governance_Signals, Migration_Backlog
        for stage, _n, running in ANALYSIS_STAGES:
            yield self._stage(conv, stage, "running", running)
            await asyncio.to_thread(a.run_stage, stage)
            done = stage_payload(a, stage)
            yield self._stage(conv, stage, "done", done["summary"], done["data"])

        # ---- Recommendation and follow-up: the rules decision, the reuse override, the explanation and proposals
        yield self._stage(conv, "decision", "running", "Preparing the recommendation")
        result = a.result
        estate = recommend(a)
        decision = await native_reuse(self.store, intent, user_turns, estate) or estate
        if decision["decision"] == "reuse" and supports_monthly_workbook(user_turns):
            decision["metric_series"] = metric_series(intent, decision)
        decision["run_id"] = conv["runs"][-1]["id"]
        missing = decision["availability"]["missing_terms"]
        # Intent is clear and a recommendation is made: the request is triaged.
        decision["triage"] = await self._triage(conv, "triaged")
        conv["plan"] = {"decision": decision}
        await self._artifact(conv, "evidence", {"recommendation": decision["recommendation"]})
        employee = decision.get("employee_report")
        if employee:
            explanation = decision["reason"]
        else:
            with usage_scope() as used:
                explanation = await explain(self.llm, {"decision": decision, "intent": public(intent),
                                                       "missing_text": ("Missing: " + ", ".join(missing) + ".") if missing else ""})
            self._count_tokens(conv, used)
        yield self._stage(conv, "decision", "done", decision["recommendation"]["label"], decision)

        # ---- Follow-up actions (proposed by Python, accepted by a person)
        yield self._stage(conv, "actions", "running", "Proposing follow-up work")
        existing = await self.store.list_artifacts("actions", limit=500)
        proposals = act.propose({**intent, "preset_id": conv.get("preset_id")}, decision, existing)
        conv["plan"]["proposed_actions"] = proposals
        n_biz = sum(1 for p in proposals if p["kind"] == "business")
        yield self._stage(conv, "actions", "done",
                          f"{n_biz} business, {len(proposals) - n_biz} maintenance proposal(s). Nothing is assigned until you accept.",
                          {"proposals": proposals})

        conv["state"] = "idle"
        if employee:
            yield self._stage(conv, "deliver", "done", f"Employee report available: {employee['title']}", {"employee_report": employee})
            yield self._say(conv, explanation, kind="result", decision="reuse", asset_id=employee["report_id"])
        elif result.decision == Decision.REUSE:
            c = result.candidate
            yield self._stage(conv, "deliver", "done", f"Matched catalogue report '{c.name}'",
                              {"asset": cat.asset_by_id(c.asset_id), "filters": intent.get("filters", {}),
                               "preview": decision.get("preview")})
            yield self._say(conv, explanation, kind="result", decision="reuse", asset_id=c.asset_id)
        elif result.decision == Decision.NOT_FEASIBLE:
            yield self._say(conv, explanation + " You can rephrase the request using the governed KPIs.",
                            kind="result", decision="not_feasible",
                            suggestions=["Show Xarelto on-time-in-full and market access coverage for Mexico.",
                                         "How are Eylea net sales and digital engagement developing in Japan?"])
        else:
            yield self._say(conv, explanation, kind="result", decision=result.decision.value)
        yield await self._done(conv, "idle")
