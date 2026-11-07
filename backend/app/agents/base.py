from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

from ..llm import LLM, summarize, usage_scope, usage_total


@dataclass
class Step:
    kind: str            # "tool", "model", "rule", "check" or "note"
    name: str
    detail: str = ""
    ok: bool = True


@dataclass
class AgentRun:
    agent: str
    mode: str            # "jev", "llm" or "rules"
    model: str
    steps: list[Step] = field(default_factory=list)
    output: Any = None
    ms: int = 0
    fallback_reason: str | None = None
    usage: dict[str, Any] | None = None

    def trace(self) -> dict[str, Any]:
        """What the UI and the audit log show (no full output)."""
        return {"agent": self.agent, "mode": self.mode, "model": self.model, "ms": self.ms,
                "fallback_reason": self.fallback_reason, "usage": self.usage, "steps": [asdict(s) for s in self.steps]}


class Agent:
    name = "agent"
    title = "Agent"
    role = "fast"        # "fast" or "reasoning" model

    jev_phase: str | None = None  # the phase in JEV_PHASES that lets Jev answer for this agent

    def __init__(self, llm: LLM, decider: Any | None = None) -> None:
        self.llm = llm
        self.decider = decider

    def jev_on(self, phase: str | None = None) -> bool:
        return self.decider is not None and self.decider.enabled(phase or self.jev_phase)

    def needs_no_model(self, ctx: dict[str, Any]) -> bool:
        """True when the answer is already known, so no model call is worth paying for."""
        return False

    async def prepare(self, ctx: dict[str, Any], steps: list[Step]) -> None:
        """Runs before the agent answers, whichever path answers."""

    async def run_jev(self, ctx: dict[str, Any], steps: list[Step]) -> Any | None:
        """The agent's answer from Jev, or None when Jev is unsure."""
        return None

    async def run(self, ctx: dict[str, Any]) -> AgentRun:
        start = time.perf_counter()
        steps: list[Step] = []
        mode, model, fallback, output = "rules", "rules (offline)", None, None
        known = self.needs_no_model(ctx)
        with usage_scope() as used:
            if not known:
                try:
                    await self.prepare(ctx, steps)
                except Exception as exc:
                    steps.append(Step("note", "Preparation step failed, continuing without it", f"{type(exc).__name__}: {exc}"[:300], ok=False))
            if not known and self.jev_on():
                try:
                    output = await self.run_jev(ctx, steps)
                except Exception as exc:  # any failure falls through: Jev is never required
                    steps.append(Step("note", "Jev failed, using the next option", f"{type(exc).__name__}: {exc}"[:300], ok=False))
            if output is not None:
                mode, model = "jev", self.decider.model
            elif self.llm.enabled and not known:
                try:
                    output = await self.run_llm(ctx, steps)
                    mode, model = "llm", self.llm.model(self.role)
                except Exception as exc:
                    fallback = f"{type(exc).__name__}: {exc}"[:300]
                    steps.append(Step("note", "Model step failed, switched to rules", fallback, ok=False))
                    output = await self.run_rules(ctx, steps)
            else:
                output = await self.run_rules(ctx, steps)
        return AgentRun(self.title, mode, model, steps, output, int((time.perf_counter() - start) * 1000), fallback, usage_total(used))

    async def run_llm(self, ctx: dict[str, Any], steps: list[Step]) -> Any:  # pragma: no cover - overridden
        raise NotImplementedError

    async def run_rules(self, ctx: dict[str, Any], steps: list[Step]) -> Any:  # pragma: no cover - overridden
        raise NotImplementedError

    @staticmethod
    def tool_recorder(steps: list[Step]):
        def record(name: str, args: dict[str, Any], result: dict[str, Any]) -> None:
            arg_text = ", ".join(f"{k}={v}" for k, v in args.items())
            steps.append(Step("tool", f"{name}({arg_text})", summarize(result), ok="error" not in result))
        return record
