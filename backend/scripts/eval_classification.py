"""Compares rules, GPT and Jev on the same labelled requests: accuracy, tokens, cost and speed per phase.

    python scripts/eval_classification.py                     # rules only: free, offline
    python scripts/eval_classification.py --modes rules,gpt,jev   # needs OPENAI_API_KEY and TYPESAFE_API_KEY; spends credits

It changes nothing. A phase should go in JEV_PHASES only if it passes the gates printed at the end.
"jev" means the real setup: Jev first, GPT when Jev is unsure, then rules.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import catalog as cat  # noqa: E402
from app.agents import IntentAgent, RelevanceAgent  # noqa: E402
from app.decider import Decider, get_decider  # noqa: E402
from app.llm import LLM, get_llm, merge_usage  # noqa: E402
from app.settings import settings  # noqa: E402

JEV_PRICE = 0.042 / 1_000_000  # per input token; output is free (docs.typesafe.ai/models)
DATA = Path(__file__).with_name("eval_messages.json")
# What the real flow knows when a follow-up question is open.
PENDING = {"Which products and markets should it cover?": "scope", "What decision will you make with it, and how often?": "decision",
           "When do you need this?": "urgency"}


def agents(mode: str, jev_client: Any = None, llm: LLM | None = None) -> tuple[LLM, Decider]:
    if mode == "rules":
        return LLM(provider="mock"), Decider()
    if mode == "gpt":
        return llm or get_llm(), Decider()
    return llm or get_llm(), Decider(jev_client, {"relevance", "kpis", "urgency"})


class Tally:
    def __init__(self) -> None:
        self.usage: dict[str, Any] | None = None
        self.paths: dict[str, int] = {}
        self.ms = 0
        self.n = 0

    def add(self, run: Any) -> None:
        self.n += 1
        self.ms += run.ms
        self.paths[run.mode] = self.paths.get(run.mode, 0) + 1
        if run.usage:
            self.usage = merge_usage(self.usage, run.usage)

    def line(self) -> str:
        u = self.usage or {"input_tokens": 0, "output_tokens": 0, "calls": 0, "by_model": {}}
        jev = sum(r["input_tokens"] for m, r in u["by_model"].items() if m.startswith("jev"))
        tokens = u["input_tokens"] + u["output_tokens"]
        return (f"{tokens / max(self.n, 1):,.0f} tokens each ({u['calls'] / max(self.n, 1):.1f} calls), "
                f"Jev cost ${jev * JEV_PRICE:.6f}, {self.ms / max(self.n, 1):,.0f} ms each, answered by {self.paths}")


def tokens_each(t: Tally) -> float:
    u = t.usage or {"input_tokens": 0, "output_tokens": 0}
    return (u["input_tokens"] + u["output_tokens"]) / max(t.n, 1)


async def relevance(mode: str, messages: list[dict[str, Any]], llm: LLM, decider: Decider) -> dict[str, Any]:
    agent, tally, right = RelevanceAgent(llm, decider), Tally(), 0
    wrong_rejects, wrong_accepts = [], []
    for m in messages:
        run = await agent.run({"text": m["text"], "question": m.get("question"), "suggestions": m.get("suggestions") or [],
                               "pending": PENDING.get(m.get("question")), "request": "Show net sales" if m.get("question") else None})
        tally.add(run)
        got = run.output["verdict"]
        right += got == m["verdict"]
        if m["verdict"] == "accept" and got != "accept":
            wrong_rejects.append(m["text"])
        if m["verdict"] != "accept" and got == "accept":
            wrong_accepts.append(m["text"])
    return {"accuracy": right / len(messages), "wrong_rejects": wrong_rejects, "wrong_accepts": wrong_accepts, "tally": tally}


def _ctx(text: str) -> dict[str, Any]:
    # asked=2 means no follow-up can be asked, so the extraction itself is what gets compared.
    return {"transcript": [{"role": "user", "content": text}], "asked": 2, "preset": None, "kpi_suggestions": [],
            "intent": {"question": text, "measures": [], "dimensions": [], "grain": None, "filters": {}, "unmatched_terms": [], "decision": None}}


async def kpis(mode: str, llm: LLM, decider: Decider) -> dict[str, Any]:
    agent, tally = IntentAgent(llm, decider), Tally()
    labelled = [p for p in cat.PRESETS if p.get("measures")]
    exact, found, wanted, returned, misses = 0, 0, 0, 0, []
    for p in labelled:
        run = await agent.run(_ctx(p["prompt"]))
        tally.add(run)
        got, want = set(run.output["intent"]["measures"]), set(p["measures"])
        exact += got == want
        found += len(got & want)
        wanted += len(want)
        returned += len(got)
        if got != want:
            misses.append(f"{p['id']}: missing {sorted(want - got) or '-'}, extra {sorted(got - want) or '-'}")
    return {"exact": exact / len(labelled), "recall": found / max(wanted, 1), "precision": found / max(returned, 1), "misses": misses, "tally": tally}


async def urgency(mode: str, messages: list[dict[str, Any]], llm: LLM, decider: Decider) -> dict[str, Any]:
    agent, tally, right, raises = IntentAgent(llm, decider), Tally(), 0, []
    labelled = [m for m in messages if m.get("urgency")]
    for m in labelled:
        run = await agent.run(_ctx(m["text"]))
        tally.add(run)
        got = (run.output["intent"].get("urgency") or {}).get("value", "normal")
        right += got == m["urgency"]
        if m["urgency"] == "normal" and got != "normal":
            raises.append(m["text"])
    return {"accuracy": right / max(len(labelled), 1), "false_raises": raises, "tally": tally}


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--modes", default="rules", help="comma separated: rules, gpt, jev")
    modes = [m.strip() for m in parser.parse_args().modes.split(",") if m.strip()]
    if "gpt" in modes or "jev" in modes:
        if not settings.openai_api_key:
            sys.exit("OPENAI_API_KEY is not set.")
    jev_client = None
    if "jev" in modes:
        if not settings.typesafe_api_key:
            sys.exit("TYPESAFE_API_KEY is not set.")
        from typesafe_sdk import AsyncTypeSafeClient

        jev_client = AsyncTypeSafeClient(api_key=settings.typesafe_api_key)
    messages = json.loads(DATA.read_text(encoding="utf-8"))["messages"]
    results: dict[str, dict[str, Any]] = {}
    started = time.perf_counter()
    for mode in modes:
        llm, decider = agents(mode, jev_client)
        results[mode] = {"relevance": await relevance(mode, messages, llm, decider), "kpis": await kpis(mode, llm, decider),
                         "urgency": await urgency(mode, messages, llm, decider)}
        r = results[mode]
        print(f"\n=== {mode}")
        print(f"Relevance  {r['relevance']['accuracy']:.0%} right on {len(messages)} | {r['relevance']['tally'].line()}")
        print(f"  wrongly rejected ({len(r['relevance']['wrong_rejects'])}): {r['relevance']['wrong_rejects']}")
        print(f"  wrongly accepted ({len(r['relevance']['wrong_accepts'])}): {r['relevance']['wrong_accepts']}")
        print(f"KPIs       exact {r['kpis']['exact']:.0%}, recall {r['kpis']['recall']:.0%}, precision {r['kpis']['precision']:.0%} | {r['kpis']['tally'].line()}")
        for miss in r["kpis"]["misses"]:
            print(f"  {miss}")
        print(f"Urgency    {r['urgency']['accuracy']:.0%} right | {r['urgency']['tally'].line()}")
        print(f"  raised without a deadline ({len(r['urgency']['false_raises'])}): {r['urgency']['false_raises']}")
    print(f"\nFinished in {time.perf_counter() - started:.0f} s.")

    if "gpt" in results and "jev" in results:
        g, j = results["gpt"], results["jev"]
        print("\n=== Gates: turn a phase on only if all of its lines say PASS")
        gates = {
            "relevance": [("accuracy at least GPT's", j["relevance"]["accuracy"] >= g["relevance"]["accuracy"]),
                          ("no business request wrongly rejected", not j["relevance"]["wrong_rejects"]),
                          ("fewer tokens per message", tokens_each(j["relevance"]["tally"]) < tokens_each(g["relevance"]["tally"]))],
            "kpis": [("exact match at least GPT's", j["kpis"]["exact"] >= g["kpis"]["exact"]),
                     ("recall at least GPT's", j["kpis"]["recall"] >= g["kpis"]["recall"]),
                     ("fewer tokens per request", tokens_each(j["kpis"]["tally"]) < tokens_each(g["kpis"]["tally"]))],
            "urgency": [("accuracy at least GPT's", j["urgency"]["accuracy"] >= g["urgency"]["accuracy"]),
                        ("no more false raises than GPT", len(j["urgency"]["false_raises"]) <= len(g["urgency"]["false_raises"]))],
        }
        for phase, checks in gates.items():
            print(f"{phase}: {'PASS' if all(ok for _, ok in checks) else 'FAIL'}")
            for name, ok in checks:
                print(f"  {'PASS' if ok else 'FAIL'}  {name}")
        print("\nUrgency runs on the Intent path, so it shares tokens with KPIs when both are on.")


if __name__ == "__main__":
    asyncio.run(main())
