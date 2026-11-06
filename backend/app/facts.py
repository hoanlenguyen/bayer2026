"""Preview numbers for a request from the synthetic business facts in the data pack.

Product_Market_Monthly holds synthetic monthly values per product and market.
Computed in plain Python, never by the model. Values are illustrative and must
not be read as Bayer performance.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from . import catalog as cat
from .decision import intent_products


def _rows() -> list[dict[str, Any]]:
    return cat.SHEETS.get("product_market_monthly", [])


def preview(intent: dict[str, Any], limit: int = 8) -> dict[str, Any] | None:
    """Latest-month values for the requested measures, broken down by product or market."""
    C = cat.CATALOG
    cols = [(m, C["measures"][m]["fact_column"]) for m in intent.get("measures", [])
            if m in C["measures"] and C["measures"][m].get("fact_column")]
    if not cols or not _rows():
        return None
    products = {pid for pid, p in C["products"].items() if p["name"] in intent_products(intent, C)}
    f = intent.get("filters") or {}
    markets = set(f.get("market") or [])
    regions = set(f.get("region") or [])
    rows = [r for r in _rows()
            if (not products or r["product_id"] in products)
            and (not markets or r["market_id"] in markets)
            and (not regions or C["markets"].get(r["market_id"], {}).get("region") in regions)]
    if not rows:
        return None
    latest = max(r["month"] for r in rows)
    previous = max((r["month"] for r in rows if r["month"] < latest), default=None)
    dims = intent.get("dimensions", [])
    by = "product" if "product" in dims or (len(products) != 1 and not markets) else "market"
    key = (lambda r: C["products"][r["product_id"]]["name"]) if by == "product" else (lambda r: C["markets"][r["market_id"]]["name"])

    def agg(month: str) -> dict[str, dict[str, float]]:
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in rows:
            if r["month"] == month:
                groups[key(r)].append(r)
        out = {}
        for g, rs in groups.items():
            vals = {}
            for m, col in cols:
                xs = [r[col] for r in rs if r.get(col) is not None]
                if not xs:
                    continue
                # Money and units add up; percentages and weeks are averaged.
                vals[m] = round(sum(xs), 2) if col in ("net_sales_m_eur_syn", "units_shipped_syn") else round(sum(xs) / len(xs), 1)
            out[g] = vals
        return out

    now, before = agg(latest), agg(previous) if previous else {}
    first = cols[0][0]
    ordered = sorted(now.items(), key=lambda kv: kv[1].get(first, 0), reverse=True)[:limit]
    return {
        "month": latest, "previous_month": previous, "by": by,
        "columns": [{"id": m, "name": C["measures"][m]["name"], "unit": C["measures"][m].get("fact_unit") or C["measures"][m]["unit"],
                     "lower_is_better": C["measures"][m]["lower_is_better"]} for m, _ in cols],
        "rows": [{"label": g, "values": v, "previous": before.get(g, {})} for g, v in ordered],
        "not_previewed": [C["measures"][m]["name"] for m in intent.get("measures", [])
                          if m in C["measures"] and not C["measures"][m].get("fact_column")],
        "note": "Synthetic values from the Bayer data pack (Product_Market_Monthly). Not Bayer performance.",
    }
