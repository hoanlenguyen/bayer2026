import pytest
from fastapi.testclient import TestClient

from app import catalog
from app.dashboard_intake import requested_period
from app.main import app
from tests.helpers import sse, stage


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def ask(client, message, cid=None):
    return sse(client.post("/api/chat", json={"message": message, "conversation_id": cid}))


def test_vague_dashboard_continues_until_both_scope_axes_purpose_and_period_are_known(client):
    first = ask(client, "I need a dashboard")
    cid = first[0]["id"]
    for answer, fragment in [("Net sales and units shipped", "products and markets"), ("Nubeqa", "markets"),
                             ("France", "decision"), ("Decide where to allocate stock", "reporting period"),
                             ("March through December 2026", "reporting period")]:
        events = ask(client, answer, cid)
        assert events[-1]["state"] == "clarifying"
        assert fragment in next(e["content"] for e in events if e.get("kind") == "question")
        assert not stage(events, "decision")
    final = ask(client, "2026-08 to 2026-10", cid)
    assert stage(final, "decision")["data"]["decision"] == "new_build"
    intent = stage(final, "intent")["data"]
    assert intent["dashboard_brief"]["period"] == {"start": "2026-08", "end": "2026-10"}
    assert intent["filters"] == {"product": ["Nubeqa"], "market": ["FR"]}
    model = catalog.model_by_id(stage(final, "decision")["data"]["target_model_id"])
    assert model["region_scope"] in {"EMEA", "Global"} and model["product_scope"] in {"Nubeqa", "All Pharma"}


def test_fully_specified_dashboard_goes_straight_to_the_decision(client):
    result = ask(client, "Build a dashboard for Nubeqa net sales and units shipped in France from January to October 2026 to allocate stock.")
    assert result[-1]["state"] == "idle"
    assert stage(result, "intent")["data"]["decision"] == "allocate stock"
    assert stage(result, "decision")["data"]["decision"] == "new_build"


def test_mixed_unavailable_requirement_is_preserved(client):
    result = ask(client, "Build a dashboard showing Nubeqa net sales and patient adherence in France.")
    assert stage(result, "decision")["data"]["decision"] == "not_feasible"
    assert stage(result, "intent")["data"]["unmatched_terms"]


def test_employee_can_name_an_unknown_kpi_when_prompted(client):
    initial = ask(client, "I need a dashboard")
    result = ask(client, "Customer churn", initial[0]["id"])
    assert stage(result, "decision")["data"]["decision"] == "not_feasible"
    assert stage(result, "intent")["data"]["unmatched_terms"] == ["Customer churn"]


@pytest.mark.parametrize(("text", "expected"), [
    ("May I have a dashboard?", None), ("due by October", None),
    ("Q1 through Q3 2026", ("2026-01", "2026-09")), ("Q1 2026 and Q3 2026", None),
    ("January and October 2026", None), ("May 2026", ("2026-05", "2026-05")),
    ("Q3 2026", ("2026-07", "2026-09")), ("Last 3 workbook months", ("2026-08", "2026-10")),
])
def test_reporting_windows(text, expected):
    result = requested_period(text, [f"2026-{i:02}" for i in range(1, 11)])
    assert ((result["start"], result["end"]) if result else None) == expected
