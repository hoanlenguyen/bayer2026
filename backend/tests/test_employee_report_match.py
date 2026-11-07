import pytest

from app.employee_report_match import matching_employee_report
from app.employee_report_match import native_reuse
from app.store import MemoryStore


BASE = {"grain": "month", "measures": ["units_shipped"], "dimensions": ["month"],
        "filters": {"product": ["Nubeqa"], "market": ["DE"]}}


def test_known_kpi_scope_resolves_to_employee_report():
    assert matching_employee_report(BASE) == {"report_id": "BR-SHIPMENTS", "view_id": "shipments",
                                               "label": "Shipment volume", "url": "/briefings?view=shipments"}


@pytest.mark.parametrize("changes", [
    {"grain": "day"}, {"scope_global": True}, {"migration": {"from": "Tableau"}},
    {"other_markets": ["Vietnam"]}, {"unmatched_terms": ["patient adherence"]},
    {"measures": ["units_shipped", "gross_to_net_rate"]}, {"dimensions": ["region"]},
    {"filters": {"product": ["Eylea"], "market": ["DE"]}},
    {"filters": {"product": ["Nubeqa"], "market": ["DE", "FR"]}},
    {"filters": {"product": ["Nubeqa"]}},
])
def test_employee_report_link_requires_supported_scope(changes):
    assert matching_employee_report({**BASE, **changes}) is None


@pytest.mark.asyncio
async def test_existing_app_report_avoids_a_duplicate_build():
    original = {"decision": "new_build", "reason": "No imported match."}
    verdict = await native_reuse(MemoryStore(), BASE, ["Monthly units shipped for Nubeqa in Germany", "Decide where to act this month"], original)
    assert verdict["decision"] == "reuse"
    assert verdict["estate_assessment"] == original
    assert verdict["candidate"] is None
    native = verdict["employee_report"]
    assert native["report_id"] == "BR-SHIPMENTS" and native["owner_id"] == "OWN-007"
    assert native["evidence"]["rows"] == [10, 11] and native["period"] == "2026-10"


@pytest.mark.asyncio
@pytest.mark.parametrize("ask", ["Build me a Power BI file", "Show daily shipments", "Compare 2024 with 2025"])
async def test_workbook_view_cannot_fulfill_other_formats_or_time_requirements(ask):
    assert await native_reuse(MemoryStore(), BASE, [ask], {"decision": "new_build"}) is None
