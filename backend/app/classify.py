"""Classify one business request into tags: urgency, domain, market, product, KPIs, semantic model, existing report.

No chat model runs here and nothing is saved. The only outside call is the embedding for vector search.

- Urgency comes from the vector store: SinceAI's labelled requests closest to this one vote. Explicit deadline words in
  the request win over the vote. The vote is weak evidence (see `triage.label_predictability`), so the result carries
  its votes and confidence.
- Product and market come only from the request's own words. The sheet's context columns can contradict the request
  text (REQ-0001 asks about Nubeqa, its product_context says Beyonttra), so similar rows are not used for them.
- KPIs come from keywords, or from the vector store when no keyword matches.
- Semantic model and existing report come from the same rules as the Ask flow (`decision.py`).
"""
from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from . import catalog as cat
from .agents.intent import OUT_OF_SCOPE, jev_match, jev_urgency, match_dimensions, match_filters, match_measures
from .decision import data_availability, decide, intent_products, rank_candidates
from .geo import other_markets
from .steps import analysis_steps, recommendation
from .triage import URGENCY_VALUES, infer_urgency
from .vectors import DUPLICATE_THRESHOLD, SIMILAR_THRESHOLD, VectorStore, suggest_kpis

log = logging.getLogger(__name__)

NEIGHBOURS = 30  # the most repeated request text appears 22 times
# How a decision answers "does a report already exist?"
REPORT_STATUS = {"reuse": ("yes", "usable"), "repair": ("yes", "needs_repair"), "migrate": ("yes", "needs_migration"),
                 "consolidate": ("no", "partial_match"), "new_build": ("no", "none"), "not_feasible": ("no", "none"),
                 "retire": ("yes", "retire"), "review": ("yes", "needs_review")}


def vote_urgency(neighbours: list[tuple[str | None, float]], duplicate_at: float, similar_at: float) -> dict[str, Any] | None:
    """Majority urgency among the closest labelled requests. Exact asks outrank merely similar ones; ties go to the more urgent."""
    same = [u for u, score in neighbours if score >= duplicate_at and u in URGENCY_VALUES]
    voters = same or [u for u, score in neighbours if score >= similar_at and u in URGENCY_VALUES]
    if not voters:
        return None
    votes = Counter(voters)
    value = max(reversed(URGENCY_VALUES), key=lambda u: votes[u])
    return {"value": value, "confidence": round(votes[value] / len(voters), 2), "votes": dict(votes),
            "neighbours_used": len(voters), "match": "same" if same else "similar"}


async def urgency_for(text: str, store: VectorStore, decider: Any | None = None) -> tuple[dict[str, Any], str | None]:
    """Stated deadline first, then the vector vote, then the default. A search failure never blocks classification."""
    stated = infer_urgency(text)
    vote, error = None, None
    try:
        hits = await store.search("requests", text, k=NEIGHBOURS)
        # Live requests carry tags this app assigned, so only SinceAI's labelled rows vote.
        labelled = [(h.doc.get("urgency"), h.score) for h in hits if h.doc.get("source") != "live"]
        name = store.embedder.name  # read after the search: it can fall back to local embeddings
        vote = vote_urgency(labelled, DUPLICATE_THRESHOLD[name], SIMILAR_THRESHOLD[name])
    except Exception as exc:
        log.warning("Vector search failed during classification: %s", exc)
        error = str(exc)[:200]
    if stated["source"] == "inferred":
        return {"value": stated["value"], "source": "stated_in_request", "evidence": stated["evidence"], "vector_vote": vote}, error
    if decider is not None and decider.enabled("urgency"):
        try:
            hint = await jev_urgency(decider, text)
            if hint:
                return {**hint, "vector_vote": vote}, error
        except Exception as exc:  # Jev is never required
            log.warning("Jev urgency failed during classification: %s", exc)
    if vote:
        return {"source": "vector_vote", "evidence": None, **vote}, error
    return {"value": "normal", "source": "default", "evidence": None, "vector_vote": None}, error


def tags_for_intent(intent: dict[str, Any], matched_by: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """The tags that follow from an intent, however it was extracted. Same rules as the Ask flow, so the answers agree."""
    C = cat.CATALOG
    filters = intent.get("filters") or {}
    governed = [m for m in intent.get("measures") or [] if m in C["measures"] and C["measures"][m]["certified"]]
    matched_by = matched_by or {}

    candidates = rank_candidates(intent, C)
    availability = data_availability(intent, C)
    result = decide(candidates, availability, intent, C)

    domains = Counter(C["measures"][m]["domain"] for m in governed)
    model = availability.get("best_model")
    if result.target_model_id and (not model or model["id"] != result.target_model_id):
        target = cat.model_by_id(result.target_model_id)
        if target:
            model = {"id": target["id"], "name": target["name"], "workspace": target["workspace"], "platform": target["platform"],
                     "endorsement": target["endorsement"], "refresh_status": target["refresh_status"],
                     "measures_served": sorted(set(governed) & set(target["measures"]))}

    exists, status = REPORT_STATUS[result.decision.value]
    c = result.candidate
    # A closest report is only worth naming when it is the one the answer refers to.
    report = None
    if c and status != "none":
        report = {"id": c.asset_id, "name": c.name, "platform": c.platform, "owner": (cat.asset_by_id(c.asset_id) or {}).get("owner"),
                  "coverage": c.coverage, "governance": c.governance}
    market = ([C["markets"][m]["name"] for m in filters.get("market", []) if m in C["markets"]] + list(filters.get("region", []))
              + list(intent.get("other_markets") or []))

    tags = {
        "domain": domains.most_common(1)[0][0] if domains else None,
        "market": market or (["Global"] if intent.get("scope_global") else []),
        "product": intent_products(intent, C),
        "breakdown": [C["dimensions"][d]["name"] for d in intent.get("dimensions") or [] if d in C["dimensions"]],
        "governed_kpis": [{"id": m, "kpi_id": C["measures"][m].get("kpi_id"), "name": C["measures"][m]["name"],
                           "domain": C["measures"][m]["domain"], **matched_by.get(m, {})} for m in governed],
        "not_available": list(intent.get("unmatched_terms") or []),
        "semantic_model": None if not model else {
            "id": model["id"], "name": model["name"], "workspace": model["workspace"], "platform": model["platform"],
            "endorsement": model["endorsement"], "refresh_status": model["refresh_status"],
            "serves_all_kpis": set(model["measures_served"]) >= set(governed),
        },
        "existing_report": exists,
        "existing_report_detail": {"status": status, "decision": result.decision.value, "report": report},
    }
    steps = analysis_steps(intent, tags, candidates, result)
    return {**tags, "recommendation": recommendation(result, steps), "steps": steps}


async def classify_request(text: str, store: VectorStore, decider: Any | None = None) -> dict[str, Any]:
    C = cat.CATALOG
    low = text.lower()
    urgency, retrieval_error = await urgency_for(text, store, decider)

    matched = match_measures(text)
    matched_by: dict[str, dict[str, Any]] = {m: {"matched_by": "keyword"} for m in matched}
    if not matched and decider is not None and decider.enabled("kpis") and text.isascii():
        try:
            found = await jev_match(decider, text)
            if not found["unsure"]:
                matched_by = {m: {"matched_by": "jev"} for m in found["measures"]}
        except Exception as exc:  # Jev is never required
            log.warning("Jev KPI match failed during classification: %s", exc)
    if not matched_by:
        try:
            for s in await suggest_kpis(store, text):
                matched_by[s["measure_id"]] = {"matched_by": "vector", "similarity": s["similarity"]}
        except Exception as exc:
            log.warning("KPI vector search failed during classification: %s", exc)
            retrieval_error = retrieval_error or str(exc)[:200]

    intent = {"question": text, "measures": [m for m in matched_by if C["measures"][m]["certified"]],
              "dimensions": match_dimensions(text), "grain": "month", "filters": match_filters(text),
              "other_markets": other_markets(text), "scope_global": "global" in low, "migration": {"from": "Tableau"} if "tableau" in low else None,
              "unmatched_terms": [t for t in OUT_OF_SCOPE if t in low]}

    return {
        "request": text,
        "urgency": urgency,
        **tags_for_intent(intent, matched_by),
        "retrieval": {"embedder": store.embedder.name, "model": store.embedder.model, "search": store.backend.get("requests", "memory"),
                      **({"error": retrieval_error} if retrieval_error else {})},
    }
