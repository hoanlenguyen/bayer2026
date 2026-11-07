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
from .assessment import REPORT_STATUS, tags_for_intent  # noqa: F401  (re-exported for callers)
from .geo import other_markets
from .triage import URGENCY_VALUES, infer_urgency
from .vectors import DUPLICATE_THRESHOLD, SIMILAR_THRESHOLD, VectorStore, suggest_kpis

log = logging.getLogger(__name__)

NEIGHBOURS = 30  # the most repeated request text appears 22 times
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


async def classify_request(text: str, store: VectorStore, decider: Any | None = None) -> dict[str, Any]:
    found = await read_request(text, store, decider)
    return {
        "request": text,
        "urgency": found["urgency"],
        **tags_for_intent(found["intent"], found["matched_by"]),
        "retrieval": found["retrieval"],
    }


async def read_request(text: str, store: VectorStore, decider: Any | None = None) -> dict[str, Any]:
    """The intent behind a request, from its words and the vector store. No chat model; nothing saved."""
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

    intent["urgency"] = {k: urgency.get(k) for k in ("value", "source", "evidence")}
    return {
        "intent": intent, "matched_by": matched_by, "urgency": urgency,
        "retrieval": {"embedder": store.embedder.name, "model": store.embedder.model, "search": store.backend.get("requests", "memory"),
                      **({"error": retrieval_error} if retrieval_error else {})},
    }
