import json

from app import catalog as cat
from app.decision import data_availability, decide, rank_candidates


def preset_intent(preset_id: str) -> dict:
    p = cat.preset_by_id(preset_id)
    return {"measures": list(p["measures"]), "dimensions": list(p["dimensions"]), "decision": p["decision"],
            "filters": {k: list(v) for k, v in (p.get("filters") or {}).items()}, "scope_global": p.get("scope_global", False),
            "migration": p.get("migration"), "unmatched_terms": list(p.get("requested_terms", [])), "grain": "month",
            "preset_id": preset_id}


def plan(preset_id: str):
    intent = preset_intent(preset_id)
    avail = data_availability(intent, cat.CATALOG)
    result = decide(rank_candidates(intent, cat.CATALOG), avail, intent, cat.CATALOG)
    d = result.to_dict()
    d["availability"] = avail
    return intent, d


def sse(resp):
    return [json.loads(l[6:]) for b in resp.text.split("\n\n") for l in b.splitlines() if l.startswith("data: ")]


def stage(evs, name):
    return next((e for e in evs if e["type"] == "stage" and e["stage"] == name and e["status"] in ("done", "waiting")), None)
