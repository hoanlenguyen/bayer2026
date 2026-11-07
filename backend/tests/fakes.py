"""Test doubles: a scripted OpenAI client and an async wrapper around mongomock."""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any


def _message(content: str | None = None, tool_calls: list[tuple[str, dict]] | None = None):
    calls = [SimpleNamespace(id=f"call_{i}", function=SimpleNamespace(name=n, arguments=json.dumps(a)))
             for i, (n, a) in enumerate(tool_calls or [])]
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=calls or None))])


class ScriptedOpenAI:
    """Returns pre-scripted responses in order and records every request."""

    def __init__(self, script: list[dict[str, Any]]) -> None:
        self.script = list(script)
        self.requests: list[dict[str, Any]] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs: Any):
        self.requests.append(kwargs)
        if not self.script:
            raise RuntimeError("script exhausted")
        step = self.script.pop(0)
        if "tools" in step:
            reply = _message(tool_calls=step["tools"])
        else:
            reply = _message(content=json.dumps(step["json"]) if "json" in step else step["text"])
        if "usage" in step:
            reply.usage = SimpleNamespace(prompt_tokens=step["usage"][0], completion_tokens=step["usage"][1])
        return reply


class ScriptedJev:
    """Answers system_one from a script, as the real SDK's response type. A step that is an Exception is raised."""

    def __init__(self, script: list[Any], input_tokens: int = 100) -> None:
        self.script = list(script)
        self.input_tokens = input_tokens
        self.requests: list[dict[str, Any]] = []

    async def system_one(self, *, state: Any, questions: Any, model: str, timeout: float) -> Any:
        from typesafe_sdk import SystemOneResponse

        self.requests.append({"state": state, "questions": questions, "model": model})
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        answers = {}
        for name in questions:
            value = step[name] if isinstance(step, dict) and name in step else (step.get("*", 0.05) if isinstance(step, dict) else step)
            if isinstance(value, dict):
                top = max(value, key=value.get)
                answers[name] = {"type": "choice", "choice": top, "confidence": value[top], "probabilities": value}
            else:
                answers[name] = {"type": "noul", "noul": value}
        return SystemOneResponse.model_validate({"model": model, "answers": answers,
                                                 "usage": {"input_tokens": self.input_tokens, "output_tokens": 0}})


# ---------------------------------------------------------------- async mongomock
class _AsyncCursor:
    def __init__(self, cursor):
        self._cursor = cursor

    def sort(self, *args, **kwargs):
        self._cursor = self._cursor.sort(*args, **kwargs)
        return self

    def limit(self, n):
        self._cursor = self._cursor.limit(n)
        return self

    def __aiter__(self):
        self._it = iter(self._cursor)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


class _AsyncCollection:
    def __init__(self, col):
        self._col = col

    def find(self, *args, **kwargs):
        return _AsyncCursor(self._col.find(*args, **kwargs))

    def __getattr__(self, name):
        attr = getattr(self._col, name)

        async def call(*args, **kwargs):
            return attr(*args, **kwargs)
        return call


class AsyncMockDB:
    def __init__(self):
        import mongomock

        self._db = mongomock.MongoClient()["test_db"]

    def __getitem__(self, name):
        return _AsyncCollection(self._db[name])

    async def command(self, name):
        return {"ok": 1}
