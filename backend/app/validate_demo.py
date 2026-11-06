"""Reproduce the entire offline generation proof: python -m app.validate_demo."""
import argparse
import asyncio
import hashlib
import json
from dataclasses import replace
from pathlib import Path

from . import catalog as cat
from . import pipeline as flow
from .governance import actor_for, source_digest
from .llm import LLM
from .pbip import render_pbip, RENDERER_VERSION
from .settings import settings
from .store import MemoryStore
from .workbook_source import metadata


def stage(events, name):
    return next(e for e in reversed(events) if e.get("stage") == name and e["status"] in ("done", "waiting"))


async def run(destination: Path):
    destination.mkdir(parents=True, exist_ok=True)
    flow.settings = replace(settings, output_dir=destination, stage_delay=0)
    cat.reset_catalog()
    store = MemoryStore()
    await cat.init(store)
    pipeline = flow.Pipeline(store, LLM(provider="mock"))
    requester, reviewer = actor_for("OWN-008"), actor_for("OWN-022")
    source = metadata()
    result = {"mode": "offline_rules", "store": "isolated_memory", "renderer": RENDERER_VERSION,
              "source_sha256": source["sha256"], "source_snapshot": source_digest(),
              "checks": [], "requests": [], "external_validation": {
                  "power_bi_rendering": "not_run", "power_bi_numeric_reconciliation": "not_run", "publication": "not_run",
                  "live_model_calls": "not_run", "production_sso": "not_configured"}}
    for preset in ("demo_portfolio_sales_units", "demo_nubeqa_sales_units", "req_finance_gtn", "scn_repair_xarelto_mx", "demo_reuse_brazil"):
        events = [e async for e in pipeline.chat(None, "", preset, requester)]
        cid = events[0]["id"]
        decision = stage(events, "decision")["data"]
        record = {"preset": preset, "request_id": cid, "decision": decision["decision"], "reason": decision["reason"]}
        if decision["decision"] == "reuse":
            result["requests"].append(record)
            continue
        approval = stage(events, "approval")["data"]
        record.update(spec_hash=approval["spec_hash"], source_hash=approval["source_hash"])
        reviewed = [e async for e in pipeline.approve(cid, True, reviewer, approval["spec_hash"])]
        assert not any(e["type"] == "error" for e in reviewed), reviewed
        output = stage(reviewed, "render")["data"]
        record.update(state=output["artifact_state"], output=output.get("folder"), blockers=output.get("blockers", []))
        if output.get("validation"):
            record["validation"] = output["validation"]
            spec = (await store.get(cid))["plan"]["spec"]
            repeat = render_pbip(spec, destination / "repeat", approval["spec_id"])
            same = repeat["validation"]["artifact_hashes"] == output["validation"]["artifact_hashes"]
            assert same
            result["checks"].append({"check": "deterministic_artifact_repeat", "preset": preset, "passed": same})
            retried = [e async for e in pipeline.approve(cid, True, reviewer, approval["spec_hash"])]
            assert stage(retried, "render")["data"] == output
        result["requests"].append(record)
    # Equivalent new request reuses an existing pending artifact, not a certified catalogue entry.
    events = [e async for e in pipeline.chat(None, "", "demo_portfolio_sales_units", requester)]
    approval = stage(events, "approval")["data"]
    reviewed = [e async for e in pipeline.approve(events[0]["id"], True, reviewer, approval["spec_hash"])]
    assert len(cat.CATALOG["assets"]) == 362
    assert stage(reviewed, "render")["data"]["folder"] == result["requests"][0]["output"]
    result["checks"].append({"check": "equivalent_request_does_not_duplicate_asset", "passed": True})
    result["application_sha256"] = hashlib.sha256(b"".join(p.read_bytes() for p in sorted(Path(__file__).parent.rglob("*.py")))).hexdigest()
    target = destination / "acceptance-results.json"
    target.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"report": str(target), "requests": len(result["requests"]), "generated_assets": 2,
                      "automated_checks": "passed", "power_bi_runtime": "not_run"}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=settings.output_dir / "acceptance")
    args = parser.parse_args()
    asyncio.run(run(args.output.resolve()))
