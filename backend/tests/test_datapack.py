from app import catalog as cat
from app.datapack import read_workbook


def test_workbook_sheets_loaded():
    sheets = read_workbook()
    sizes = {k: len(v) for k, v in sheets.items()}
    assert sizes["analytics_assets"] == 360 and sizes["semantic_models"] == 75 and sizes["kpi_catalog"] == 56
    assert sizes["asset_usage"] == 3600 and sizes["lineage_edges"] == 438 and sizes["business_requests"] == 150
    assert "synthetic_record" not in sheets["products"][0]


def test_catalog_mapping():
    C = cat.CATALOG
    assert len(C["measures"]) == 18 and all(m["certified"] for m in C["measures"].values())
    ns = C["measures"]["net_sales"]
    assert ns["kpi_id"] == "KPI-001" and {v["kpi_id"] for v in ns["variants"]} == {"KPI-002", "KPI-003"}
    a1 = cat.asset_by_id("AST-0001")
    assert "demand_forecast_accuracy" in a1["conflicts"] and a1["views_90d"] > 0
    assert cat.model_by_id("SM-001")["measures"]
    assert len(cat.PRESETS) == 14 and sum(1 for p in cat.PRESETS if p["id"].startswith("req_")) == 10
