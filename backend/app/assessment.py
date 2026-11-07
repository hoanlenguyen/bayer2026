"""One request's assessment, run step by step so each visible stage reports the work it actually did.

Each method runs one stage's real operation and keeps its result for the stages that depend on it:

    scope()     request tags known from the intent alone (no catalog ranking)        -> step 1
    kpis()      governed KPI definitions and conflicting variants                     -> step 2
    discover()  candidate ranking, data availability and the rules decision, once     -> step 3
    lineage()   lineage of the model the decision points at                           -> step 4
    trust()     owner, certification, refresh and quality evidence for that subject   -> step 5
    migration() Tableau migration evidence, or why it does not apply                  -> step 6

`run()` executes them in order. `tags_for_intent` (classification, Simulator) and the Ask flow's `analyse` both go
through this class, so the ranking and the decision are computed once per request and every consumer sees the same
result. Pure: reads the catalog, saves nothing.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from . import catalog as cat
from .decision import data_availability, decide, intent_products, rank_candidates
from .steps import check_trust, find_analytics, handle_migration, parse_request, recommendation, resolve_kpis, trace_lineage

# How a decision answers "does a report already exist?"
REPORT_STATUS = {"reuse": ("yes", "usable"), "repair": ("yes", "needs_repair"), "migrate": ("yes", "needs_migration"),
                 "consolidate": ("no", "partial_match"), "new_build": ("no", "none"), "not_feasible": ("no", "none"),
                 "retire": ("yes", "retire"), "review": ("yes", "needs_review")}

ORDER = ("kpis", "discovery", "lineage", "governance", "migration")


class Assessment:
    def __init__(self, intent: dict[str, Any], matched_by: dict[str, dict[str, Any]] | None = None) -> None:
        self.intent = intent
        self.C = cat.CATALOG
        self.matched_by = matched_by or {}
        self.governed = [m for m in intent.get("measures") or [] if m in self.C["measures"] and self.C["measures"][m]["certified"]]
        self.steps: dict[int, dict[str, Any]] = {}
        self.candidates: list | None = None
        self.availability: dict[str, Any] | None = None
        self.result = None
        self.report: dict[str, Any] | None = None
        self.assessed: dict[str, Any] = {}

    # ---------------------------------------------------------------- 1
    def scope(self) -> dict[str, Any]:
        """What the intent alone says. Safe for a clarification: nothing from the catalog ranking."""
        C, intent = self.C, self.intent
        filters = intent.get("filters") or {}
        domains = Counter(C["measures"][m]["domain"] for m in self.governed)
        market = ([C["markets"][m]["name"] for m in filters.get("market", []) if m in C["markets"]] + list(filters.get("region", []))
                  + list(intent.get("other_markets") or []))
        return {
            "domain": domains.most_common(1)[0][0] if domains else None,
            "market": market or (["Global"] if intent.get("scope_global") else []),
            "product": intent_products(intent, C),
            "breakdown": [C["dimensions"][d]["name"] for d in intent.get("dimensions") or [] if d in C["dimensions"]],
            "governed_kpis": [{"id": m, "kpi_id": C["measures"][m].get("kpi_id"), "name": C["measures"][m]["name"],
                               "domain": C["measures"][m]["domain"], **self.matched_by.get(m, {})} for m in self.governed],
            "not_available": list(intent.get("unmatched_terms") or []),
        }

    def parse(self) -> dict[str, Any]:
        self.steps[1] = parse_request(self.intent, self.scope())
        return self.steps[1]

    # ---------------------------------------------------------------- 2
    def kpis(self) -> dict[str, Any]:
        self.steps[2] = resolve_kpis(self.governed)
        return self.steps[2]

    # ---------------------------------------------------------------- 3
    def discover(self) -> dict[str, Any]:
        """Rank candidates, check data availability and apply the decision rules: the one catalog scan for this request."""
        C, intent = self.C, self.intent
        self.candidates = rank_candidates(intent, C)
        self.availability = data_availability(intent, C)
        self.result = result = decide(self.candidates, self.availability, intent, C)
        model = self.availability.get("best_model")
        target_id = result.target_model_id
        if not target_id and result.candidate and result.decision.value in {"reuse", "repair", "consolidate", "retire", "review"}:
            target_id = result.candidate.scope_evidence.get("model_id")
        if target_id and (not model or model["id"] != target_id):
            target = cat.model_by_id(target_id)
            if target:
                model = {"id": target["id"], "name": target["name"], "workspace": target["workspace"], "platform": target["platform"],
                         "endorsement": target["endorsement"], "refresh_status": target["refresh_status"],
                         "measures_served": sorted(set(self.governed) & set(target["measures"]))}
        exists, status = REPORT_STATUS[result.decision.value]
        c = result.candidate
        named = None  # a closest report is only worth naming when it is the one the answer refers to
        if c and status != "none":
            asset = cat.asset_by_id(c.asset_id) or {}
            named = {"id": c.asset_id, "name": c.name, "platform": c.platform, "workspace": asset.get("workspace"),
                     "owner": asset.get("owner"), "coverage": c.coverage, "governance": c.governance}
        self.report = cat.asset_by_id(c.asset_id) if c else None
        self.assessed = {
            "semantic_model": None if not model else {
                "id": model["id"], "name": model["name"], "workspace": model["workspace"], "platform": model["platform"],
                "endorsement": model["endorsement"], "refresh_status": model["refresh_status"],
                "serves_all_kpis": set(model["measures_served"]) >= set(self.governed),
            },
            "existing_report": exists,
            "existing_report_detail": {"status": status, "decision": result.decision.value, "report": named},
        }
        self.steps[3] = find_analytics(self.candidates)
        return self.steps[3]

    @property
    def model_id(self) -> str | None:
        return (self.assessed.get("semantic_model") or {}).get("id")

    # ---------------------------------------------------------------- 4 to 6 (use the decision's subject)
    def lineage(self) -> dict[str, Any]:
        self.steps[4] = trace_lineage(self.model_id)
        return self.steps[4]

    def trust(self) -> dict[str, Any]:
        self.steps[5] = check_trust(self.report, self.model_id, self.result.candidate if self.result else None)
        return self.steps[5]

    def migration(self) -> dict[str, Any]:
        self.steps[6] = handle_migration(self.intent, self.report)
        return self.steps[6]

    STAGES = {"kpis": "kpis", "discovery": "discover", "lineage": "lineage", "governance": "trust", "migration": "migration"}

    def run_stage(self, stage: str) -> dict[str, Any]:
        return getattr(self, self.STAGES[stage])()

    # ---------------------------------------------------------------- all
    def run(self) -> "Assessment":
        self.parse()
        for stage in ORDER:
            self.run_stage(stage)
        return self

    def tags(self) -> dict[str, Any]:
        """The full classification, same shape as before: scope, model, existing report, recommendation and six steps."""
        steps = [self.steps[n] for n in range(1, 7)]
        return {**self.scope(), **self.assessed, "recommendation": recommendation(self.result, steps), "steps": steps}


def tags_for_intent(intent: dict[str, Any], matched_by: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """The tags that follow from an intent, however it was extracted. Same rules as the Ask flow, so the answers agree."""
    return Assessment(intent, matched_by).run().tags()
