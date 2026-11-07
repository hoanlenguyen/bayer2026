"""App-defined employee reports backed by the synthetic workbook."""

FILTERS = {"product_id": "P-NUB", "market_id": "DE"}
VIEWS = {
    "sales": ("BR-SALES", "Commercial performance", "Net sales and forecast", "KPI-001", "€m", "net_sales_m_eur_syn"),
    "shipments": ("BR-SHIPMENTS", "Nubeqa sales & shipments", "Shipment volume", "KPI-014", "units", "units_shipped_syn"),
    "otif": ("BR-OTIF", "Delivery performance", "On-time, in-full delivery", "KPI-020", "%", "otif_pct_syn"),
}
EMPLOYEE_REPORTS = [(report_id, name, kpi, "Nubeqa") for report_id, name, _, kpi, _, _ in VIEWS.values()]
DEFAULTS = {"commercial": ["sales", "shipments"], "supply": ["shipments", "otif"]}
