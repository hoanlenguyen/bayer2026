"""Clarify an employee's dashboard brief before the catalogue decision."""
import calendar
import re

from . import catalog


_AUTHOR = re.compile(r"\bdashboards?\b|\b(?:build|create|design|make|need|want)\b.{0,30}\b(?:reports?|scorecards?)\b", re.I)
_LIFECYCLE = re.compile(r"\b(?:migrat\w*|retir\w*|consolidat\w*|replace\w*)\b", re.I)
_PURPOSE = re.compile(r"\b(?:so (?:that )?(?:we|I|my team) can\s+|in order to\s+|(?:to help (?:us|me)|help (?:us|me)|to)\s+(?=decide|identify|allocate|prioriti[sz]e|monitor|compare|plan|track|review|spot|rebalance))(.+)", re.I)
_ALL_PRODUCTS = re.compile(r"\b(?:all|every|across the) (?:products?|brands?|medicines?|portfolio)\b", re.I)
_ALL_MARKETS = re.compile(r"\b(?:(?:all|every) (?:markets?|countries|country)|worldwide|globally|global)\b", re.I)
_OTHER_GRAIN = re.compile(r"\b(?:hourly|daily|weekly|quarterly|annual(?:ly)?|yearly|real[- ]time|last (?:7|seven) days|(?:per|by) (?:hour|day|week|quarter|year))\b", re.I)
_MEETING = re.compile(r"\b(?:weekly|daily|quarterly|annual)\s+(?:(?:sales|supply|team|business|leadership|management)\s+)?(?:meetings?|briefings?|reviews?|huddles?)\b", re.I)
_ACTION = re.compile(r"^(?:to )?(?:decide|identify|allocate|prioriti[sz]e|monitor|compare|plan|track|review|spot|rebalance|choose|assess)\s+\S+", re.I)
_UNKNOWN_GOAL = re.compile(r"\b(?:not sure|don['’]?t know|no idea|maybe|no fixed deadline)\b", re.I)
_MONTHS = {label.lower(): i for i in range(1, 13) for label in (calendar.month_name[i], calendar.month_abbr[i])}
_MONTHS["sept"] = 9
_MONTH = r"\b(" + "|".join(_MONTHS) + r")(?:\s+(20\d{2}))?\b"
PERIOD_CHOICES = ["All available workbook months", "Last 3 workbook months", "Latest workbook month"]


def is_dashboard_request(text: str) -> bool:
    return bool(_AUTHOR.search(text) and not _LIFECYCLE.search(text))


def requires_grain_change(text: str) -> bool:
    return bool(_OTHER_GRAIN.search(_MEETING.sub("", text)))


def workbook_months() -> list[str]:
    return sorted({r["month"][:7] for r in catalog.SHEETS["product_market_monthly"] if r.get("month")})


def requested_period(text: str, months: list[str]) -> dict | None:
    """Resolve a continuous range only when it exists in the workbook."""
    if not months:
        return None
    low = text.lower().strip().replace("–", "-").replace("—", "-")
    low = re.sub(r"\bmay\s+(?:i|we|be|need|want)\b", "", low)
    if re.search(r"\b(?:all (?:available |workbook |available workbook )?(?:months|history)|full (?:workbook )?history)\b", low):
        return {"start": months[0], "end": months[-1]}
    if re.search(r"\b(?:latest|most recent) (?:available |workbook )?month\b", low):
        return {"start": months[-1], "end": months[-1]}
    last = re.search(r"\b(?:last|latest|most recent) (\d+) (?:workbook |available )?months\b", low)
    if last:
        n = int(last[1])
        return {"start": months[-n], "end": months[-1]} if 0 < n <= len(months) else None
    # A due date does not specify the reporting period.
    low = re.sub(r"\b(?:needed|due|required|deliver(?:ed)?|ready)\s+(?:by|before|on|in)\s+[^.,;]+", "", low)
    iso = list(re.finditer(r"\b(20\d{2}-(?:0[1-9]|1[0-2]))\b(?!-\d)", low))
    named = list(re.finditer(_MONTH, low))
    if iso and named:
        return None
    quarters = list(re.finditer(r"\bq([1-4])(?:\s+(20\d{2}))?\b", low))
    if len(quarters) > 2 or (quarters and (iso or named)):
        return None
    if quarters:
        first, last_quarter = quarters[0], quarters[-1]
        if len(quarters) == 2 and low[first.end():last_quarter.start()].strip() not in {"-", "to", "through", "until"}:
            return None
        years = {q[2] for q in quarters if q[2]} or {m[:4] for m in months}
        if len(years) != 1 and any(not q[2] for q in quarters):
            return None
        periods = [f"{first[2] or next(iter(years))}-{int(first[1])*3-2:02}",
                   f"{last_quarter[2] or next(iter(years))}-{int(last_quarter[1])*3:02}"]
    else:
        matches = iso or named
        if not matches or len(matches) > 2:
            return None
        if len(matches) == 2:
            between = low[matches[0].end():matches[1].start()].strip()
            if between not in {"-", "to", "through", "until"} and not (between == "and" and "between" in low):
                return None
        if iso:
            periods = [m[1] for m in iso]
        else:
            years = {m[2] for m in named if m[2]} or {m[:4] for m in months}
            if len(years) != 1 and any(not m[2] for m in named):
                return None
            periods = [f"{m[2] or next(iter(years))}-{_MONTHS[m[1]]:02}" for m in named]
    start, end = periods[0], periods[-1]
    return {"start": start, "end": end} if start in months and end in months and start <= end else None


def clarify(ctx: dict, intent: dict, previous: dict, pending: str | None) -> dict:
    turns = [m["content"] for m in ctx["transcript"] if m["role"] == "user"]
    last = turns[-1]
    brief = dict(previous)
    intent["dashboard_brief"] = brief
    intent.pop("_pending", None)
    def ask(field, question, choices):
        intent["_pending"] = "dashboard_" + field
        return {"status": "ask", "intent": intent, "question": question, "suggestions": choices}
    clear = {"status": "clear", "intent": intent, "question": None, "suggestions": []}
    if intent.get("unmatched_terms") or intent.get("other_markets") or intent.get("migration"):
        return clear
    if pending == "dashboard_grain" and re.search(r"\b(?:monthly|by month)\b", last, re.I) and not re.search(r"\b(?:not|no|without)\b", last, re.I):
        brief["monthly_confirmed"] = True
    if pending == "dashboard_grain" and re.search(r"\b(?:keep|need|require)\b", last, re.I) and not brief.get("monthly_confirmed"):
        intent["unmatched_terms"] = ["requested reporting frequency is finer than the monthly workbook"]
        return clear
    if _ALL_PRODUCTS.search(last):
        brief["all_products"] = True
    if _ALL_MARKETS.search(last):
        brief["all_markets"] = True
    intent["scope_global"] = bool(brief.get("all_products") and brief.get("all_markets"))
    # Prior answers remain distinct from subsequent replies to a different question.
    goal = _PURPOSE.search(last)
    if (pending == "dashboard_decision" or _ACTION.search(last)) and len(last.split()) > 1 and not _UNKNOWN_GOAL.search(last):
        brief["decision"] = last.strip()
    elif goal:
        brief["decision"] = goal[1].strip().rstrip(".")
    intent["decision"] = brief.get("decision")
    months = workbook_months()
    period_text = last[:goal.start()] if goal else last
    period = requested_period(period_text, months) if pending != "dashboard_decision" else None
    if period:
        brief["period"] = period
    filters = intent.get("filters") or {}
    product_known = filters.get("product") or filters.get("therapeutic_area") or brief.get("all_products")
    market_known = filters.get("market") or filters.get("region") or brief.get("all_markets")
    if not intent["measures"]:
        if pending == "dashboard_measures" and not _UNKNOWN_GOAL.search(last):
            intent["unmatched_terms"] = [last.strip()]
            return clear
        return ask("measures", "Which numbers should this dashboard show?",
                   ["Net sales and units shipped", "Inventory coverage and OTIF", "Market access coverage"])
    if not product_known and not market_known:
        return ask("scope", "Which products and markets should it cover?",
                   ["Nubeqa in France", "Lynkuet in Spain", "All products, all markets"])
    if not product_known:
        return ask("scope", "Which products should it cover?", ["All products", "Nubeqa", "Lynkuet"])
    if not market_known:
        return ask("scope", "Which markets should it cover?", ["All markets", "France", "Germany"])
    if not intent.get("decision"):
        return ask("decision", "What decision will someone make using this dashboard?",
                   ["Decide where to allocate stock", "Choose markets for a sales review", "Assess delivery performance"])
    if not brief.get("period") and months:
        return ask("period", f"Which reporting period should the charts cover? Monthly data is available from {months[0]} through {months[-1]}.", PERIOD_CHOICES)
    if not brief.get("monthly_confirmed") and any(requires_grain_change(text) for text in turns):
        return ask("grain", "The workbook has one observation per month. Can monthly figures support this decision?",
                   ["Use monthly data", "Keep the requested frequency"])
    if len(filters.get("product", [])) == 1 and len(filters.get("market", [])) == 1:
        brief["breakdown"] = "month"
    else:
        groups = [d for d in intent.get("dimensions", []) if d != "month"]
        if len(groups) == 1:
            brief["breakdown"] = groups[0]
    return clear
