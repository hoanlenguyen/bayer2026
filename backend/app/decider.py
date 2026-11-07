"""Jev (TypeSafe AI): a decision model for classification. It returns probabilities, never text.

Off unless TYPESAFE_API_KEY is set and JEV_PHASES names a phase. Jev only supplies facts; when it is unsure or fails,
the agent falls through to GPT and then to rules. Python still decides the recommendation.
"""
from __future__ import annotations

import logging
from typing import Any, Mapping

from .llm import record_usage
from .settings import settings

log = logging.getLogger(__name__)

PHASES = {"relevance", "kpis", "urgency"}
ALWAYS_ON = {"conversation"}  # the chat simulator exists to use Jev, so a key is enough. Ask stays under JEV_PHASES
JEV_PRICE = 0.042 / 1_000_000  # per input token; output is free (docs.typesafe.ai/models)

# How sure Jev must be before its answer is used. Change them here only.
JEV_THRESHOLDS = {
    "accept": 0.70,      # a message is usable
    "reject": 0.80,      # higher: a wrong rejection blocks a real user
    "yes": 0.70,         # a KPI, breakdown or migration is being asked for
    "no": 0.30,          # it is not. Anything between is unsure, and goes to GPT
    "raise_urgency": 0.80,
    "speak": 0.70,       # the chat simulator steps in
    "stay_quiet": 0.30,  # it does not. Anything between is unsure, and goes to GPT
}


def jev_cost(usage: dict[str, Any] | None) -> float:
    """What Jev charged for these calls, in dollars."""
    by_model = (usage or {}).get("by_model") or {}
    return sum(r["input_tokens"] for m, r in by_model.items() if m.startswith("jev")) * JEV_PRICE


class Decider:
    def __init__(self, client: Any | None = None, phases: set[str] | None = None, model: str | None = None,
                 timeout: float = 10.0) -> None:
        self.client = client
        self.phases = set(phases or ())
        self.model = model or settings.jev_model
        self.timeout = timeout

    def enabled(self, phase: str | None) -> bool:
        return self.client is not None and phase in self.phases

    async def decide(self, state: Any, questions: Mapping[str, Any]) -> Any:
        response = await self.client.system_one(state=state, questions=questions, model=self.model, timeout=self.timeout)
        usage = response.usage
        record_usage(response.model, usage.input_tokens, usage.output_tokens)
        return response


def get_decider() -> Decider:
    phases = settings.jev_phases & PHASES
    for unknown in sorted(settings.jev_phases - PHASES):
        log.warning("JEV_PHASES: unknown phase %s", unknown)
    if not settings.typesafe_api_key:
        if phases:
            log.warning("JEV_PHASES is set but TYPESAFE_API_KEY is not: Jev stays off.")
        return Decider()
    from typesafe_sdk import AsyncTypeSafeClient

    return Decider(AsyncTypeSafeClient(api_key=settings.typesafe_api_key), phases | ALWAYS_ON)
