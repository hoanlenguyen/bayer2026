"""A dashboard built in Ask is reused when it covers a later request: same product and markets, every requested KPI,
the requested breakdown, and a period that contains the one asked for. Python only, no model."""
from app import catalog
from app.assessment import Assessment
from app.employee_report_match import covers, saved_dashboard_reuse, saved_dashboard_summary, wanted_from_intent

SAVED = {"id": "dash_saved", "title": "Nubeqa · 2 markets: Net Sales and Units Shipped", "created_at": "2026-11-08T00:11:30+00:00",
         "created_by": {"name": "Demo employee"}, "period": {"start": "2026-01", "end": "2026-10"},
         "scope": {"products": ["Nubeqa"], "markets": ["Germany", "France"]}, "dimensions": ["month", "market"],
         "columns": [{"id": "net_sales", "name": "Net Sales", "kpi_id": "KPI-001"},
                     {"id": "units_shipped", "name": "Units Shipped", "kpi_id": "KPI-014"},
                     {"id": "sales_forecast", "name": "Sales forecast", "kpi_id": None}],
         "requirements": {"products": ["P-NUB"], "markets": ["DE", "FR"], "measures": ["net_sales", "units_shipped"],
                          "dimensions": ["month", "market"]}}


def intent(**over):
    base = {"measures": ["net_sales"], "dimensions": ["month", "market"], "grain": "month", "decision": "Compare markets",
            "filters": {"product": ["Nubeqa"], "market": ["FR", "DE"]}}
    return {**base, **over}


def test_covers_follows_scope_kpis_breakdown_and_period():
    catalog.reset_catalog()
    assert covers(SAVED, wanted_from_intent(intent()))                                           # a subset of its KPIs
    assert covers(SAVED, wanted_from_intent(intent(measures=["net_sales", "units_shipped"])))
    assert not covers(SAVED, wanted_from_intent(intent(filters={"product": ["Nubeqa"], "market": ["FR"]})))  # other markets
    assert not covers(SAVED, wanted_from_intent(intent(filters={"product": ["Kerendia"], "market": ["FR", "DE"]})))
    assert not covers(SAVED, wanted_from_intent(intent(measures=["on_time_in_full"])))         # a KPI it lacks
    assert wanted_from_intent(intent(measures=["sales_forecast"])) is None                    # the forecast is not a KPI
    inside = intent(dashboard_brief={"period": {"start": "2026-05", "end": "2026-10"}})
    outside = intent(dashboard_brief={"period": {"start": "2025-11", "end": "2026-10"}})
    assert covers(SAVED, wanted_from_intent(inside)) and not covers(SAVED, wanted_from_intent(outside))
    assert wanted_from_intent(intent(grain="week")) is None and wanted_from_intent(intent(migration=True)) is None


def test_a_kpi_no_dashboard_can_show_does_not_hide_the_match():
    catalog.reset_catalog()
    # Net sales growth has no workbook column, so a build leaves it out too: the saved dashboard still covers the request.
    asked = intent(measures=["net_sales", "units_shipped", "net_sales_growth"], dimensions=["market"],
                   dashboard_brief={"period": {"start": "2026-10", "end": "2026-10"}})
    assert covers(SAVED, wanted_from_intent(asked))


def test_step_3_finds_the_dashboard_built_in_ask():
    catalog.reset_catalog()
    a = Assessment(intent(), saved_dashboards=[SAVED]).run()
    step = a.steps[3]
    assert a.saved_match["id"] == "dash_saved" and step["summary"].startswith("Already built in Ask: Nubeqa")
    assert "Dashboards built in Ask" in step["sheets"] and step["data"]["built_in_ask"]["url"] == "/dashboards/dash_saved"
    assert a.assessed["existing_report"] is True and a.assessed["existing_report_detail"]["status"] == "built_in_ask"
    nothing = Assessment(intent(), saved_dashboards=[]).run()
    assert nothing.saved_match is None and not nothing.steps[3]["summary"].startswith("Already")
    assert Assessment(intent()).run().steps[3]["sheets"] == ["Analytics_Assets", "Asset_Usage"]  # simulator: not searched


def test_new_build_becomes_reuse_only_with_a_covering_dashboard():
    catalog.reset_catalog()
    estate = {"decision": "new_build", "reason": "No report has these numbers."}
    match = saved_dashboard_summary(SAVED)
    assert saved_dashboard_reuse(None, ["Nubeqa net sales by market"], estate) is None
    reused = saved_dashboard_reuse(match, ["Nubeqa net sales by market"], estate)
    assert reused["decision"] == "reuse" and reused["change_type"] == "saved_dashboard_reuse"
    assert reused["saved_dashboard"]["url"] == "/dashboards/dash_saved" and reused["saved_dashboard"]["owner"] is None
    assert "no owner yet" in reused["reason"] and reused["estate_assessment"]["decision"] == "new_build"
    assert reused["recommendation"]["evidence"][0]["task"] == "Find existing analytics"
    # Only a new build is overridden, and a format the saved monthly view cannot give is left alone.
    assert saved_dashboard_reuse(match, ["x"], {**estate, "decision": "migrate"}) is None
    assert saved_dashboard_reuse(match, ["Nubeqa net sales weekly"], estate) is None
