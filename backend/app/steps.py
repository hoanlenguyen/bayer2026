"""The six analysis steps from SinceAI's data pack, each answered from its own sheets.

  1 Business_Requests                Parse business question   structured intent
  2 KPI_Catalog                      Resolve metric definitions governed metric set
  3 Analytics_Assets + Asset_Usage   Find existing analytics   reuse / consolidate candidates
  4 Semantic_Models + Lineage_Edges  Trace data dependencies   impact & lineage explanation
  5 Governance_Signals + Data_Quality Check trust and ownership risk / repair actions
  6 Migration_Backlog                Handle Tableau → Power BI migrate / retire / consolidate recommendation

Plain Python over catalog facts: no model runs here, so the same request always gives the same steps.
"""
from __future__ import annotations

from typing import Any

from . import catalog as cat
from .decision import THRESHOLDS, AssetScore, DecisionResult, intent_products

MAX_LISTED = 5
OK_REFRESH = "healthy"
CONSOLIDATE_PATHS = {"CONSOLIDATE_BEFORE_MIGRATION"}


def _step(number: int, sheets: list[str], task: str, looked_at: list[str], output: str, summary: str,
          findings: list[str], data: dict[str, Any]) -> dict[str, Any]:
    return {"step": number, "sheets": sheets, "task": task, "looked_at": looked_at, "output": output,
            "summary": summary, "findings": findings, "data": data}


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


# ---------------------------------------------------------------- 1
def parse_request(intent: dict[str, Any], tags: dict[str, Any]) -> dict[str, Any]:
    market = ", ".join(tags["market"]) or "no market named"
    product = ", ".join(tags["product"]) or "no product named"
    domain = tags["domain"] or "no domain found"
    findings = [f"Domain: {domain}", f"Market: {market}", f"Product: {product}"]
    if tags["breakdown"]:
        findings.append("Broken down by: " + ", ".join(tags["breakdown"]))
    if intent.get("migration"):
        findings.append("Asks to move a Tableau report to Power BI")
    if tags["not_available"]:
        findings.append("Not available in this data: " + ", ".join(tags["not_available"]))
    return _step(1, ["Business_Requests"], "Parse business question", ["request text", "domain", "market", "product"],
                 "structured intent", f"{domain}, {market}, {product}", findings,
                 {"question": intent.get("question"), "domain": tags["domain"], "market": tags["market"], "product": tags["product"],
                  "breakdown": tags["breakdown"], "measures": intent.get("measures") or [], "migration": bool(intent.get("migration")),
                  "not_available": tags["not_available"]})


# ---------------------------------------------------------------- 2
def resolve_kpis(governed: list[str]) -> dict[str, Any]:
    C, rows, findings = cat.CATALOG, [], []
    for mid in governed:
        m = C["measures"][mid]
        variants = m.get("variants") or []
        conflicts = [v["name"] for v in variants if v.get("status") == "definition_conflict"]
        others = [v["name"] for v in variants if v.get("status") != "definition_conflict"]
        rows.append({"id": mid, "kpi_id": m.get("kpi_id"), "canonical": m["name"], "aliases": list(m.get("keywords") or []),
                     "conflicts": conflicts, "other_variants": others})
        note = f"{m['name']} ({m.get('kpi_id')}) is the approved definition"
        if conflicts:
            note += f"; do not use {', '.join(conflicts)} (conflicting)"
        findings.append(note)
    total = sum(len(r["conflicts"]) for r in rows)
    summary = (f"{_plural(len(rows), 'approved KPI')}, {_plural(total, 'conflicting definition')} to avoid" if rows
               else "No approved KPI matches this request")
    return _step(2, ["KPI_Catalog"], "Resolve metric definitions", ["canonical KPI", "aliases", "conflicts"],
                 "governed metric set", summary, findings, {"kpis": rows})


# ---------------------------------------------------------------- 3
def find_analytics(candidates: list[AssetScore]) -> dict[str, Any]:
    t = THRESHOLDS
    in_scope = [c for c in candidates if c.scope_score >= t["min_scope"]]

    def row(c: AssetScore, role: str) -> dict[str, Any]:
        asset = cat.asset_by_id(c.asset_id) or {}
        return {"id": c.asset_id, "name": c.name, "role": role, "platform": c.platform, "similarity": c.coverage,
                "views_90d": c.views_90d, "users_90d": asset.get("users_90d", 0), "freshness": c.freshness, "governance": c.governance}

    reuse = [c for c in in_scope if c.reusable]
    review = [c for c in in_scope if c.scope_evidence.get("conflict") and not c.measures_missing
              and c.coverage >= t["reuse_coverage"]]
    taken = {c.asset_id for c in reuse}
    consolidate = [c for c in in_scope if c.asset_id not in taken and not c.scope_evidence.get("conflict")
                   and c.coverage >= t["consolidate_min_coverage"]]
    rows = ([row(c, "reuse") for c in reuse[:MAX_LISTED]] + [row(c, "scope review") for c in review[:MAX_LISTED]]
            + [row(c, "consolidate") for c in consolidate[:MAX_LISTED]])
    findings = [f"{r['role'].capitalize()}: {r['name']} ({round(r['similarity'] * 100)}% match, {r['views_90d']:,} views, "
                f"{r['users_90d']:,} users in 90 days)" for r in rows]
    summary = (f"{_plural(len(reuse), 'reuse candidate')}, {_plural(len(review), 'scope review')}, {_plural(len(consolidate), 'consolidate candidate')} "
               f"out of {_plural(len(candidates), 'report')} using these KPIs")
    return _step(3, ["Analytics_Assets", "Asset_Usage"], "Find existing analytics", ["similarity", "adoption", "freshness"],
                 "reuse / consolidate candidates", summary, findings,
                 {"reports_using_kpis": len(candidates), "in_scope": len(in_scope), "reuse_count": len(reuse), "scope_review_count": len(review),
                  "consolidate_count": len(consolidate), "candidates": rows})


# ---------------------------------------------------------------- 4
def trace_lineage(model_id: str | None) -> dict[str, Any]:
    C = cat.CATALOG
    model = cat.model_by_id(model_id) if model_id else None
    sheets = ["Semantic_Models", "Lineage_Edges"]
    looked_at = ["model", "source", "downstream reports"]
    if not model:
        return _step(4, sheets, "Trace data dependencies", looked_at, "impact & lineage explanation",
                     "No semantic model serves this request", [], {"model": None, "sources": [], "downstream": []})

    sources = sorted({e["source"] for e in C["lineage"] if e["target"] == model["id"]})
    report_ids = {e["target"] for e in C["lineage"] if e["source"] == model["id"] and e["type"] == "MODEL_TO_ASSET"}
    reports = sorted((a for a in C["assets"] if a["id"] in report_ids), key=lambda a: a.get("views_90d", 0), reverse=True)
    views = sum(a.get("views_90d", 0) for a in reports)
    impact = f"Changing {model['name']} ({model['id']}) affects {_plural(len(reports), 'report')} with {views:,} views in 90 days."
    findings = [impact, "Sources: " + (", ".join(sources) if sources else "none recorded")]
    findings += [f"Downstream: {a['name']} ({a.get('views_90d', 0):,} views)" for a in reports[:MAX_LISTED]]
    return _step(4, sheets, "Trace data dependencies", looked_at, "impact & lineage explanation", impact, findings,
                 {"model": {"id": model["id"], "name": model["name"], "workspace": model["workspace"], "platform": model["platform"]},
                  "sources": sources, "downstream_count": len(reports), "downstream_views_90d": views,
                  "downstream": [{"id": a["id"], "name": a["name"], "views_90d": a.get("views_90d", 0)} for a in reports[:MAX_LISTED]]})


# ---------------------------------------------------------------- 5
def check_trust(report: dict[str, Any] | None, model_id: str | None, candidate: AssetScore | None = None) -> dict[str, Any]:
    model = cat.model_by_id(model_id) if model_id else None
    sheets = ["Governance_Signals", "Data_Quality"]
    looked_at = ["owner", "certification", "sensitivity", "refresh", "quality"]
    subject = report or model
    if not subject:
        return _step(5, sheets, "Check trust and ownership", looked_at, "risk / repair actions",
                     "Nothing to check: no report or model was found", [], {"subject": None, "risks": [], "repair_actions": []})

    is_report = subject is report
    owner_ok = subject.get("owner_status") == "active"
    certified = bool(subject.get("certified")) if is_report else subject.get("endorsement") == "certified"
    refresh = subject.get("refresh_status") or (model or {}).get("refresh_status")
    signals = [s for s in subject.get("signals", []) if s.get("status") == "open"]
    issues = subject.get("dq_issues", [])
    risks, actions = [], []
    sources = []
    if candidate:
        # Cite workbook row positions by stable IDs, including when reports have similar titles.
        ev = candidate.scope_evidence
        for sheet, key, record_id, fields in (
            ("Analytics_Assets", "asset_id", candidate.asset_id, ("model_id", "product_scope", "market_scope")),
            ("Semantic_Models", "model_id", ev.get("model_id"), ("product_scope", "region_scope")),
        ):
            for n, row in enumerate(cat.SHEETS[sheet.lower()], start=2):
                if row[key] == record_id:
                    sources.append({"sheet": sheet, "row": n, "record_id": record_id,
                                    "fields": {f: row[f] for f in fields}})
                    break
        if ev.get("conflict"):
            risks.append(ev["reason"])
            actions.append("Verify the report's model binding and the data coverage for the requested scope")
        sheets += [s["sheet"] for s in sources]
    if not owner_ok:
        risks.append(f"Owner is {subject.get('owner') or 'missing'} ({subject.get('owner_status')})")
        actions.append("Assign an active owner")
    if not certified and subject.get("endorsement") != "promoted":
        risks.append("Not certified or promoted")
        actions.append("Review and endorse it")
    if refresh != OK_REFRESH:
        risks.append(f"Refresh is {refresh or 'not recorded'}")
        actions.append("Fix the refresh")
    for s in signals:
        if s.get("severity") == "high":
            risks.append(f"Open high-severity signal: {s.get('code')}")
    if any(s.get("severity") == "high" for s in signals):
        actions.append("Resolve the open high-severity signals")
    high_issues = [i for i in issues if i.get("severity") == "high"]
    if high_issues:
        risks.append(_plural(len(high_issues), "high-severity data quality issue"))
        actions.append("Fix the data quality issues")
    if is_report and subject.get("lifecycle") == "candidate_retire":
        risks.append("Marked as a candidate for retirement")

    sensitivity = subject.get("classification", "not recorded")
    name = subject["name"]
    findings = [f"Checked: {name}", f"Owner: {subject.get('owner') or 'none'} ({subject.get('owner_status')})",
                f"Certification: {subject.get('endorsement') or 'none'}", f"Sensitivity: {sensitivity}",
                f"Refresh: {refresh or 'not recorded'}", f"Quality: {_plural(len(issues), 'issue')}, {_plural(len(signals), 'open signal')}"]
    findings += [f"{s['sheet']} row {s['row']} ({s['record_id']}) · " +
                 ", ".join(f"{k}={v}" for k, v in s["fields"].items()) for s in sources]
    findings += [f"Risk: {r}" for r in risks] + [f"Action: {a}" for a in actions]
    return _step(5, sheets, "Check trust and ownership", looked_at, "risk / repair actions",
                 f"{name}: {_plural(len(risks), 'risk')}, {_plural(len(actions), 'repair action')}", findings,
                 {"subject": {"id": subject["id"], "name": name, "kind": "report" if is_report else "semantic model"},
                  "owner": subject.get("owner"), "owner_status": subject.get("owner_status"), "certification": subject.get("endorsement"),
                  "sensitivity": sensitivity, "refresh": refresh, "open_signals": len(signals), "quality_issues": len(issues),
                  "risks": risks, "repair_actions": actions, "scope_sources": sources})


# ---------------------------------------------------------------- 6
def _recommend(asset: dict[str, Any]) -> tuple[str, str]:
    """Migrate, retire, consolidate or review, with the reason. Unused and retiring reports are never moved 1:1 (RULE-006)."""
    path = (asset.get("migration") or {}).get("recommended_path_candidate") or "not in backlog"
    views = asset.get("views_90d", 0)
    if path == "RETIRE":
        return "retire", "the backlog recommends it"
    if asset.get("lifecycle") == "candidate_retire":
        return "retire", "already marked for retirement"
    if views < THRESHOLDS["low_usage_views_90d"]:
        return "retire", f"low usage ({views:,} views in 90 days)"
    if path in CONSOLIDATE_PATHS:
        return "consolidate", "the backlog recommends it"
    if path == "HUMAN_REVIEW":
        return "review", "the backlog asks for a human decision"
    return "migrate", f"in use ({views:,} views in 90 days)"


def handle_migration(intent: dict[str, Any], report: dict[str, Any] | None) -> dict[str, Any]:
    C = cat.CATALOG
    sheets, looked_at = ["Migration_Backlog"], ["legacy status", "duplicate destination", "complexity"]
    output = "migrate / retire / consolidate recommendation"
    products = set(intent_products(intent, C))
    legacy = [a for a in C["assets"] if a["platform"] == "Tableau" and a["product_scope"] in products] if intent.get("migration") else []
    if report and report.get("platform") == "Tableau" and report["id"] not in {a["id"] for a in legacy}:
        legacy.append(report)
    if not legacy:
        return _step(6, sheets, "Handle Tableau → Power BI", looked_at, output, "Not needed: no Tableau report is involved", [],
                     {"applies": False, "assets": [], "counts": {}})

    rows = []
    for a in sorted(legacy, key=lambda x: x.get("views_90d", 0), reverse=True):
        action, why = _recommend(a)
        m = a.get("migration") or {}
        rows.append({"id": a["id"], "name": a["name"], "recommendation": action, "reason": why, "legacy_status": a.get("lifecycle"),
                     "in_backlog": bool(m), "backlog_path": m.get("recommended_path_candidate"), "backlog_status": m.get("status"),
                     "destination_model": m.get("candidate_target_model_id"), "complexity": m.get("complexity"), "views_90d": a.get("views_90d", 0)})
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["recommendation"]] = counts.get(r["recommendation"], 0) + 1
    findings = [f"{r['recommendation'].capitalize()}: {r['name']}, {r['reason']}"
                + (f"; destination {r['destination_model']}, {r['complexity']} complexity" if r["destination_model"] else "; not in the backlog")
                for r in rows[:MAX_LISTED]]
    summary = f"{_plural(len(rows), 'Tableau report')}: " + ", ".join(f"{n} {k}" for k, n in counts.items())
    return _step(6, sheets, "Handle Tableau → Power BI", looked_at, output, summary, findings,
                 {"applies": True, "counts": counts, "assets": rows})


# ---------------------------------------------------------------- recommendation
RECOMMENDATIONS = {
    "reuse": ("reuse", "Reuse"), "repair": ("reuse", "Reuse after repair"), "consolidate": ("consolidation", "Consolidation"),
    "migrate": ("migration", "Migration"), "retire": ("retirement", "Retirement"), "review": ("review", "Human review"), "new_build": ("new_build", "New build"),
    "not_feasible": ("not_feasible", "Not feasible"),
}


def recommendation(result: DecisionResult, steps: list[dict[str, Any]]) -> dict[str, Any]:
    """What the system recommends and why. It builds and changes nothing: people act on this."""
    data = result.to_dict()
    value, label = RECOMMENDATIONS[result.decision.value]
    return {"value": value, "label": label, "reason": result.reason, "rule": result.rule, "rules_applied": data["rules_applied"],
            "evidence": [{"step": s["step"], "sheets": s["sheets"], "task": s["task"], "output": s["output"],
                          "summary": s["summary"], "findings": s["findings"]} for s in steps]}


# ---------------------------------------------------------------- all
def analysis_steps(intent: dict[str, Any], tags: dict[str, Any], candidates: list[AssetScore], result: DecisionResult) -> list[dict[str, Any]]:
    report = cat.asset_by_id(result.candidate.asset_id) if result.candidate else None
    model_id = (tags.get("semantic_model") or {}).get("id")
    governed = [k["id"] for k in tags["governed_kpis"]]
    return [parse_request(intent, tags), resolve_kpis(governed), find_analytics(candidates), trace_lineage(model_id),
            check_trust(report, model_id, result.candidate), handle_migration(intent, report)]
