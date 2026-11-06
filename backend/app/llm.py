"""Model access shared by the agents.

``LLM`` wraps the OpenAI API (GPT-6 family by default) with three call styles:
plain text, JSON output, and a tool-calling loop. When no API key is set the
provider is "mock": ``enabled`` is False and every agent uses its rule-based
path instead, so the whole flow still runs offline.

The model only ever receives the user's words and catalog metadata (names,
definitions, table and column names, row counts), never raw production data.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Callable

from .settings import settings

log = logging.getLogger(__name__)


@dataclass
class Tool:
    """A function the model may call. ``fn`` takes keyword arguments and returns a JSON-able dict."""

    name: str
    description: str
    parameters: dict[str, Any]
    fn: Callable[..., dict[str, Any]]

    def schema(self) -> dict[str, Any]:
        return {"type": "function", "function": {"name": self.name, "description": self.description, "parameters": self.parameters}}

    def call(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            return self.fn(**args)
        except Exception as exc:  # report tool errors back to the model instead of crashing
            return {"error": f"{type(exc).__name__}: {exc}"}


def parse_json(text: str | None) -> dict[str, Any]:
    """Parse a JSON object from model output, tolerating code fences or leading prose."""
    if not text:
        raise ValueError("empty model response")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise ValueError("model response contains no JSON object")
        return json.loads(match.group(0))


def summarize(result: dict[str, Any], limit: int = 220) -> str:
    text = json.dumps(result, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[: limit - 1] + "…"


class LLM:
    def __init__(self, client: Any | None = None, provider: str | None = None) -> None:
        self.provider = provider or settings.llm_provider
        self.client = client
        if self.provider == "openai" and self.client is None:
            from openai import AsyncOpenAI

            self.client = AsyncOpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)

    @property
    def enabled(self) -> bool:
        return self.provider == "openai" and self.client is not None

    @property
    def name(self) -> str:
        return self.provider

    def model(self, role: str) -> str:
        return settings.model_reasoning if role == "reasoning" else settings.model_fast

    async def text(self, role: str, system: str, user: str) -> str:
        resp = await self.client.chat.completions.create(
            model=self.model(role), messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
        return resp.choices[0].message.content or ""

    async def json(self, role: str, system: str, user: str) -> dict[str, Any]:
        resp = await self.client.chat.completions.create(
            model=self.model(role),
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={"type": "json_object"},
        )
        return parse_json(resp.choices[0].message.content)

    async def tool_loop(self, role: str, system: str, user: str, tools: list[Tool],
                        on_tool: Callable[[str, dict[str, Any], dict[str, Any]], None], max_turns: int = 8) -> dict[str, Any]:
        """Let the model call tools until it answers with a JSON object."""
        by_name = {t.name: t for t in tools}
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        for _ in range(max_turns):
            resp = await self.client.chat.completions.create(
                model=self.model(role), messages=messages, tools=[t.schema() for t in tools], tool_choice="auto")
            msg = resp.choices[0].message
            calls = list(msg.tool_calls or [])
            if not calls:
                return parse_json(msg.content)
            messages.append({"role": "assistant", "content": msg.content or "",
                             "tool_calls": [{"id": c.id, "type": "function",
                                             "function": {"name": c.function.name, "arguments": c.function.arguments}} for c in calls]})
            for c in calls:
                try:
                    args = json.loads(c.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                tool = by_name.get(c.function.name)
                result = tool.call(args) if tool else {"error": f"Unknown tool '{c.function.name}'"}
                on_tool(c.function.name, args, result)
                messages.append({"role": "tool", "tool_call_id": c.id,
                                 "content": json.dumps(result, ensure_ascii=False, default=str)[:8000]})
        raise RuntimeError(f"agent did not finish within {max_turns} turns")


EXPLAIN_SYSTEM = """You explain an analytics decision to a non-technical plant employee in 2-3 short sentences.
Name the report in **bold**. Say what will happen next. Plain language, no jargon, no dashes as punctuation."""


async def explain(llm: LLM, payload: dict[str, Any]) -> str:
    """Plain-language explanation of the decision. Falls back to a template."""
    from .agents.templates import decision_text

    if llm.enabled:
        try:
            return await llm.text("fast", EXPLAIN_SYSTEM, json.dumps(payload, ensure_ascii=False, default=str))
        except Exception as exc:
            log.warning("explain failed, using template: %s", exc)
    return decision_text(payload)


def get_llm() -> LLM:
    return LLM()
