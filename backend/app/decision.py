"""Deterministic scoring and the reuse / extend / create decision.

The AI extracts facts (the intent and the catalog candidates). This module
decides. Same inputs always give the same decision, and every score is shown
to the user. Change thresholds and weights here only.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from enum import Enum
from typing import Any

GRAIN_ORDER = {"hour": 0, "day": 1, "week": 2, "month": 3}
FRESHNESS_TARGET_HOURS = {"hour": 2, "day": 24, "week": 168, "month": 744}

THRESHOLDS = {
    "reuse_coverage": 0.90,
    "reuse_freshness": 0.90,
    "min_governance": 0.80,
    "extend_min_coverage": 0.60,
    "ungoverned_governance": 0.60,   # below this an overlapping asset is flagged for merge/retirement
    "flag_overlap_coverage": 0.40,
    "review_max_days": 365,
}

COVERAGE_WEIGHTS = {"measures": 0.5, "dimensions": 0.3, "grain": 0.2}

GOVERNANCE_WEIGHTS = {
    "definitions_match": 0.30,
    "certified": 0.20,
    "owner_active": 0.20,
    "tests_passing": 0.15,
    "recently_reviewed": 0.10,
    "documented": 0.05,
}

GOVERNANCE_LABELS = {
    "definitions_match": "Metric definitions match certified definitions",
    "certified": "Asset is certified",
    "owner_active": "Owner is active",
    "tests_passing": "Data quality tests pass",
    "recently_reviewed": "Reviewed in the last 12 months",
    "documented": "Purpose and fields documented",
}


class Decision(str, Enum):
    REUSE = "reuse"
    EXTEND = "extend"
    CREATE = "create"
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
    coverage: float
    freshness: float
    governance: float
    measures_found: list[str]
    measures_missing: list[str]
    dimensions_found: list[str]
    dimensions_missing: list[str]
    grain_supported: bool
    checks: list[Check] = field(default_factory=list)
    gates_failed: list[str] = field(default_factory=list)

    @property
    def gates_pass(self) -> bool:
        return not self.gates_failed

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["gates_pass"] = self.gates_pass
        return d


@dataclass
class DecisionResult:
    decision: Decision
    rule: str
    reason: str
    candidate: AssetScore | None
    change_type: str | None = None  # "business" or "maintenance" for Extend
    flags: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.value,
            "rule": self.rule,
            "reason": self.reason,
            "candidate": self.candidate.to_dict() if self.candidate else None,
            "change_type": self.change_type,
            "flags": self.flags,
            "thresholds": THRESHOLDS,
        }


def _ratio(found: int, required: int) -> float:
    return 1.0 if required == 0 else found / required


def grain_supported(asset_grain: str, intent_grain: str) -> bool:
    """An asset supports the intent grain if its own grain is the same or finer."""
    return GRAIN_ORDER.get(asset_grain, 99) <= GRAIN_ORDER.get(intent_grain, 1)


def coverage(intent: dict[str, Any], asset: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    req_m, req_d = intent.get("measures", []), intent.get("dimensions", [])
    found_m = [m for m in req_m if m in asset["measures"]]
    found_d = [d for d in req_d if d in asset["dimensions"]]
    g_ok = grain_supported(asset["grain"], intent.get("grain", "day"))
    if not req_m:
        value = 0.0
    else:
        value = (
            COVERAGE_WEIGHTS["measures"] * _ratio(len(found_m), len(req_m))
            + COVERAGE_WEIGHTS["dimensions"] * _ratio(len(found_d), len(req_d))
            + COVERAGE_WEIGHTS["grain"] * (1.0 if g_ok else 0.0)
        )
    return round(value, 3), {
        "measures_found": found_m,
        "measures_missing": [m for m in req_m if m not in found_m],
        "dimensions_found": found_d,
        "dimensions_missing": [d for d in req_d if d not in found_d],
        "grain_supported": g_ok,
    }


def freshness(age_hours: float, grain: str) -> float:
    """1.0 within the freshness target for the grain, falling linearly to 0 at three times the target."""
    target = FRESHNESS_TARGET_HOURS.get(grain, 24)
    if age_hours <= target:
        return 1.0
    return round(max(0.0, 1.0 - (age_hours - target) / (2 * target)), 3)


def governance(asset: dict[str, Any], today: date | None = None) -> tuple[float, list[Check]]:
    today = today or date.today()
    reviewed = asset.get("last_review")
    recently = bool(reviewed) and (today - date.fromisoformat(reviewed)).days <= THRESHOLDS["review_max_days"]
    passed = {
        "definitions_match": not asset.get("conflicts"),
        "certified": bool(asset.get("certified")),
        "owner_active": asset.get("owner_status") == "active",
        "tests_passing": bool(asset.get("tests_passing")),
        "recently_reviewed": recently,
        "documented": bool(asset.get("documented")),
    }
    checks = [Check(k, GOVERNANCE_LABELS[k], passed[k], w) for k, w in GOVERNANCE_WEIGHTS.items()]
    return round(sum(c.weight for c in checks if c.passed), 3), checks


def gates(asset: dict[str, Any], intent: dict[str, Any]) -> list[str]:
    failed = []
    conflicts = {m: why for m, why in (asset.get("conflicts") or {}).items() if m in intent.get("measures", [])}
    for m, why in conflicts.items():
        failed.append(f"Metric conflict on '{m}': {why}")
    if asset.get("restricted"):
        failed.append("You do not have access to this workspace.")
    if asset.get("owner_status") != "active" and not asset.get("backup_owner"):
        failed.append("Owner has left and no backup owner is assigned.")
    return failed


def score_asset(intent: dict[str, Any], asset: dict[str, Any], today: date | None = None) -> AssetScore:
    cov, det = coverage(intent, asset)
    gov, checks = governance(asset, today)
    return AssetScore(
        asset_id=asset["id"],
        name=asset["name"],
        coverage=cov,
        freshness=freshness(asset.get("refresh_age_hours", 1e9), intent.get("grain", "day")),
        governance=gov,
        checks=checks,
        gates_failed=gates(asset, intent),
        **det,
    )


def rank_candidates(intent: dict[str, Any], assets: list[dict[str, Any]], today: date | None = None) -> list[AssetScore]:
    scored = [score_asset(intent, a, today) for a in assets]
    scored = [s for s in scored if s.measures_found]
    return sorted(scored, key=lambda s: (s.coverage, s.governance, s.freshness), reverse=True)


def decide(candidates: list[AssetScore], data_available: bool) -> DecisionResult:
    t = THRESHOLDS
    eligible = [c for c in candidates if c.gates_pass and c.governance >= t["min_governance"]]

    flags = [
        {"asset_id": c.asset_id, "name": c.name,
         "message": "Overlaps this request but is poorly governed. Propose merging into the chosen asset or retiring it."}
        for c in candidates
        if c.coverage >= t["flag_overlap_coverage"] and (c.governance < t["ungoverned_governance"] or not c.gates_pass)
    ]

    for c in eligible:
        if c.coverage >= t["reuse_coverage"] and c.freshness >= t["reuse_freshness"]:
            return DecisionResult(
                Decision.REUSE,
                f"Coverage {c.coverage:.2f} ≥ {t['reuse_coverage']} and freshness {c.freshness:.2f} ≥ {t['reuse_freshness']} "
                f"and governance {c.governance:.2f} ≥ {t['min_governance']}, no gate failed",
                f"'{c.name}' already answers this request with certified data.",
                c, flags=flags)

    for c in eligible:
        if c.coverage >= t["reuse_coverage"]:
            return DecisionResult(
                Decision.EXTEND,
                f"Coverage {c.coverage:.2f} ≥ {t['reuse_coverage']} but freshness {c.freshness:.2f} < {t['reuse_freshness']}",
                f"'{c.name}' covers the request, but its data is older than this request needs. Fix the refresh schedule instead of building a copy.",
                c, change_type="maintenance", flags=flags)
        if c.coverage >= t["extend_min_coverage"]:
            return DecisionResult(
                Decision.EXTEND,
                f"{t['extend_min_coverage']} ≤ coverage {c.coverage:.2f} < {t['reuse_coverage']} and governance {c.governance:.2f} ≥ {t['min_governance']}",
                f"'{c.name}' covers most of the request. Add the missing parts to it instead of building a new report.",
                c, change_type="business", flags=flags)

    if data_available:
        best = candidates[0] if candidates else None
        why = ("No governed asset covers enough of this request." if candidates
               else "Nothing in the catalog answers this request yet.")
        return DecisionResult(Decision.CREATE, "No asset passes the reuse or extend rules; required data exists in the catalog",
                              why + " The required data exists, so a new report can be built from certified sources.",
                              best, flags=flags)

    return DecisionResult(Decision.NOT_FEASIBLE, "Required measures or dimensions are not in the catalog",
                          "The catalog does not contain the data this request needs.", None, flags=flags)


def data_availability(intent: dict[str, Any], catalog: dict[str, Any]) -> dict[str, Any]:
    """Check that every requested measure has a source dataset and every dimension is available there."""
    measures = catalog["measures"]
    missing_terms = list(intent.get("unmatched_terms", []))
    req_m = intent.get("measures", [])
    datasets = sorted({measures[m]["dataset"] for m in req_m if m in measures})
    dims_available = {d for ds in datasets for d in catalog["datasets"].get(ds, {}).get("dimensions", [])}
    missing_dims = [d for d in intent.get("dimensions", []) if d not in dims_available]
    available = bool(req_m) and not missing_terms and not missing_dims
    return {"available": available, "datasets": datasets, "missing_terms": missing_terms, "missing_dimensions": missing_dims}
