"""Deterministic scoring and the lifecycle decision.

The AI extracts the intent; this module decides. Same inputs always give the
same decision, and every score, check and rule is shown to the user
(SinceAI RULE-008: explain every lifecycle action).

Outcomes (from the data pack): reuse, repair, consolidate, migrate, new build,
not feasible. Retirement appears as flags on overlapping assets and becomes a
maintenance action. Thresholds and weights live here only.
"""
from __future__ import annotations

import re

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

THRESHOLDS = {
    "reuse_coverage": 0.90,
    "reuse_freshness": 0.90,
    "reuse_governance": 0.80,
    "repair_min_governance": 0.30,
    "repair_min_views_90d": 300,  # repair reports people use, or well-governed ones (never rebuild a governed report)
    "consolidate_min_coverage": 0.60,
    "consolidate_governance": 0.60,
    "min_scope": 0.75,            # product and market scope must fit for reuse, repair or consolidate
    "consolidate_min_measures": 0.5,
    "migration_min_scope": 0.5,
    "flag_overlap_coverage": 0.60,
    "flag_governance_below": 0.50,
    "low_usage_views_90d": 150,
    "max_candidates_shown": 8,
    "max_flags": 5,
}

COVERAGE_WEIGHTS = {"measures": 0.6, "scope": 0.4}
FRESHNESS_BY_REFRESH = {"healthy": 1.0, "warning": 0.7, "failed": 0.3, None: 0.5}

GOVERNANCE_WEIGHTS = {
    "definitions_match": 0.30,
    "endorsed": 0.20,
    "owner_active": 0.20,
    "no_open_high_signals": 0.15,
    "lifecycle_active": 0.10,
    "ai_ready_model": 0.05,
}
GOVERNANCE_LABELS = {
    "definitions_match": "Requested KPIs use approved definitions (RULE-002)",
    "endorsed": "Certified or promoted (RULE-005)",
    "owner_active": "Has an active owner (RULE-003)",
    "no_open_high_signals": "No open high-severity governance signals",
    "lifecycle_active": "Lifecycle status is active",
    "ai_ready_model": "Semantic model is AI-ready (RULE-007)",
}

# Which rules each outcome applies. Shown next to the decision.
RULES_BY_DECISION = {
    "reuse": ["RULE-001", "RULE-002", "RULE-005"],
    "repair": ["RULE-001", "RULE-003", "RULE-008"],
    "consolidate": ["RULE-001", "RULE-002", "RULE-004"],
    "migrate": ["RULE-006", "RULE-001", "RULE-004"],
    "new_build": ["RULE-001", "RULE-002", "RULE-007"],
    "retire": ["RULE-006", "RULE-004", "RULE-008"],
    "review": ["RULE-006", "RULE-008"],
    "not_feasible": ["RULE-008"],
}


RETIRE_WORDS = re.compile(r"\b(retire|retiring|decommission\w*|sunset\w*|switch(ing)? off|shut(ting)? down)\b", re.I)


class Decision(str, Enum):
    REUSE = "reuse"
    REPAIR = "repair"
    CONSOLIDATE = "consolidate"
    MIGRATE = "migrate"
    NEW_BUILD = "new_build"
    RETIRE = "retire"
    REVIEW = "review"
    NOT_FEASIBLE = "not_feasible"


@dataclass
class Check:
    id: str
    label: str
    passed: bool
    weight: float


@dataclass
class AssetScore:
    asset_id: str
    name: str
    platform: str
    coverage: float
    freshness: float
    governance: float
    measures_found: list[str]
    measures_missing: list[str]
    scope_score: float
    scope_note: str
    views_90d: int
    lifecycle: str
    owner: str | None = None
    owner_status: str | None = None
    scope_evidence: dict[str, Any] = field(default_factory=dict)
    checks: list[Check] = field(default_factory=list)
    gates_failed: list[str] = field(default_factory=list)
    repairable: list[str] = field(default_factory=list)

    @property
    def gates_pass(self) -> bool:
        return not self.gates_failed

    @property
    def reusable(self) -> bool:
        t = THRESHOLDS
        return (self.gates_pass and not self.measures_missing and self.scope_score == 1.0
                and self.coverage >= t["reuse_coverage"] and self.freshness >= t["reuse_freshness"]
                and self.governance >= t["reuse_governance"])

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["gates_pass"] = self.gates_pass
        # Kept for UI compatibility: scope stands in for breakdown coverage.
        d["dimensions_found"], d["dimensions_missing"], d["grain_supported"] = [], [], True
        return d


@dataclass
class DecisionResult:
    decision: Decision
    rule: str
    reason: str
    candidate: AssetScore | None
    change_type: str | None = None
    flags: list[dict[str, Any]] = field(default_factory=list)
    target_model_id: str | None = None
    replaces: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        rules = ["RULE-004", "RULE-008"] if self.change_type == "scope_review" else RULES_BY_DECISION[self.decision.value]
        return {
            "decision": self.decision.value, "rule": self.rule, "reason": self.reason,
            "candidate": self.candidate.to_dict() if self.candidate else None,
            "change_type": self.change_type, "flags": self.flags, "target_model_id": self.target_model_id,
            "replaces": self.replaces, "rules_applied": rules, "thresholds": THRESHOLDS,
        }


# ---------------------------------------------------------------- scope
def intent_products(intent: dict[str, Any], catalog: dict[str, Any]) -> list[str]:
    f = intent.get("filters") or {}
    names = list(f.get("product") or [])
    for ta in f.get("therapeutic_area") or []:
        names += [p["name"] for p in catalog["products"].values() if p["therapeutic_area"].lower() == ta.lower()]
    return list(dict.fromkeys(names))


def products_disagree(report_product: str, model_product: str) -> bool:
    return report_product != model_product and "All Pharma" not in (report_product, model_product)


def model_scope(intent: dict[str, Any], asset: dict[str, Any], catalog: dict[str, Any]) -> dict[str, Any]:
    """Compare the report's actual upstream model with the product and geography it would have to serve."""
    model_id = asset.get("model_id")
    model = catalog["models"].get(model_id) or {}
    report_product, report_market = asset["product_scope"], asset["market_scope"]
    model_product, model_region = model.get("product_scope"), model.get("region_scope")
    filters = intent.get("filters") or {}
    products = set(intent_products(intent, catalog))
    regions = set(filters.get("region") or [])
    for market in filters.get("market") or []:
        region = catalog["markets"].get(market, {}).get("region")
        if region:
            regions.add(region)
    market_region = catalog["markets"].get(report_market, {}).get("region")
    needs_global = intent.get("scope_global") or "market" in intent.get("dimensions", [])
    outside_model_region = bool(regions - {model_region}) or (not regions and needs_global)
    reason = None
    if not model_product or not model_region:
        reason = f"The scope of the model linked to {asset['id']} is unrecorded."
    elif products_disagree(report_product, model_product):
        reason = f"Report {asset['id']} lists {report_product}, while its linked model {model_id} lists {model_product}."
    elif report_product == "All Pharma" and model_product != "All Pharma" and products != {model_product}:
        reason = f"Report {asset['id']} lists All Pharma, while its linked model {model_id} is scoped to {model_product}."
    elif model_region != "Global" and market_region and market_region != model_region:
        reason = f"Report {asset['id']} lists {report_market} ({market_region}), while its linked model {model_id} lists {model_region}."
    elif report_market == "Global" and model_region != "Global" and outside_model_region:
        reason = f"Report {asset['id']} lists Global, while its linked model {model_id} is scoped to {model_region}."
    return {"asset_id": asset["id"], "asset_product": report_product, "asset_market": report_market, "model_id": model_id,
            "model_product": model_product, "model_region": model_region, "conflict": bool(reason), "reason": reason}


def scope_match(intent: dict[str, Any], asset: dict[str, Any], catalog: dict[str, Any]) -> tuple[float, str]:
    """How well the asset's product and market scope fit the request (0 to 1)."""
    f = intent.get("filters") or {}
    products = intent_products(intent, catalog)
    multi_product = len(products) != 1 or "product" in intent.get("dimensions", [])
    ps = asset["product_scope"]
    if multi_product:
        p_ok = 1.0 if ps == "All Pharma" else (0.5 if ps in products else 0.0)
    else:
        p_ok = 1.0 if ps in (products[0], "All Pharma") else 0.0

    markets, regions = f.get("market") or [], f.get("region") or []
    ms = asset["market_scope"]
    needs_global = intent.get("scope_global") or "market" in intent.get("dimensions", []) or len(markets) > 1 or len(regions) > 1
    if intent.get("other_markets"):
        m_ok = 0.0  # no report covers a country the catalog holds no data for, not even a Global one
    elif ms == "Global":
        m_ok = 1.0
    elif needs_global:
        m_ok = 0.0
    elif markets:
        m_ok = 1.0 if ms in markets else 0.0
    elif regions:
        region_of = catalog["markets"].get(ms, {}).get("region")
        m_ok = 0.5 if region_of in regions else 0.0
    else:
        m_ok = 0.5
    note = f"product {ps} ({'fits' if p_ok == 1 else 'partly fits' if p_ok else 'does not fit'}), market {ms} ({'fits' if m_ok == 1 else 'partly fits' if m_ok else 'does not fit'})"
    return round((p_ok + m_ok) / 2, 3), note


# ---------------------------------------------------------------- scores
def coverage(intent: dict[str, Any], asset: dict[str, Any], catalog: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    req = intent.get("measures", [])
    found = [m for m in req if m in asset["measures"]]
    scope, note = scope_match(intent, asset, catalog)
    value = 0.0 if not req else COVERAGE_WEIGHTS["measures"] * len(found) / len(req) + COVERAGE_WEIGHTS["scope"] * scope
    return round(value, 3), {"measures_found": found, "measures_missing": [m for m in req if m not in found],
                             "scope_score": scope, "scope_note": note}


def freshness(asset: dict[str, Any]) -> float:
    return FRESHNESS_BY_REFRESH.get(asset.get("refresh_status"), 0.5)


def governance(asset: dict[str, Any], intent: dict[str, Any] | None = None) -> tuple[float, list[Check]]:
    """Governance of the asset for this request. Without an intent, all KPIs it uses are checked."""
    req = set((intent or {}).get("measures") or []) or set(asset.get("measures", []))
    bad_defs = (set(asset.get("conflicts") or {}) | set(asset.get("variants") or {})) & req
    passed = {
        "definitions_match": not bad_defs,
        "endorsed": asset.get("endorsement") in ("certified", "promoted"),
        "owner_active": asset.get("owner_status") == "active",
        "no_open_high_signals": not any(s["status"] == "open" and s["severity"] == "high" for s in asset.get("signals", [])),
        "lifecycle_active": asset.get("lifecycle") == "active",
        "ai_ready_model": asset.get("model_ai_readiness") == "good",
    }
    checks = [Check(k, GOVERNANCE_LABELS[k], passed[k], w) for k, w in GOVERNANCE_WEIGHTS.items()]
    return round(sum(c.weight for c in checks if c.passed), 3), checks


def gates(asset: dict[str, Any], intent: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Hard gates block reuse. Returns (failed gates, of which repairable)."""
    failed, repairable = [], []
    for m, why in (asset.get("conflicts") or {}).items():
        if m in intent.get("measures", []):
            failed.append(f"Metric conflict: {why}")
    if asset.get("lifecycle") == "candidate_retire":
        failed.append("Marked as a candidate for retirement (RULE-006).")
    if asset.get("owner_status") != "active":
        msg = f"Owner {asset.get('owner')} is {asset.get('owner_status')} (RULE-003)."
        failed.append(msg)
        repairable.append(msg)
    return failed, repairable


def score_asset(intent: dict[str, Any], asset: dict[str, Any], catalog: dict[str, Any]) -> AssetScore:
    cov, det = coverage(intent, asset, catalog)
    gov, checks = governance(asset, intent)
    failed, repairable = gates(asset, intent)
    evidence = model_scope(intent, asset, catalog)
    if evidence["conflict"]:
        failed.append(evidence["reason"])
    return AssetScore(asset_id=asset["id"], name=asset["name"], platform=asset["platform"], coverage=cov,
                      freshness=freshness(asset), governance=gov, views_90d=asset.get("views_90d", 0),
                      lifecycle=asset.get("lifecycle", ""), owner=asset.get("owner"),
                      owner_status=asset.get("owner_status"), checks=checks, gates_failed=failed,
                      repairable=repairable, scope_evidence=evidence, **det)


def rank_candidates(intent: dict[str, Any], catalog: dict[str, Any]) -> list[AssetScore]:
    scored = [score_asset(intent, a, catalog) for a in catalog["assets"]]
    scored = [s for s in scored if s.measures_found]
    return sorted(scored, key=lambda s: (s.coverage, s.governance, s.freshness, s.views_90d), reverse=True)


# ---------------------------------------------------------------- data availability
def data_availability(intent: dict[str, Any], catalog: dict[str, Any]) -> dict[str, Any]:
    """Every requested measure needs an approved KPI and a semantic model that serves it."""
    measures = catalog["measures"]
    req = intent.get("measures", [])
    missing_terms = list(intent.get("unmatched_terms", []))
    uncertified = [m for m in req if m in measures and not measures[m]["certified"]]
    models = rank_models(intent, catalog)
    best = models[0] if models else None
    covered = set(best["measures_served"]) if best else set()
    return {
        "available": bool(req) and not missing_terms and not uncertified,
        "missing_terms": missing_terms, "uncertified_measures": uncertified, "missing_dimensions": [],
        "best_model": best, "models": models[:5],
        "model_gaps": [m for m in req if m not in covered],
        "datasets": [best["id"]] if best else [],
    }


def rank_models(intent: dict[str, Any], catalog: dict[str, Any]) -> list[dict[str, Any]]:
    """Shared semantic models that could host the request, best first (RULE-001: reuse shared models)."""
    req = set(intent.get("measures", []))
    filters = intent.get("filters") or {}
    brief = intent.get("dashboard_brief") or {}
    regions = set(filters.get("region") or [])
    regions.update(catalog["markets"][market]["region"] for market in filters.get("market", []) if market in catalog["markets"])
    products = set(intent_products(intent, catalog))
    out = []
    for m in catalog["models"].values():
        if products and m["product_scope"] != "All Pharma" and products != {m["product_scope"]}:
            continue
        if regions and m["region_scope"] != "Global" and regions != {m["region_scope"]}:
            continue
        if brief.get("all_products") and m["product_scope"] != "All Pharma":
            continue
        if brief.get("all_markets") and m["region_scope"] != "Global":
            continue
        served = sorted(req & set(m["measures"]))
        if not served:
            continue
        score = (len(served) / len(req) * 0.5
                 + (0.15 if m["endorsement"] == "certified" else 0.08 if m["endorsement"] == "promoted" else 0)
                 + {"healthy": 0.15, "warning": 0.07}.get(m["refresh_status"], 0)
                 + {"good": 0.1, "partial": 0.05}.get(m["ai_readiness"], 0)
                 + (0.05 if m["platform"] == "Power BI" else 0)
                 + (0.05 if m["region_scope"] == "Global" or m["region_scope"] in regions else 0)
                 + (0.05 if m["product_scope"] == "All Pharma" or m["product_scope"] in products else 0))
        out.append({"id": m["id"], "name": m["name"], "workspace": m["workspace"], "platform": m["platform"],
                    "endorsement": m["endorsement"], "refresh_status": m["refresh_status"], "ai_readiness": m["ai_readiness"],
                    "measures_served": served, "score": round(score, 3)})
    return sorted(out, key=lambda x: x["score"], reverse=True)


# ---------------------------------------------------------------- decision
def _flags(candidates: list[AssetScore], chosen: AssetScore | None) -> list[dict[str, Any]]:
    t = THRESHOLDS
    flags = []
    for c in candidates:
        if chosen and c.asset_id == chosen.asset_id:
            continue
        if c.coverage < t["flag_overlap_coverage"]:
            continue
        reasons = []
        if c.lifecycle == "candidate_retire":
            reasons.append("already marked for retirement")
        if c.views_90d < t["low_usage_views_90d"]:
            reasons.append(f"low usage ({c.views_90d} views in 90 days)")
        if c.governance < t["flag_governance_below"]:
            reasons.append(f"poorly governed ({c.governance:.2f})")
        if any(g.startswith("Metric conflict") for g in c.gates_failed):
            reasons.append("uses a conflicting KPI definition")
        if reasons:
            flags.append({"asset_id": c.asset_id, "name": c.name, "coverage": c.coverage, "views_90d": c.views_90d,
                          "message": "Overlaps this request but is " + ", ".join(reasons) + ". Propose consolidating or retiring it."})
    return flags[: t["max_flags"]]


def decide(candidates: list[AssetScore], availability: dict[str, Any], intent: dict[str, Any] | None = None,
           catalog: dict[str, Any] | None = None) -> DecisionResult:
    t = THRESHOLDS
    intent = intent or {}
    best_model = availability.get("best_model")
    missing = (availability.get("missing_terms") or []) + (availability.get("uncertified_measures") or [])
    if missing:
        return DecisionResult(Decision.NOT_FEASIBLE, "Required KPIs are missing or unapproved.",
                              "The governed data cannot answer the full request. Unavailable requirements: " + ", ".join(missing),
                              None)

    if catalog is not None:
        result = _decide_retirement(candidates, intent, catalog)
        if result:
            return result

    # Migration requests: never migrate 1:1 without checking for reuse first (RULE-006).
    if intent.get("migration") and catalog is not None:
        result = _decide_migration(candidates, availability, intent, catalog)
        if result:
            return result

    in_scope = [c for c in candidates if c.scope_score >= t["min_scope"]]
    for c in in_scope:
        if c.reusable:
            return DecisionResult(
                Decision.REUSE,
                f"coverage {c.coverage:.2f} ≥ {t['reuse_coverage']}, freshness {c.freshness:.2f} ≥ {t['reuse_freshness']}, "
                f"governance {c.governance:.2f} ≥ {t['reuse_governance']}, no gate failed",
                f"'{c.name}' already answers this request with approved KPIs and an active owner.", c, flags=_flags(candidates, c))

    for c in in_scope:
        # Conflicting KPIs and retirement candidates are not repaired: switching definitions changes the numbers.
        only_fixable = set(c.gates_failed) <= set(c.repairable)
        if c.coverage >= t["reuse_coverage"] and only_fixable and c.governance >= t["repair_min_governance"] \
                and (c.views_90d >= t["repair_min_views_90d"] or c.governance >= t["reuse_governance"]) \
                and (c.freshness < t["reuse_freshness"] or c.repairable or c.governance < t["reuse_governance"]):
            failed = {k.id for k in c.checks if not k.passed}
            fixes = []
            if c.freshness < t["reuse_freshness"]:
                fixes.append("fix the failing or unstable refresh")
            if c.repairable:
                fixes.append("assign an active owner")
            if "definitions_match" in failed:
                fixes.append("switch local KPI variants to the approved definitions")
            if "endorsed" in failed:
                fixes.append("review and endorse it")
            if "ai_ready_model" in failed:
                fixes.append("make the model AI-ready (clear names, explicit measures)")
            return DecisionResult(
                Decision.REPAIR,
                f"coverage {c.coverage:.2f} ≥ {t['reuse_coverage']}, {c.views_90d} views in 90 days, governance {c.governance:.2f}: repair before reuse",
                f"'{c.name}' covers the request. Repair it ({'; '.join(fixes)}) instead of building a copy.",
                c, change_type="maintenance", flags=_flags(candidates, c))

    for c in in_scope:
        # A metadata contradiction warrants review when the report otherwise covers the request.
        if (c.scope_evidence.get("conflict") and not c.measures_missing and c.coverage >= t["reuse_coverage"]
                and set(c.gates_failed) - set(c.repairable) == {c.scope_evidence["reason"]}):
            contact = c.owner if c.owner_status == "active" else "the BI team"
            return DecisionResult(
                Decision.REVIEW, "Report and model scope must be reconciled before reuse (RULE-004).",
                f"{c.scope_evidence['reason']} Ask {contact} to verify the model binding and its data coverage before using this report.",
                c, change_type="scope_review", target_model_id=c.scope_evidence["model_id"], flags=_flags(candidates, c))

    n_req = max(len(intent.get("measures", [])), 1)
    for c in in_scope:
        if c.gates_pass and t["consolidate_min_coverage"] <= c.coverage < t["reuse_coverage"] \
                and len(c.measures_found) / n_req >= t["consolidate_min_measures"] and c.governance >= t["consolidate_governance"]:
            flags = _flags(candidates, c)
            return DecisionResult(
                Decision.CONSOLIDATE,
                f"{t['consolidate_min_coverage']} ≤ coverage {c.coverage:.2f} < {t['reuse_coverage']}, governance {c.governance:.2f} ≥ {t['consolidate_governance']}",
                f"'{c.name}' covers most of the request. Extend it with the missing parts and fold overlapping reports into it.",
                c, change_type="business", flags=flags, replaces=[f["asset_id"] for f in flags])

    if availability["available"] and best_model:
        others = intent.get("other_markets") or []
        named_market = others or (intent.get("filters") or {}).get("market")
        # A report for another country is not an overlap, and a new report for this one does not replace it.
        flags = _flags(in_scope if named_market else candidates, None)
        names = ", ".join(others)
        why = (f"No existing report covers {names}." if others
               else "No existing report is both close enough and well governed." if candidates
               else "Nothing in the estate answers this request yet.")
        return DecisionResult(
            Decision.NEW_BUILD, f"no asset passes reuse, repair or consolidate rules; shared model {best_model['id']} serves "
                                f"{len(best_model['measures_served'])} of {len(intent.get('measures', []))} measures"
                                + (f"; {names} not in the catalog's markets" if others else ""),
            why + f" Build one thin report on the shared model '{best_model['name']}' with approved KPIs only."
            + (f" The catalog holds no data for {names} yet, so that data has to be added first." if others else ""),
            candidates[0] if candidates else None, flags=flags, target_model_id=best_model["id"],
            replaces=[f["asset_id"] for f in flags])

    return DecisionResult(Decision.NOT_FEASIBLE, "required KPIs are missing or not approved",
                          "The catalog has no approved KPI or semantic model for this request.", None, flags=_flags(candidates, None))


def _decide_retirement(candidates: list[AssetScore], intent: dict[str, Any], catalog: dict[str, Any]) -> DecisionResult | None:
    """Someone asks to retire a report: recommend it only if the evidence supports it, and say so if it does not."""
    t = THRESHOLDS
    question = intent.get("question") or ""
    if not RETIRE_WORDS.search(question):
        return None
    low = question.lower()
    named = [a for a in catalog["assets"] if a["name"].lower() in low]
    if named:
        target = score_asset(intent, max(named, key=lambda a: len(a["name"])), catalog)
    else:
        target = next((c for c in candidates if c.scope_score >= t["min_scope"]), None)
    if not target:
        return None
    reasons = []
    if target.lifecycle == "candidate_retire":
        reasons.append("it is already marked for retirement")
    if target.views_90d < t["low_usage_views_90d"]:
        reasons.append(f"it has low usage ({target.views_90d} views in 90 days)")
    if target.governance < t["flag_governance_below"]:
        reasons.append(f"it is poorly governed ({target.governance:.2f})")
    if reasons:
        return DecisionResult(Decision.RETIRE, "; ".join(reasons), f"Retire '{target.name}': " + " and ".join(reasons) + ".", target,
                              flags=_flags(candidates, target), replaces=[target.asset_id])
    return DecisionResult(Decision.REUSE, f"{target.views_90d} views in 90 days, governance {target.governance:.2f}: no retirement criterion met",
                          f"Keep '{target.name}': it is in use and well governed, so the evidence does not support retiring it.", target,
                          flags=_flags(candidates, target))


def _decide_migration(candidates: list[AssetScore], availability: dict[str, Any], intent: dict[str, Any],
                      catalog: dict[str, Any]) -> DecisionResult | None:
    """Tableau to Power BI: rationalise first, then rebuild what people use on a shared model (RULE-006)."""
    t = THRESHOLDS
    products = set(intent_products(intent, catalog))
    legacy = [a for a in catalog["assets"] if a["platform"] == "Tableau" and a["product_scope"] in products]
    pbi = [c for c in candidates if c.platform == "Power BI" and c.reusable]

    def path(a: dict[str, Any]) -> str:
        return (a.get("migration") or {}).get("recommended_path_candidate") or "not in backlog"

    worth_keeping = sorted([a for a in legacy if path(a) != "RETIRE" and a["views_90d"] >= t["low_usage_views_90d"]
                            and a["lifecycle"] != "candidate_retire"], key=lambda a: a["views_90d"], reverse=True)
    # A report the backlog holds for a human decision is not cleared to move, however much it is used.
    keep = [a for a in worth_keeping if path(a) != "HUMAN_REVIEW"]
    in_review = [a for a in worth_keeping if path(a) == "HUMAN_REVIEW"]
    flags = []
    for a in sorted(legacy, key=lambda a: a["views_90d"], reverse=True):
        if a in keep[:1]:
            continue
        why = ("the backlog recommends RETIRE" if path(a) == "RETIRE" else
               f"low usage" if a["views_90d"] < t["low_usage_views_90d"] else
               "it is already marked for retirement" if a["lifecycle"] == "candidate_retire" else "")
        if why:
            verdict = f"retire, do not migrate ({why})"
        elif path(a) == "HUMAN_REVIEW":
            verdict = "needs human review before migration"
        else:
            verdict = "fold into the new Power BI report"
        flags.append({"asset_id": a["id"], "name": a["name"], "coverage": 0, "views_90d": a["views_90d"],
                      "message": f"Tableau, {a['views_90d']} views in 90 days, backlog path {path(a)}: {verdict}."})
    flags = flags[: t["max_flags"] + 3]

    if pbi:
        return DecisionResult(
            Decision.REUSE, "a governed Power BI report already covers the request (RULE-006: do not migrate waste)",
            f"No migration needed: '{pbi[0].name}' already covers it in Power BI. Retire the {len(legacy)} Tableau assets instead.",
            pbi[0], flags=flags, replaces=[a["id"] for a in legacy])
    if not keep and in_review:
        top = in_review[0]
        return DecisionResult(
            Decision.REVIEW, f"{len(legacy)} Tableau assets for {', '.join(sorted(products))}; none is cleared to migrate, "
                             f"{len(in_review)} wait for a human decision in the backlog (RULE-006)",
            f"Have someone review '{top['name']}' before anything moves: the backlog holds it for a human decision, "
            f"and no other Tableau report here is cleared to migrate.",
            next((c for c in candidates if c.asset_id == top["id"]), None) or score_asset(intent, top, catalog),
            flags=flags, replaces=[])
    if not keep:
        if not legacy:
            return None
        top = max(legacy, key=lambda a: a["views_90d"])
        return DecisionResult(
            Decision.RETIRE, f"{len(legacy)} Tableau assets for {', '.join(sorted(products))}; none has real usage or a migration path (RULE-006)",
            f"Retire the {len(legacy)} Tableau assets instead of moving them: none is worth migrating.",
            next((c for c in candidates if c.asset_id == top["id"]), None) or score_asset(intent, top, catalog),
            flags=flags, replaces=[a["id"] for a in legacy])
    src = keep[0]
    source_score = next((c for c in candidates if c.asset_id == src["id"]), None) or score_asset(intent, src, catalog)
    target = (src.get("migration") or {}).get("candidate_target_model_id") or (availability.get("best_model") or {}).get("id")
    return DecisionResult(
        Decision.MIGRATE,
        f"{len(legacy)} Tableau assets for {', '.join(sorted(products))}; {len(keep)} have real usage; "
        f"main source {src['id']} ({src['views_90d']} views, backlog {path(src)})",
        f"Rebuild '{src['name']}' as one Power BI report on the shared model {target} with approved KPIs. "
        f"Of the other {len(legacy) - 1} Tableau assets, retire the unused ones instead of copying them 1:1.",
        source_score, change_type="business", flags=flags, target_model_id=target,
        replaces=[a["id"] for a in legacy])
