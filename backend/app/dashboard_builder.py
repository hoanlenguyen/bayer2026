"""Resolve a saved dashboard brief and calculate an immutable local workbook view."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import math
import re
from collections import defaultdict

from . import catalog
from .agents.intent import match_filters, match_measures
from .dashboard_intake import requires_grain_change, workbook_months
from .decision import data_availability, decide, rank_candidates
from .employee_report_match import matching_employee_report

SOURCE = "Product_Market_Monthly"
BUILDABLE = {"new_build", "create", "extend"}
DIMENSIONS = {"month", "product", "market", "region", "therapeutic_area"}
ADDITIVE = {"net_sales", "units_shipped"}
UNSUPPORTED = re.compile(
    r"\b(?:power\s?bi|pbix|pbip|tableau|excel|export|csv|pdf|powerpoint|yoy|ytd|(?:by|per) (?:channel|hospital|clinic|customer|sku|store|site|postcode|city)|"
    r"patient.level|prescriber.level|hcp.level)\b", re.I)
UNKNOWN_GOAL = re.compile(r"^(?:i (?:don['’]?t know|am not sure)|i['’]?m not sure|not sure|unknown|unclear|idk|no idea|none|whatever|you choose)[.!? ]*$", re.I)


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _options(items):
    return [{"value": str(key), "label": str(label)} for key, label in items]


def _question(key, prompt, kind, items=(), **extra):
    return {"key": key, "prompt": prompt, "kind": kind, "options": _options(items), **extra}


def _supported():
    return {mid: m for mid, m in catalog.CATALOG["measures"].items() if m.get("certified") and m.get("fact_column")
            and (m["unit"] == m.get("fact_unit") or (m["unit"], m.get("fact_unit")) == ("EUR", "M EUR"))}


def _unavailable_name(mid):
    m = catalog.CATALOG["measures"].get(mid, {})
    name = m.get("name", mid)
    if m.get("fact_column") and m.get("fact_unit") != m.get("unit"):
        return f"{name} (approved unit {m['unit']}, source unit {m['fact_unit']})"
    return name


def _period(value, months):
    if not isinstance(value, dict) or set(value) != {"start", "end"}:
        raise ValueError("Select both the first and last workbook month.")
    start, end = value["start"], value["end"]
    if start not in months or end not in months or start > end:
        raise ValueError(f"Select an ordered period from {months[0]} through {months[-1]}.")
    return {"start": start, "end": end}


def validate_answer(question, value):
    if question["kind"] == "period":
        return _period(value, workbook_months())
    if question["kind"] == "text":
        if (not isinstance(value, str) or not 5 <= len(value.strip()) <= 240 or not re.search(r"[A-Za-z]", value)
                or UNKNOWN_GOAL.fullmatch(value.strip())):
            raise ValueError("Describe the business decision in 5–240 characters.")
        if UNSUPPORTED.search(value):
            raise ValueError("This field records the decision. A different delivery format or grain needs a new request.")
        return value.strip()
    allowed = {v["value"] for v in question["options"]}
    if question["kind"] == "single":
        if not isinstance(value, str) or value not in allowed:
            raise ValueError("Choose one of the offered answers.")
        return value
    if (not isinstance(value, list) or not value or any(not isinstance(v, str) or v not in allowed for v in value)
            or len(set(value)) != len(value) or ("all" in value and len(value) != 1)):
        raise ValueError("Select one or more offered values, or select all by itself.")
    return value


def resolve(intent, verdict, answers, user_text):
    """Return requirements, the next unanswered question, and a blocking reason."""
    C = catalog.CATALOG
    measures = _supported()
    requested = list(dict.fromkeys(intent.get("measures") or []))
    req = {"requested_measures": requested, "measures": list(requested), "omitted_measures": []}
    if verdict not in BUILDABLE:
        return req, None, f"This request has a {verdict.replace('_', ' ')} recommendation. Follow the existing decision before building."
    if intent.get("other_markets") or intent.get("unmatched_terms") or intent.get("migration") or intent.get("grain") not in (None, "month"):
        return req, None, "The saved request contains a scope, source or grain that this monthly workbook cannot fulfill."
    intake = intent.get("dashboard_brief") or {}
    if UNSUPPORTED.search(user_text) or (requires_grain_change(user_text) and not intake.get("monthly_confirmed")):
        return req, None, "The request specifies a format, breakdown or grain this monthly workbook cannot deliver. Revise the request to change it."
    exclusions = re.findall(r"\b(?:except(?: for)?|excluding|exclude|but not|rather than)\s+([^.!?;\n]+)", user_text, re.I)
    if any(match_filters(clause) or match_measures(clause) for clause in exclusions):
        return req, None, "This request excludes part of the saved metric or market scope. Restate the exact values to include."
    if intake.get("monthly_confirmed"):
        req["monthly_confirmed"] = True
    goal = intent.get("decision") or ""
    default_goal = "Monitor " + (", ".join(C["measures"].get(m, {}).get("name", m) for m in requested) or "the requested numbers")
    req["decision_goal"] = answers.get("decision_goal") or intake.get("decision") or (goal if goal != default_goal else "")
    guided = intake.get("guided")
    if guided:  # a guided example: fixed purpose, lead KPI and presentation, all part of the reviewed brief
        req["guided"] = {k: guided[k] for k in ("id", "purpose", "period")}
        req["lead_measure"] = guided["lead_measure"]
        req["presentation"] = guided["presentation"]
    if not req["decision_goal"] or UNKNOWN_GOAL.fullmatch(req["decision_goal"].strip()):
        return req, _question("decision_goal", "What decision will you make using this dashboard?", "text"), None
    if not requested:
        if not answers.get("measures"):
            return req, _question("measures", "Which governed workbook measures should it show?", "multi",
                                  [(k, m["name"]) for k, m in measures.items()]), None
        requested = req["requested_measures"] = answers["measures"]
    req["measures"] = [k for k in requested if k in measures]
    req["omitted_measures"] = [k for k in requested if k not in measures]
    if not req["measures"]:
        unavailable = ", ".join(_unavailable_name(k) for k in req["omitted_measures"])
        return req, None, f"No approved workbook values with matching units are available for {unavailable}."
    approved_metrics = {"keep": req["measures"], "omit": req["omitted_measures"]}
    if req["omitted_measures"] and answers.get("metric_scope") != approved_metrics:
        missing = ", ".join(_unavailable_name(k) for k in req["omitted_measures"])
        kept = ", ".join(measures[k]["name"] for k in req["measures"])
        return req, _question("metric_scope", f"The workbook cannot calculate {missing}. Should this dashboard cover only {kept}?",
                              "single", [("available_only", f"Build with {kept} only")]), None

    filters = intent.get("filters") or {}
    if set(filters) - {"product", "market", "region", "therapeutic_area"}:
        return req, None, "The workbook cannot enforce one of the requested filters."
    for key, axis, tag, column, selector in (("products", "product", "therapeutic_area", "therapeutic_area", "name"),
                                             ("markets", "market", "region", "region", None)):
        choices = C[key]
        names, tags = set(filters.get(axis) or []), set(filters.get(tag) or [])
        known_names = {r[selector] if selector else k for k, r in choices.items()}
        if names - known_names or tags - {r[column] for r in choices.values()}:
            return req, None, f"The workbook does not cover all requested {key}."
        eligible = [k for k, r in choices.items() if (not names or (r[selector] if selector else k) in names)
                    and (not tags or r[column] in tags)]
        if not eligible or (names and len(eligible) != len(names)):
            return req, None, f"The saved {axis} filters conflict. Clarify the original request."
        axis_known = names or tags or intake.get("all_" + key) or (not intake and intent.get("scope_global"))
        selected = answers.get(key)
        if not axis_known and not selected:
            return req, _question(key, f"Which {key} should it cover?", "multi",
                                  [("all", f"All {len(eligible)} workbook {key}"), *[(k, choices[k]["name"]) for k in eligible]]), None
        if names and not selector:  # keep the markets in the order the request named them
            eligible.sort(key=lambda k: list(filters.get(axis) or []).index(k) if k in (filters.get(axis) or []) else len(eligible))
        req[key] = eligible if axis_known or selected == ["all"] else selected
        if set(req[key]) - set(eligible):
            return req, None, f"The saved {axis} selection is no longer available in the workbook."

    dims = list(dict.fromkeys(intent.get("dimensions") or []))
    if set(dims) - DIMENSIONS:
        return req, None, "The workbook does not contain the requested breakdown."
    groups = [d for d in dims if d != "month"]
    selected_group = intake.get("breakdown") or answers.get("breakdown")
    if not dims and not selected_group and (len(req["products"]) > 1 or len(req["markets"]) > 1):
        options = [("month", "One monthly trend"), ("product", "Separate products"), ("market", "Separate markets"),
                   ("product_market", "Separate product and market pairs")]
        return req, _question("breakdown", "Which monthly comparison will support the decision?", "single", options), None
    if not groups and selected_group and selected_group != "month":
        if selected_group not in {"product_market", "product", "market", "region", "therapeutic_area"}:
            return req, None, "The requested grouping is unavailable."
        groups = ["product", "market"] if selected_group == "product_market" else [selected_group]
    req["dimensions"] = ["month", *groups]
    months = workbook_months()
    if not months:
        return req, None, "No monthly source rows are available."
    period = intake.get("period") or answers.get("period")
    if not period:
        return req, _question("period", "Which workbook months should the dashboard cover?", "period",
                              min_period=months[0], max_period=months[-1]), None
    try:
        req["period"] = _period(period, months)
    except ValueError as exc:
        return req, None, str(exc)
    if req.get("lead_measure") and req["lead_measure"] not in req["measures"]:
        return req, None, "The guided example's lead KPI is not part of this brief."
    if any(m not in ADDITIVE for m in req["measures"]):
        combinations = {tuple(_axis(p, m, g) for g in groups) for p in req["products"] for m in req["markets"]}
        if len(combinations) < len(req["products"]) * len(req["markets"]):
            method = answers.get("rates")
            if not method:
                return req, _question("rates", "These rates or coverage measures lack weights across product-market rows. How should they appear?",
                                      "single", [("separate", "Keep each product and market separate"),
                                                 ("mean", "Show the unweighted mean of the selected observations")]), None
            if method == "separate":
                req["dimensions"] = list(dict.fromkeys([*req["dimensions"], "product", "market"]))
            req["rates"] = method
    return req, None, None


def _axis(product, market, dim):
    C = catalog.CATALOG
    if dim in ("product", "therapeutic_area"):
        return C["products"][product]["name" if dim == "product" else "therapeutic_area"]
    return C["markets"][market]["name" if dim == "market" else "region"]


def check_reuse(req):
    C = catalog.CATALOG
    products = [C["products"][k]["name"] for k in req["products"]]
    intent = {"measures": req["measures"], "dimensions": req["dimensions"], "grain": "month",
              "filters": {"product": products, "market": req["markets"]}, "decision": req["decision_goal"],
              "scope_global": len(req["markets"]) == len(C["markets"])}
    native = matching_employee_report(intent)
    if native:
        return f"{native['label']} already covers this KPI and scope. Open the existing employee report.", native["url"]
    ranked = rank_candidates(intent, C)
    result = decide(ranked, data_availability(intent, C), intent, C)
    if result.decision.value in BUILDABLE:
        return None, None
    candidate = result.candidate
    link = f"/briefings?report={candidate.asset_id}" if candidate else None
    return f"The clarified scope leads to {result.decision.value.replace('_', ' ')}. {result.reason}", link


def select_source(req):
    """Resolve the governed bindings and select the approved scope's workbook rows, with every existing check
    (complete contiguous months, valid numbers, unique observations, known record types). One snapshot feeds the
    approval fingerprint and the calculation, so they agree. Raises ValueError when the evidence cannot be used."""
    start, end = req["period"]["start"], req["period"]["end"]
    months = [m for m in workbook_months() if start <= m <= end]
    if len(months) != (int(end[:4]) - int(start[:4])) * 12 + int(end[5:]) - int(start[5:]) + 1:
        raise ValueError("A month in the requested period is missing from the workbook.")
    products, markets = set(req["products"]), set(req["markets"])
    columns = []
    for key in req["measures"]:
        meta = _supported()[key]
        method = ("Sum of workbook rows" if key in ADDITIVE else
                  "Unweighted mean of workbook rows" if req.get("rates") == "mean" else "Single product-market observation")
        columns.append({"id": key, "name": meta["name"], "unit": meta["fact_unit"] or meta["unit"], "field": meta["fact_column"],
                        "kpi_id": meta["kpi_id"], "aggregation": method, "lower_is_better": meta["lower_is_better"]})
    fields = {col["field"] for col in columns}
    records, seen = [], set()
    for i, row in enumerate(catalog.SHEETS[SOURCE.lower()], 2):
        p, m, period = row["product_id"], row["market_id"], row["month"][:7]
        if p not in products or m not in markets or period not in months:
            continue
        if (p, m, period) in seen:
            raise ValueError(f"Duplicate source observations for {p}, {m}, {period}.")
        seen.add((p, m, period))
        if any(type(row.get(f)) not in (float, int) or not math.isfinite(row[f]) for f in fields):
            raise ValueError(f"Missing or invalid numeric evidence in {SOURCE} row {i}.")
        if row.get("value_type") not in ("actual_like_synthetic", "forecast_like_synthetic"):
            raise ValueError(f"The record type in {SOURCE} row {i} cannot be verified.")
        records.append({"row": i, "product_id": p, "market_id": m, "month": row["month"], "value_type": row["value_type"],
                        **{field: row[field] for field in sorted(fields)}})
    if len(seen) != len(products) * len(markets) * len(months):
        raise ValueError("A requested product, market or month is missing source observations. Narrow or revise the brief.")
    return {"columns": columns, "records": records, "months": months}


def calculate(req, source, dashboard_id, conversation_id, run_id, request):
    """Aggregate a verified source snapshot into the approved monthly series and groups. Reads no workbook rows."""
    C = catalog.CATALOG
    columns, records = source["columns"], source["records"]
    products, markets = set(req["products"]), set(req["markets"])
    groups = defaultdict(lambda: defaultdict(list))
    axes = [d for d in req["dimensions"] if d != "month"]
    for record in records:
        groups[tuple(_axis(record["product_id"], record["market_id"], d) for d in axes)][record["month"][:7]].append(record)
    result = []
    for group, monthly in sorted(groups.items()):
        points = []
        for period, rows in sorted(monthly.items()):
            values = {}
            for col in columns:
                key = col["id"]
                total = sum(r[col["field"]] for r in rows)
                if len(rows) == 1 or key in ADDITIVE:
                    value = total
                else:
                    value = total / len(rows)
                values[key] = round(value, 4)
            points.append({"period": period, "values": values, "source_rows": [r["row"] for r in rows],
                           "value_types": sorted({r["value_type"] for r in rows})})
        result.append({"label": " · ".join(group) if group else "Selected scope", "points": points})
    scope = {"products": [C["products"][k]["name"] for k in req["products"]], "markets": [C["markets"][k]["name"] for k in req["markets"]]}
    subject = " · ".join([scope["products"][0] if len(products) == 1 else f"{len(products)} products",
                          scope["markets"][0] if len(markets) == 1 else f"{len(markets)} markets"])
    if req.get("presentation"):  # guided: name the two countries, lead KPI first
        lead_first = sorted(columns, key=lambda c: c["id"] != req.get("lead_measure"))
        title = f"{scope['products'][0]} in {' and '.join(C['markets'][m]['name'] for m in req['markets'])}: " + \
                " and ".join(c["name"] for c in lead_first)
    else:
        title = f"{subject}: " + _join([c["name"] for c in columns])
    return {"id": dashboard_id, "title": title,
            "conversation_id": conversation_id, "run_id": run_id, "request": request, "decision_goal": req["decision_goal"],
            "period": req["period"], "scope": scope, "dimensions": req["dimensions"], "columns": columns, "groups": result,
            "requested_measures": req["requested_measures"], "omitted_measures": req["omitted_measures"],
            "source": SOURCE, "source_records": records, "synthetic": True,
            **({"presentation": req["presentation"], "lead_measure": req["lead_measure"], "guided": req["guided"],
                "market_order": [C["markets"][m]["name"] for m in req["markets"]]} if req.get("presentation") else {})}




def assemble(req, dashboard_id, conversation_id, run_id, request):
    """Select and validate the source rows, then calculate the view: the review preview and older callers."""
    return calculate(req, select_source(req), dashboard_id, conversation_id, run_id, request)


def _join(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _month_label(period: str) -> str:
    return datetime.strptime(period[:7], "%Y-%m").strftime("%B %Y")


def charted_columns(artifact: dict) -> list[dict]:
    """The measures a chart draws: every column except a sales forecast shown beside net sales (drawn as its comparison line)."""
    columns = artifact.get("columns") or []
    ids = {c["id"] for c in columns}
    return [c for c in columns if not (c["id"] == "sales_forecast" and "net_sales" in ids)]


def _finite(v) -> bool:
    return type(v) in (int, float) and math.isfinite(v)


def choose_layout(artifact: dict) -> str:
    """The dashboard layout, from the data's shape alone (the frontend mirrors this in lib/dashboardLayout.ts):
    table (approved table-only), empty (nothing chartable), comparison (exactly two peers over the same months),
    pulse (one scope with two or more months), summary (one scope, one month) or overview (3+ peers or uneven coverage)."""
    if artifact.get("display_mode") == "table":
        return "table"
    charted = [c["id"] for c in charted_columns(artifact)]
    groups = [g for g in artifact.get("groups") or []
              if any(_finite(p["values"].get(k)) for p in g["points"] for k in charted)]
    if not groups:
        return "empty"
    months = [{p["period"] for p in g["points"] if any(_finite(p["values"].get(k)) for k in charted)} for g in groups]
    if len(groups) == 2 and months[0] == months[1]:
        return "comparison"
    if len(groups) == 1:
        return "pulse" if len(months[0]) >= 2 else "summary"
    return "overview"


def build_receipt(artifact: dict) -> dict:
    """What a dashboard holds and how it opens, computed from the assembled or saved artifact. No model, no extra reads.

    Shown during the hand-off from the reviewed brief to the saved dashboard, and again on the dashboard itself."""
    columns = artifact.get("columns") or []
    charted = charted_columns(artifact)
    groups = artifact.get("groups") or []
    periods = sorted({p["period"] for g in groups for p in g["points"]})
    records = artifact.get("source_records") or []
    rows = sorted(r["row"] for r in records)
    actual = sum(r.get("value_type") == "actual_like_synthetic" for r in records)
    unit = lambda u: "€m" if u in ("M EUR", "EUR M") else u
    label = lambda c: f"{c['name']} ({unit(c['unit'])})" if c.get("unit") else c["name"]
    names = [label(c) for c in charted]
    view = choose_layout(artifact)
    lead = next((c for c in charted if c["id"] == artifact.get("lead_measure")), None)
    if view == "comparison":
        places = _join(artifact.get("market_order") or [g["label"] for g in groups])
        ordered = ([lead] + [c for c in charted if c is not lead]) if lead else charted
        if len(periods) == 1:
            layout = f"Summary cards for {places} in {_month_label(periods[0])}: {_join([label(c) for c in ordered])}."
        else:
            shown = "two at a time, with a KPI selector" if len(ordered) > 2 else "one panel per KPI"
            layout = f"Monthly trend panels ({shown}: {_join([label(c) for c in ordered])}), each comparing {places}."
        if lead:
            layout += f" {lead['name']} leads, with a latest-month comparison of both."
        layout += " Select a month to see both values and their workbook rows; every value is also listed under All values and workbook rows."
    elif view == "table":
        layout = "A table of the approved monthly values with their workbook rows."
    elif view == "empty":
        layout = "No chartable values were saved for this scope; the table shows what was."
    elif view == "summary":
        layout = ("Switch between " if len(names) > 1 else "") + f"{_join(names)} for {_month_label(periods[0])}. The table below lists the figures and their workbook rows."
    else:
        trend = f"Switch between {_join(names)} in a monthly trend" if len(names) > 1 else f"A monthly trend of {names[0]}"
        layout = trend + " in the Monthly Pulse panel."
        if view == "overview":
            layout += f" Choose one of {len(groups)} groups ({_join([g['label'] for g in groups][:4])}{', …' if len(groups) > 4 else ''}) to see its figures."
        layout += " The figures and their workbook rows are listed under the chart."
    scope = artifact.get("scope") or {}
    return {
        "products": scope.get("products", []), "markets": scope.get("markets", []), "period": artifact.get("period"),
        "measures": [{"id": c["id"], "kpi_id": c.get("kpi_id"), "name": c["name"], "unit": c.get("unit", "")} for c in columns],
        "charted_measures": len(charted), "groups": len(groups), "group_labels": [g["label"] for g in groups],
        "months": len(periods), "first_month": periods[0] if periods else None, "last_month": periods[-1] if periods else None,
        "observations": len(records), "rows": {"first": rows[0], "last": rows[-1]} if rows else None,
        "actual_like": actual, "forecast_like": len(records) - actual, "source": artifact.get("source"),
        "omitted_measures": artifact.get("omitted_measures") or [], "arrangement": layout,
        "lead_measure": artifact.get("lead_measure"), "presentation": artifact.get("presentation"), "layout": view,
        "decision_goal": artifact.get("decision_goal"),
    }
