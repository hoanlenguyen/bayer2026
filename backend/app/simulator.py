"""One sentence of the chat simulator: two people talk, and the system speaks only when a sentence needs a decision.

Flow: gate agent labels the sentence → if it needs a decision, classify the open thread → Python writes what C says.
A request too vague to check (no KPI, product or market) gets no reply: C keeps listening, and checks again when a
later sentence adds business details. It never asks a question, so it only speaks once it has something to say.

C uses no chat model: the recommendation comes from the same rules as the Ask flow, and its text from the templates
here. Nothing is saved. The browser holds the transcript and sends it back with each sentence.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, AsyncIterator

from . import actions as act
from . import catalog as cat
from .agents.gate import ConversationGateAgent
from .classify import read_request
from .decider import jev_cost
from .decision import Decision
from .llm import usage_scope, usage_total
from .pipeline import STAGES, analyse, intent_summary, label_list, public

if TYPE_CHECKING:
    from .pipeline import Pipeline

RECENT_MESSAGES = 6      # what the gate sees of the chat before this sentence
RECENT_CHARS = 500       # per message
THREAD_CHARS = 2000      # same limit as /api/v2/classify

Event = dict[str, Any]

def open_thread(history: list[dict[str, Any]]) -> dict[str, Any]:
    """The sentences this request is made of: back to C's last answer or a repeat, leaving out small talk.
    `pending` is the first request in it that was too vague to check, which later sentences may complete."""
    sentences: list[str] = []
    pending: str | None = None
    for m in reversed(history):
        if m["speaker"] == "C" or m.get("label") == "already_answered":
            break
        if m.get("label") != "off_topic":
            sentences.insert(0, m["text"])
        if m.get("label") == "needs_context":
            pending = m["text"]
    return {"sentences": sentences, "pending": pending}


def request_text(sentences: list[str], text: str) -> str:
    """Joined oldest first, keeping the newest words when it runs over the limit."""
    return " ".join([*sentences, text])[-THREAD_CHARS:]


def is_thin(result: dict[str, Any]) -> bool:
    """Too little to check: no KPI named, or only a loose vector match with no product or market to anchor it."""
    if result["not_available"]:
        return False
    kpis = result["governed_kpis"]
    loose = all(k.get("matched_by") == "vector" for k in kpis)
    return not kpis or (loose and not result["product"] and not result["market"])


def stage(name: str, summary: str, data: dict[str, Any]) -> Event:
    return {"type": "stage", "stage": name, "title": STAGES[name], "status": "done", "summary": summary, "data": data}


def evidence_stages(intent: dict[str, Any], tags: dict[str, Any], plan: dict[str, Any], gate_trace: dict[str, Any]) -> list[Event]:
    """The same steps and recommendation the Ask flow shows. Nothing is created, so the request has no status."""
    triage = {"status": None, "urgency": intent["urgency"], "similar": None, "request_id": None, "request_store": None}
    classification = {k: v for k, v in tags.items() if k not in ("steps", "recommendation")}
    decision = {**plan["decision"], "triage": triage}
    result = plan["result"]
    out = [stage("intent", intent_summary(intent), {**public(intent), "triage": triage, "classification": classification, "agent": gate_trace})]
    out += [stage(name, s["summary"], s["data"]) for name, s in plan["stages"].items()]
    out.append(stage("decision", tags["recommendation"]["label"], decision))
    proposals = act.propose({**intent, "preset_id": None}, decision, [])
    if proposals:
        n_biz = sum(1 for p in proposals if p["kind"] == "business")
        out.append(stage("actions", f"{n_biz} business, {len(proposals) - n_biz} maintenance suggestion(s).", {"proposals": proposals}))
    if result.decision == Decision.REUSE:
        out.append(stage("deliver", f"Opened '{result.candidate.name}'", {"asset": cat.asset_by_id(result.candidate.asset_id),
                                                                         "filters": intent.get("filters", {}), "preview": decision.get("preview")}))
    return out


def answer_key(result: dict[str, Any]) -> str:
    """Two answers with the same key would say the same thing."""
    detail = result["existing_report_detail"]
    target = (detail["report"] or {}).get("id") or (result["semantic_model"] or {}).get("id") or ",".join(result["not_available"])
    return f"{detail['decision']}:{target}"


def answer_text(result: dict[str, Any]) -> str:
    """What C says. Only a plain reuse may be called ready to use."""
    detail, rec = result["existing_report_detail"], result["recommendation"]
    report = detail["report"]
    if detail["decision"] == "reuse":
        where = f" You can reuse it in {report['workspace']}." if report.get("workspace") else " You can reuse it."
        owner = f" Owner: {report['owner']}." if report.get("owner") else ""
        return f"Hey, this already exists. {report['name']} covers it.{where}{owner}"
    if detail["decision"] == "repair":
        return f"Hey, before anyone builds this: {rec['reason']}"
    if detail["decision"] == "not_feasible" and result["not_available"]:
        return f"Hey, this data is not in the catalog: {', '.join(result['not_available'])}. {rec['reason']}"
    missing = f" Not in the catalog: {', '.join(result['not_available'])}." if result["not_available"] else ""
    return f"Hey, before anyone builds this, I recommend: {rec['label']}. {rec['reason']}{missing}"


def gate_event(agent: ConversationGateAgent, run: Any) -> Event:
    return {"type": "gate", "label": run.output["label"], "confidence": run.output["confidence"], "reason": run.output["reason"],
            "decided_by": run.mode, "model": run.model, "ms": run.ms, "usage": run.usage, "cost": jev_cost(run.usage),
            "fallback_reason": run.fallback_reason, "jev_on": agent.jev_on()}


async def turn(pipeline: "Pipeline", speaker: str, text: str, history: list[dict[str, Any]]) -> AsyncIterator[Event]:
    thread = open_thread(history)
    recent = [{"speaker": m["speaker"], "text": m["text"][:RECENT_CHARS]} for m in history[-RECENT_MESSAGES:]]
    agent = pipeline.gate_agent
    run = await agent.run({"text": text, "speaker": speaker, "recent": recent, "pending_request": thread["pending"]})
    yield gate_event(agent, run)
    label = run.output["label"]
    # Business talk can complete a vague request already waiting, so it is checked too. Small talk never is.
    if not (label == "needs_decision" or (label == "business_talk" and thread["pending"])):
        yield {"type": "done"}
        return

    yield {"type": "searching"}
    with usage_scope() as used:
        found = await read_request(request_text(thread["sentences"], text), pipeline.vectors, pipeline.decider)
    usage = usage_total(used)
    intent = found["intent"]
    # Same defaults as the Ask flow once a request is clear.
    intent["decision"] = f"Monitor {label_list(intent['measures'], 'm') or 'the requested numbers'}"
    intent["department"] = cat.department_for(intent["measures"])
    plan = analyse(intent)
    tags = plan["tags"]
    result = {**tags, "governed_kpis": [{**k, **found["matched_by"].get(k["id"], {})} for k in tags["governed_kpis"]]}

    if is_thin(result):
        yield {"type": "needs_context", "usage": usage}
        yield {"type": "done"}
        return

    key = answer_key(result)
    if any(m.get("answer_key") == key for m in history):
        yield {"type": "already_answered", "answer_key": key, "usage": usage}
        yield {"type": "done"}
        return

    detail, rec = result["existing_report_detail"], result["recommendation"]
    yield {"type": "reply", "kind": "answer", "text": answer_text(result), "answer_key": key, "usage": usage, "decision": detail["decision"],
           "recommendation": {"value": rec["value"], "label": rec["label"], "reason": rec["reason"], "rule": rec["rule"],
                              "rules_applied": rec["rules_applied"],
                              "evidence": [{"step": e["step"], "task": e["task"], "summary": e["summary"]} for e in rec["evidence"]]},
           "report": detail["report"], "stages": evidence_stages(intent, tags, plan, run.trace())}
    yield {"type": "done"}
