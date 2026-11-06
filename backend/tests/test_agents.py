import pytest

from app import catalog as cat
from app.agents import EvidenceAgent, IntentAgent, SpecAgent
from app.agents.spec import validate
from app.llm import LLM

from .fakes import ScriptedOpenAI
from .helpers import plan


@pytest.fixture(autouse=True)
def _catalog():
    cat.reset_catalog()


def offline() -> LLM:
    return LLM(provider="mock")


def online(script):
    client = ScriptedOpenAI(script)
    return LLM(client=client, provider="openai"), client


async def test_intent_rules_parses_products_markets_and_migration():
    run = await IntentAgent(offline()).run({"transcript": [{"role": "user", "content":
        "Please create a Power BI replacement for our legacy Tableau Xarelto commercial workbook in Germany"}],
        "intent": {"measures": []}, "asked": 2, "preset": None})
    i = run.output["intent"]
    assert i["migration"] == {"from": "Tableau"} and i["filters"]["product"] == ["Xarelto"] and i["filters"]["market"] == ["DE"]


async def test_intent_rules_blocks_patient_level_requests():
    run = await IntentAgent(offline()).run({"transcript": [{"role": "user", "content": "Show patient adherence by prescriber"}],
                                            "intent": {"measures": []}, "asked": 0, "preset": None})
    assert run.output["status"] == "clear" and run.output["intent"]["unmatched_terms"]


async def test_intent_rules_asks_when_scope_missing():
    run = await IntentAgent(offline()).run({"transcript": [{"role": "user", "content": "I need net sales and gross-to-net"}],
                                            "intent": {"measures": []}, "asked": 0, "preset": None})
    assert run.output["status"] == "ask" and set(run.output["intent"]["measures"]) >= {"net_sales", "gross_to_net_rate"}


async def test_intent_llm_drops_unknown_ids():
    llm, client = online([{"json": {"status": "clear", "question": None, "suggestions": [], "intent": {
        "decision": "Review", "measures": ["net_sales", "made_up_kpi"], "dimensions": ["market"],
        "filters": {"product": ["Nubeqa", "Aspirinex"], "market": ["DE", "XX"]}}}}])
    run = await IntentAgent(llm).run({"transcript": [{"role": "user", "content": "Nubeqa net sales Germany"}],
                                      "intent": {"measures": []}, "asked": 0, "preset": None})
    i = run.output["intent"]
    assert run.mode == "llm" and i["measures"] == ["net_sales"]
    assert i["filters"] == {"product": ["Nubeqa"], "market": ["DE"]}
    assert client.requests[0]["response_format"] == {"type": "json_object"}


async def test_agent_falls_back_to_rules_when_model_fails():
    llm, _ = online([])
    run = await IntentAgent(llm).run({"transcript": [{"role": "user", "content": "OTIF for Kerendia in Spain"}],
                                      "intent": {"measures": []}, "asked": 2, "preset": None})
    assert run.mode == "rules" and run.fallback_reason and "on_time_in_full" in run.output["intent"]["measures"]


async def test_evidence_rules_records_tools_and_proofs():
    intent, d = plan("scn_repair_xarelto_mx")
    run = await EvidenceAgent(offline()).run({"intent": intent, "decision": d, "availability": d["availability"]})
    tools = [s.name.split("(")[0] for s in run.steps if s.kind == "tool"]
    assert tools[0] == "get_report" and "get_model" in tools and "get_lineage" in tools
    ev = run.output
    assert ev["base_asset"]["id"] == "AST-0217" and ev["semantic_model"]
    assert any("Variants not to use" in p["text"] for p in ev["proofs"])


async def test_evidence_llm_tool_loop_and_python_corrections():
    intent, d = plan("req_finance_gtn")
    llm, client = online([
        {"tools": [("get_kpi", {"measure_id": "net_sales"}), ("get_model", {"model_id": d["target_model_id"]})]},
        {"tools": [("get_model", {"model_id": "SM-999"})]},
        {"json": {"semantic_model": "SM-999", "notes": ["n"], "summary": "Use the shared model."}},
    ])
    run = await EvidenceAgent(llm).run({"intent": intent, "decision": d, "availability": d["availability"]})
    ev = run.output
    assert run.mode == "llm" and len(client.requests) == 3 and "tools" in client.requests[0]
    assert any(m["role"] == "tool" for m in client.requests[1]["messages"])
    assert ev["semantic_model"]["id"] == d["target_model_id"]          # invented model rejected
    assert any("SM-999" in v["text"] and not v["ok"] for v in ev["verification"])


async def _ctx(preset_id):
    intent, d = plan(preset_id)
    ev = (await EvidenceAgent(offline()).run({"intent": intent, "decision": d, "availability": d["availability"]})).output
    return {"intent": intent, "decision": d, "evidence": ev, "preset": cat.preset_by_id(preset_id)}


async def test_spec_rules_thin_report_is_valid():
    spec = (await SpecAgent(offline()).run(await _ctx("req_finance_gtn"))).output
    assert spec["semantic_model"]["id"] and spec["decision_type"] == "new_build"
    assert not [c for c in spec["validation"]["checks"] if not c["ok"] and "model serves" not in c["text"]]
    assert {m["kpi_id"] for m in spec["measures"]} == {"KPI-001", "KPI-034", "KPI-039"}


async def test_spec_repair_has_no_pages():
    spec = (await SpecAgent(offline()).run(await _ctx("scn_repair_xarelto_mx"))).output
    assert spec["pages"] == [] and spec["base_asset_id"] == "AST-0217" and spec["validation"]["passed"]


async def test_spec_llm_revises_after_validation_errors():
    ctx = await _ctx("req_finance_gtn")
    bad = {"name": "x", "pages": [{"name": "P", "visuals": [{"type": "pie", "title": "t", "measure": "net_sales", "by": "warehouse"}]}]}
    good = {"name": "Finance view", "rationale": "r", "pages": [{"name": "P", "visuals": [
        {"type": "card", "title": "Net sales", "measure": "net_sales", "by": None},
        {"type": "card", "title": "GtN", "measure": "gross_to_net_rate", "by": None},
        {"type": "bar", "title": "Budget variance by product", "measure": "budget_variance", "by": "product"}]}]}
    llm, client = online([{"json": bad}, {"json": good}])
    run = await SpecAgent(llm).run(ctx)
    assert run.mode == "llm" and run.output["validation"]["attempts"] == 2 and run.output["name"] == "Finance view"
    assert "validation_errors" in client.requests[1]["messages"][1]["content"]


def test_validate_flags_problems():
    spec = {"name": "", "decision_type": "new_build", "measures": [{"id": "net_sales", "name": "Net Sales", "certified": False}],
            "semantic_model": None, "dimensions": [], "pages": [], "owner": "", "review_date": ""}
    failed = " ".join(c["text"] for c in validate(spec) if not c["ok"])
    assert "name" in failed and "approved" in failed and "shared semantic model" in failed and "Owner" in failed
