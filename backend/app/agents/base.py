from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

from ..llm import LLM, summarize


@dataclass
class Step:
    kind: str            # "tool", "model", "rule", "check" or "note"
    name: str
    detail: str = ""
    ok: bool = True


@dataclass
class AgentRun:
    agent: str
    mode: str            # "llm" or "rules"
    model: str
    steps: list[Step] = field(default_factory=list)
    output: Any = None
    ms: int = 0
    fallback_reason: str | None = None

    def trace(self) -> dict[str, Any]:
        """What the UI and the audit log show (no full output)."""
        return {"agent": self.agent, "mode": self.mode, "model": self.model, "ms": self.ms,
                "fallback_reason": self.fallback_reason, "steps": [asdict(s) for s in self.steps]}


class Agent:
    name = "agent"
    title = "Agent"
    role = "fast"        # "fast" or "reasoning" model

    def __init__(self, llm: LLM) -> None:
        self.llm = llm

    async def run(self, ctx: dict[str, Any]) -> AgentRun:
        start = time.perf_counter()
        steps: list[Step] = []
        mode, model, fallback = "rules", "rules (offline)", None
        if self.llm.enabled:
            try:
                output = await self.run_llm(ctx, steps)
                mode, model = "llm", self.llm.model(self.role)
            except Exception as exc:
                fallback = f"{type(exc).__name__}: {exc}"[:300]
                steps.append(Step("note", "Model step failed, switched to rules", fallback, ok=False))
                output = await self.run_rules(ctx, steps)
        else:
            output = await self.run_rules(ctx, steps)
        return AgentRun(self.title, mode, model, steps, output, int((time.perf_counter() - start) * 1000), fallback)

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
