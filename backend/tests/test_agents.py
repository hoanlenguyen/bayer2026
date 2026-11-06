import pytest

from app.agents import EvidenceAgent, IntentAgent, SpecAgent
from app.agents.spec import validate
from app.catalog import CATALOG, reset_catalog
from app.decision import data_availability, decide, rank_candidates
from app.llm import LLM

from .fakes import ScriptedOpenAI


@pytest.fixture(autouse=True)
def _catalog():
    reset_catalog()


def offline() -> LLM:
    return LLM(provider="mock")


def online(script) -> tuple[LLM, ScriptedOpenAI]:
    client = ScriptedOpenAI(script)
    return LLM(client=client, provider="openai"), client


def late_deliveries():
    intent = {"question": "late deliveries", "measures": ["late_shipments", "days_late"],
              "dimensions": ["customer", "carrier", "priority"], "grain": "day", "filters": {},
              "unmatched_terms": [], "decision": "Escalate late shipments"}
    decision = decide(rank_candidates(intent, CATALOG["assets"]), True).to_dict()
    return intent, decision, data_availability(intent, CATALOG)


# ---------------------------------------------------------------- intent
async def test_intent_rules_asks_then_clears():
    agent = IntentAgent(offline())
    intent = {"measures": [], "dimensions": [], "grain": None, "filters": {}, "unmatched_terms": []}
    run = await agent.run({"transcript": [{"role": "user", "content": "I need a late deliveries dashboard"}],
                           "intent": intent, "asked": 0, "preset": None})
    assert run.mode == "rules" and run.output["status"] == "ask"
    assert run.output["intent"]["measures"] == ["late_shipments"]


async def test_intent_llm_drops_unknown_ids():
    llm, client = online([{"json": {"status": "clear", "question": None, "suggestions": [],
                                    "intent": {"decision": "Act today", "measures": ["late_shipments", "made_up_kpi"],
                                               "dimensions": ["carrier"], "grain": "day"}}}])
    run = await IntentAgent(llm).run({"transcript": [{"role": "user", "content": "late deliveries by carrier"}],
                                      "intent": {"measures": []}, "asked": 0, "preset": None})
    assert run.mode == "llm" and run.model == "gpt-6-luna"
    assert run.output["intent"]["measures"] == ["late_shipments"]
    assert any(s.kind == "check" and not s.ok for s in run.steps)
    assert client.requests[0]["response_format"] == {"type": "json_object"}


async def test_agent_falls_back_to_rules_when_model_fails():
    llm, _ = online([])  # script exhausted: every call raises
    run = await IntentAgent(llm).run({"transcript": [{"role": "user", "content": "OEE by line today"}],
                                      "intent": {"measures": []}, "asked": 2, "preset": None})
    assert run.mode == "rules" and run.fallback_reason
    assert "oee" in run.output["intent"]["measures"]


# ---------------------------------------------------------------- evidence
async def test_evidence_rules_records_tool_calls():
    intent, decision, availability = late_deliveries()
    run = await EvidenceAgent(offline()).run({"intent": intent, "decision": decision, "availability": availability})
    tools = [s.name.split("(")[0] for s in run.steps if s.kind == "tool"]
    assert tools[0] == "get_report" and "get_dataset" in tools
    ev = run.output
    assert ev["datasets"] == ["shipments_fact"]
    assert {"carrier_id", "priority", "customer_id"} <= set(ev["columns"]["shipments_fact"])


async def test_evidence_llm_tool_loop_and_python_corrections():
    llm, client = online([
        {"tools": [("get_report", {"report_id": "rpt_delivery_perf"}), ("get_dataset", {"dataset_id": "shipments_fact"})]},
        {"tools": [("get_dataset", {"dataset_id": "warehouse_magic"})]},
        {"json": {"datasets": ["shipments_fact", "warehouse_magic"], "columns": {"shipments_fact": ["carrier_id", "invented_col"]},
                  "notes": ["priority column exists"], "summary": "Shipments table has everything."}},
    ])
    intent, decision, availability = late_deliveries()
    run = await EvidenceAgent(llm).run({"intent": intent, "decision": decision, "availability": availability})
    assert run.mode == "llm" and run.model == "gpt-6-astra"
    assert len(client.requests) == 3 and "tools" in client.requests[0]
    # tool results were sent back to the model
    assert any(m["role"] == "tool" for m in client.requests[1]["messages"])
    ev = run.output
    assert ev["datasets"] == ["shipments_fact"]                       # unknown dataset removed
    assert "invented_col" not in ev["columns"]["shipments_fact"]      # unknown column removed
    assert "priority" in ev["columns"]["shipments_fact"]              # required column added
    texts = " ".join(v["text"] for v in ev["verification"])
    assert "warehouse_magic" in texts and "invented_col" in texts
    assert ev["summary"] == "Shipments table has everything."
    assert not [s for s in run.steps if s.name.startswith("get_dataset(dataset_id=warehouse_magic") and s.ok]


# ---------------------------------------------------------------- spec
async def _evidence():
    intent, decision, availability = late_deliveries()
    ev = (await EvidenceAgent(offline()).run({"intent": intent, "decision": decision, "availability": availability})).output
    return {"intent": intent, "decision": decision, "evidence": ev, "preset": None}


async def test_spec_rules_is_valid():
    ctx = await _evidence()
    run = await SpecAgent(offline()).run(ctx)
    spec = run.output
    assert spec["validation"]["passed"], spec["validation"]
    assert spec["base_asset_id"] == "rpt_delivery_perf"
    assert spec["change"]["add_dimensions"] == ["carrier", "priority"]


async def test_spec_llm_revises_after_validation_errors():
    bad = {"name": "x", "pages": [{"name": "Today", "visuals": [
        {"type": "pie", "title": "Late", "measure": "late_shipments", "by": "warehouse"}]}], "rationale": "r"}
    good = {"name": "x", "pages": [{"name": "Today", "visuals": [
        {"type": "card", "title": "Late shipments", "measure": "late_shipments", "by": None},
        {"type": "card", "title": "Days late", "measure": "days_late", "by": None},
        {"type": "table", "title": "Late by carrier", "measure": "late_shipments", "by": "carrier"}]}],
        "rationale": "Numbers first, then where to act."}
    llm, client = online([{"json": bad}, {"json": good}])
    run = await SpecAgent(llm).run(await _evidence())
    spec = run.output
    assert run.mode == "llm" and spec["validation"]["passed"] and spec["validation"]["attempts"] == 2
    assert "validation_errors" in client.requests[1]["messages"][1]["content"]
    assert spec["name"] == "Delivery Performance"   # extend keeps the base report name


def test_validate_flags_problems():
    spec = {"name": "", "pages": [], "measures": [{"id": "otif", "name": "OTIF %", "certified": False}],
            "dimensions": ["material"], "entities": ["shipments_fact"], "owner": "", "review_date": ""}
    failed = [c["text"] for c in validate(spec) if not c["ok"]]
    assert any("name" in f for f in failed)
    assert any("certified" in f for f in failed)
    assert any("material" in f for f in failed)
