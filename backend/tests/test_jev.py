"""Jev is optional: each phase is off by default, used only when confident, and any failure falls through."""
import json

import httpx2
import pytest
from fastapi.testclient import TestClient
from typesafe_sdk import AsyncTypeSafeClient, Choice, Noul

from app import catalog as cat
from app.agents import IntentAgent, RelevanceAgent
from app.decider import Decider, get_decider
from app.llm import LLM
from app.main import app
from app.pipeline import Pipeline
from app.settings import settings
from app.store import MemoryStore

from .fakes import ScriptedJev, ScriptedOpenAI
from .helpers import sse, stage


@pytest.fixture(autouse=True)
def _catalog():
    cat.reset_catalog()


def relevance_ctx(text="Show net sales", **extra):
    return {"text": text, "question": None, "suggestions": [], "pending": None, "request": None, **extra}


def intent_ctx(text="Show net sales for Eylea in Japan", **extra):
    return {"transcript": [{"role": "user", "content": text}], "asked": 0, "preset": None, "kpi_suggestions": [],
            "intent": {"question": text, "measures": [], "dimensions": [], "grain": None, "filters": {}, "unmatched_terms": [], "decision": None}, **extra}


def gpt(*script):
    client = ScriptedOpenAI(list(script))
    return LLM(client=client, provider="openai"), client


def jev(script, *phases):
    client = ScriptedJev(script)
    return Decider(client, set(phases), model="jev-1.14.0"), client


def verdicts(**p):
    return {"verdict": {"accept": 0.0, "meaningless": 0.0, "off_topic": 0.0, "not_enough": 0.0, **p}}


GPT_ACCEPT = {"json": {"verdict": "accept", "reason": "ok"}}


# ---------------------------------------------------------------- off by default
def test_off_without_phases_or_key(monkeypatch):
    assert get_decider().enabled("relevance") is False
    monkeypatch.setattr(type(settings), "__setattr__", object.__setattr__, raising=False)
    object.__setattr__(settings, "jev_phases", {"relevance"})
    object.__setattr__(settings, "typesafe_api_key", None)
    try:
        assert get_decider().enabled("relevance") is False
    finally:
        object.__setattr__(settings, "jev_phases", set())


async def test_phase_not_listed_never_calls_jev():
    decider, client = jev([], "kpis")
    llm, _ = gpt(GPT_ACCEPT)
    run = await RelevanceAgent(llm, decider).run(relevance_ctx())
    assert run.mode == "llm" and client.requests == []


# ---------------------------------------------------------------- the real SDK, fake network
async def test_real_sdk_request_and_response_format():
    seen = {}

    def handler(request):
        seen["url"], seen["auth"], seen["body"] = str(request.url), request.headers["authorization"], json.loads(request.content)
        return httpx2.Response(200, json={
            "model": "jev-1.14.0", "usage": {"input_tokens": 42, "output_tokens": 0},
            "answers": {"verdict": {"type": "choice", "choice": "accept", "confidence": 0.9,
                                    "probabilities": {"accept": 0.9, "meaningless": 0.03, "off_topic": 0.04, "not_enough": 0.03}}}})

    client = AsyncTypeSafeClient(api_key="test-key", transport=httpx2.MockTransport(handler))
    run = await RelevanceAgent(LLM(provider="mock"), Decider(client, {"relevance"}, model="jev-1.14.0")).run(relevance_ctx("Show net sales"))
    assert seen["url"] == "https://api.typesafe.ai/v1/systemone" and seen["auth"] == "Bearer test-key"
    assert seen["body"]["model"] == "jev-1.14.0" and seen["body"]["state"]["message"] == "Show net sales"
    question = seen["body"]["questions"]["verdict"]
    assert question["type"] == "choice" and list(question["criteria"])[0] == "accept"
    assert run.mode == "jev" and run.model == "jev-1.14.0" and run.output["verdict"] == "accept"
    assert run.usage["input_tokens"] == 42 and run.usage["by_model"]["jev-1_14_0"]["calls"] == 1


async def test_real_sdk_multi_question_noul_format():
    from app.agents.intent import jev_match

    def handler(request):
        body = json.loads(request.content)
        assert all(q["type"] == "noul" for q in body["questions"].values())
        return httpx2.Response(200, json={"model": "jev-1.14.0", "usage": {"input_tokens": 9, "output_tokens": 0},
                                          "answers": {n: {"type": "noul", "noul": 0.95 if n == "kpi:net_sales" else 0.02} for n in body["questions"]}})

    client = AsyncTypeSafeClient(api_key="k", transport=httpx2.MockTransport(handler))
    found = await jev_match(Decider(client, {"kpis"}, model="jev-1.14.0"), "Show net sales")
    assert found == {"measures": ["net_sales"], "dimensions": [], "migration": False, "unsure": []}


async def test_real_sdk_bad_key_falls_through():
    client = AsyncTypeSafeClient(api_key="k", transport=httpx2.MockTransport(lambda r: httpx2.Response(401, json={"detail": "bad key"})))
    llm, _ = gpt(GPT_ACCEPT)
    run = await RelevanceAgent(llm, Decider(client, {"relevance"})).run(relevance_ctx())
    assert run.mode == "llm" and run.output["verdict"] == "accept"
    assert any("Jev failed" in s.name for s in run.steps)


# ---------------------------------------------------------------- relevance thresholds
@pytest.mark.parametrize("probabilities,mode,verdict", [
    ({"accept": 0.70, "off_topic": 0.30}, "jev", "accept"),       # at the accept line
    ({"accept": 0.69, "off_topic": 0.31}, "llm", "accept"),       # below it
    ({"off_topic": 0.80, "accept": 0.20}, "jev", "off_topic"),    # at the reject line
    ({"off_topic": 0.79, "accept": 0.21}, "llm", "accept"),       # rejecting needs more certainty than accepting
    ({"meaningless": 0.95, "accept": 0.05}, "jev", "meaningless"),
])
async def test_relevance_thresholds(probabilities, mode, verdict):
    decider, _ = jev([verdicts(**probabilities)], "relevance")
    llm, client = gpt(GPT_ACCEPT)
    run = await RelevanceAgent(llm, decider).run(relevance_ctx())
    assert (run.mode, run.output["verdict"]) == (mode, verdict)
    assert (client.requests == []) == (mode == "jev")


@pytest.mark.parametrize("failure", [TimeoutError("timed out"), RuntimeError("429 rate limited"), RuntimeError("529 overloaded")])
async def test_relevance_failures_fall_through_to_gpt_then_rules(failure):
    decider, _ = jev([failure], "relevance")
    llm, _ = gpt(GPT_ACCEPT)
    assert (await RelevanceAgent(llm, decider).run(relevance_ctx())).mode == "llm"

    decider, _ = jev([failure], "relevance")
    run = await RelevanceAgent(LLM(provider="mock"), decider).run(relevance_ctx())
    assert run.mode == "rules" and run.output["verdict"] == "accept"

    decider, _ = jev([failure], "relevance")
    llm, _ = gpt()  # GPT is down too
    assert (await RelevanceAgent(llm, decider).run(relevance_ctx())).mode == "rules"


async def test_suggestion_shortcut_still_needs_no_call():
    decider, client = jev([], "relevance")
    run = await RelevanceAgent(LLM(provider="mock"), decider).run(relevance_ctx("Germany", suggestions=["Germany"], question="Which market?"))
    assert run.output["verdict"] == "accept" and client.requests == []


# ---------------------------------------------------------------- KPIs
async def test_kpis_confident_needs_no_gpt():
    decider, client = jev([{"kpi:net_sales": 0.95, "dim:product": 0.9, "*": 0.05}], "kpis")
    llm, openai = gpt()
    run = await IntentAgent(llm, decider).run(intent_ctx())
    assert run.mode == "jev" and openai.requests == [] and len(client.requests) == 1
    intent = run.output["intent"]
    assert intent["measures"] == ["net_sales"] and "product" in intent["dimensions"]
    assert intent["filters"]["product"] == ["Eylea"] and intent["filters"]["market"] == ["JP"]  # still from the rules


async def test_kpis_offers_only_approved_kpis():
    decider, client = jev([{"*": 0.05}], "kpis")
    await IntentAgent(LLM(provider="mock"), decider).run(intent_ctx())
    offered = {n.split(":", 1)[1] for n in client.requests[0]["questions"] if n.startswith("kpi:")}
    assert offered == {m for m, d in cat.CATALOG["measures"].items() if d["certified"]}
    assert all(isinstance(q, Noul) for q in client.requests[0]["questions"].values())


@pytest.mark.parametrize("unsure", [0.31, 0.5, 0.69])
async def test_any_unsure_answer_sends_the_whole_message_to_gpt(unsure):
    decider, _ = jev([{"kpi:net_sales": 0.95, "kpi:net_sales_growth": unsure, "*": 0.05}], "kpis")
    llm, openai = gpt({"json": {"status": "clear", "question": None, "suggestions": [],
                                "intent": {"decision": "Review", "measures": ["net_sales"], "dimensions": [], "filters": {}}}})
    run = await IntentAgent(llm, decider).run(intent_ctx())
    assert run.mode == "llm" and len(openai.requests) == 1


async def test_confident_no_at_the_lines():
    from app.agents.intent import jev_match

    decider, _ = jev([{"kpi:net_sales": 0.70, "kpi:net_sales_growth": 0.30, "*": 0.05}], "kpis")
    found = await jev_match(decider, "x")
    assert found["measures"] == ["net_sales"] and found["unsure"] == []


async def test_non_english_skips_jev_because_the_questions_are_english():
    decider, client = jev([], "kpis")
    llm, openai = gpt({"json": {"status": "clear", "question": None, "suggestions": [],
                                "intent": {"decision": "x", "measures": ["net_sales"], "dimensions": [], "filters": {}}}})
    run = await IntentAgent(llm, decider).run(intent_ctx("Näytä nettomyynti"))
    assert run.mode == "llm" and client.requests == [] and len(openai.requests) == 1


async def test_missing_details_use_the_question_templates():
    decider, _ = jev([{"kpi:net_sales": 0.95, "*": 0.05}], "kpis")
    llm, openai = gpt()
    run = await IntentAgent(llm, decider).run(intent_ctx("Show net sales"))
    assert run.mode == "jev" and openai.requests == []
    assert run.output["status"] == "ask" and "products and markets" in run.output["question"]


async def test_follow_up_after_jev_keeps_the_kpis():
    decider, _ = jev([{"kpi:net_sales": 0.95, "*": 0.05}, {"kpi:net_sales": 0.95, "*": 0.05}], "kpis")
    agent = IntentAgent(LLM(provider="mock"), decider)
    first = await agent.run(intent_ctx("Show net sales"))
    assert first.output["intent"]["_pending"] == "scope"
    ctx = intent_ctx("Show net sales", asked=1)
    ctx["intent"] = first.output["intent"]
    ctx["transcript"] += [{"role": "assistant", "content": first.output["question"]}, {"role": "user", "content": "All products, all markets"}]
    second = await agent.run(ctx)
    assert second.output["intent"]["measures"] == ["net_sales"] and second.output["intent"]["scope_global"] is True
    assert not second.output["intent"].get("unmatched_terms")


# ---------------------------------------------------------------- urgency
def urgency(**p):
    return {"urgency": {"normal": 0.0, "high": 0.0, "urgent": 0.0, **p}}


@pytest.mark.parametrize("probabilities,value,source", [
    ({"urgent": 0.85, "normal": 0.15}, "urgent", "model"),
    ({"high": 0.80, "normal": 0.20}, "high", "model"),
    ({"urgent": 0.79, "normal": 0.21}, "normal", "default"),      # not sure enough to raise
    ({"normal": 0.95, "high": 0.05}, "normal", "default"),
])
async def test_urgency_only_raises_when_sure(probabilities, value, source):
    decider, _ = jev([urgency(**probabilities)], "urgency")
    run = await IntentAgent(LLM(provider="mock"), decider).run(intent_ctx(asked=2))
    assert (run.output["intent"]["urgency"]["value"], run.output["intent"]["urgency"]["source"]) == (value, source)


async def test_deadline_words_need_no_jev_call():
    decider, client = jev([], "urgency")
    run = await IntentAgent(LLM(provider="mock"), decider).run(intent_ctx("Show net sales by tomorrow", asked=2))
    assert run.output["intent"]["urgency"]["source"] == "inferred" and client.requests == []


async def test_urgency_failure_does_not_stop_the_agent():
    decider, _ = jev([RuntimeError("down")], "urgency")
    run = await IntentAgent(LLM(provider="mock"), decider).run(intent_ctx(asked=2))
    assert run.output["intent"]["urgency"]["source"] == "default" and any("Preparation" in s.name for s in run.steps)


async def test_urgency_hint_used_on_the_gpt_path():
    decider, _ = jev([urgency(urgent=0.9, normal=0.1)], "urgency")
    llm, _ = gpt({"json": {"status": "clear", "question": None, "suggestions": [],
                           "intent": {"decision": "x", "measures": ["net_sales"], "dimensions": [], "filters": {}}}})
    run = await IntentAgent(llm, decider).run(intent_ctx())
    assert run.mode == "llm" and run.output["intent"]["urgency"]["source"] == "model"


# ---------------------------------------------------------------- presets and token counts
async def test_preset_needs_no_model_at_all():
    preset = next(p for p in cat.PRESETS if p["id"] == "scn_reuse_eylea_jp")
    decider, jev_client = jev([], "kpis", "urgency")
    llm, openai = gpt()
    ctx = intent_ctx(preset["prompt"], preset=preset)
    ctx["intent"].update(measures=list(preset["measures"]), decision=preset["decision"])
    run = await IntentAgent(llm, decider).run(ctx)
    assert run.mode == "rules" and openai.requests == [] and jev_client.requests == []
    assert run.output["status"] == "clear" and run.usage["calls"] == 0


async def test_preset_with_changed_text_is_read_normally():
    preset = next(p for p in cat.PRESETS if p["id"] == "scn_reuse_eylea_jp")
    llm, openai = gpt({"json": {"status": "clear", "question": None, "suggestions": [],
                                "intent": {"decision": "x", "measures": ["net_sales"], "dimensions": [], "filters": {}}}})
    await IntentAgent(llm).run(intent_ctx("Something else entirely about net sales", preset=preset))
    assert len(openai.requests) == 1


async def _collect(agen):
    return [e async for e in agen]


async def test_question_total_counts_every_call_and_model():
    decider, _ = jev([verdicts(accept=0.9, off_topic=0.1), {"kpi:net_sales": 0.95, "kpi:market_access_coverage": 0.95, "*": 0.05}], "relevance", "kpis")
    llm, openai = gpt({"text": "Use it.", "usage": (120, 30)})
    pipeline = Pipeline(MemoryStore(), llm, decider)
    evs = await _collect(pipeline.chat(None, "Decide on Eylea in Japan, show net sales and access, by tomorrow, monthly review", None))
    done = evs[-1]
    assert done["type"] == "done"
    tokens = done["tokens"]
    assert tokens["by_model"]["jev-1_14_0"]["calls"] >= 1
    saved = await pipeline.store.get(evs[0]["id"])
    assert saved["runs"][-1]["tokens"] == tokens  # MongoDB keys can't hold dots: model names are stored without them
    assert not any("." in key for key in tokens["by_model"])


async def test_gpt_usage_is_recorded_in_the_trace():
    llm, _ = gpt({**GPT_ACCEPT, "usage": (200, 15)})
    run = await RelevanceAgent(llm).run(relevance_ctx())
    assert run.usage["input_tokens"] == 200 and run.usage["output_tokens"] == 15
    assert run.trace()["usage"]["calls"] == 1


# ---------------------------------------------------------------- classify route, off by default
def test_classify_route_works_with_jev_off():
    with TestClient(app) as client:
        body = client.post("/api/v2/classify", json={"request": "Show market access coverage."}).json()
    assert body["governed_kpis"][0]["matched_by"] == "keyword"


async def test_classify_uses_jev_when_no_keyword_matches():
    from app.classify import classify_request
    from app.llm import LLM as _LLM
    from app.vectors import LocalEmbedder, VectorStore

    decider, client = jev([urgency(high=0.9, normal=0.1), {"kpi:net_sales": 0.9, "*": 0.05}], "kpis", "urgency")
    body = await classify_request("How much money did the brands bring in?", VectorStore(LocalEmbedder()), decider)
    assert [k["id"] for k in body["governed_kpis"]] == ["net_sales"] and body["governed_kpis"][0]["matched_by"] == "jev"
    assert body["urgency"]["source"] == "model" and body["urgency"]["value"] == "high"
    assert len(client.requests) == 2


async def test_classify_survives_jev_failing():
    from app.classify import classify_request
    from app.vectors import LocalEmbedder, VectorStore

    decider, _ = jev([RuntimeError("down"), RuntimeError("down")], "kpis", "urgency")
    body = await classify_request("How much money did the brands bring in?", VectorStore(LocalEmbedder()), decider)
    assert body["urgency"]["source"] in ("vector_vote", "default")
