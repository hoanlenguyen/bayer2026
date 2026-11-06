"""Agents for the processing flow.

Each agent has two paths that return the same output shape:
- ``run_llm``: the OpenAI model, with catalog tools where useful.
- ``run_rules``: deterministic rules, used offline and as a fallback.

Every run records its steps (tool calls, model calls, checks) so the UI can
show exactly what the agent did, and Python verifies what the agent proposes.
"""
from .base import AgentRun, Step
from .evidence import EvidenceAgent
from .intent import IntentAgent
from .spec import SpecAgent

__all__ = ["AgentRun", "Step", "IntentAgent", "EvidenceAgent", "SpecAgent"]
