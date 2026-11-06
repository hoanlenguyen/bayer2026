"""Builds the Estate Explorer graph ("molecular view") from the live catalog.

Entities: reports, measures, datasets, owners (people and data teams) and
departments. Edges: usage, lineage, ownership, metric conflicts and overlaps
between reports. Status, trust and flags reuse the governance scoring in
decision.py, so the graph and the decision always agree.
"""
from __future__ import annotations

import re
from datetime import date
from itertools import combinations
from typing import Any

from . import catalog as cat
from .decision import THRESHOLDS, freshness, governance

DEPT_ID = lambda name: "dom_" + re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")  # noqa: E731
PERSON_ID = lambda name: "p_" + re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")  # noqa: E731


def _initials(name: str) -> str:
    parts = [p for p in re.split(r"[\s.]+", name) if p and p[0].isalpha()]
    return "".join(p[0] for p in parts[:2]).upper() or "?"


def _asset_status(a: dict[str, Any], gov: float, today: date) -> str:
    if a.get("conflicts"):
        return "conflict"
    if a.get("owner_status") != "active":
        return "orphaned"
    reviewed = a.get("last_review")
    if a.get("refresh_age_hours", 0) > 7 * 24 or (reviewed and (today - date.fromisoformat(reviewed)).days > THRESHOLDS["review_max_days"]):
        return "stale"
    return "certified" if a.get("certified") else "uncertified"


def build_graph(today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    C = cat.CATALOG
    entities: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, str]] = []

    def edge(s: str, rel: str, t: str) -> None:
        if s in entities and t in entities:
            edges.append({"s": s, "rel": rel, "t": t})

    # Departments
    for dept in sorted(set(cat.DATASET_DEPARTMENT.values())):
        did = DEPT_ID(dept)
        entities[did] = {"id": did, "uid": did, "type": "domain", "name": dept, "status": "active", "trust": 1.0,
                         "updated": today.isoformat(), "summary": f"{dept} department at the plant.",
                         "props": {"Datasets": str(sum(1 for d in cat.DATASET_DEPARTMENT.values() if d == dept))}, "flags": []}

    # Measures
    for mid, m in C["measures"].items():
        entities[mid] = {
            "id": mid, "uid": f"msr_{mid}", "type": "metric", "name": m["name"],
            "status": "certified" if m["certified"] else "draft", "trust": 0.95 if m["certified"] else 0.5,
            "updated": today.isoformat(), "summary": m["definition"],
            "props": {"Measure ID": mid, "Formula": m["expression"], "Unit": m["unit"], "Default grain": m["default_grain"],
                      "Source dataset": m["dataset"]},
            "flags": [] if m["certified"] else [{"sev": "warn", "title": "Not certified", "text": "This measure has no approved definition."}],
        }

    # Datasets and their owning teams
    for dsid, d in C["datasets"].items():
        tests_ok = d["tests_passed"] == d["tests_total"]
        fresh = freshness(d["refresh_age_hours"], "day")
        flags = []
        if not tests_ok:
            flags.append({"sev": "warn", "title": "Quality test failing",
                          "text": f"{d['tests_total'] - d['tests_passed']} of {d['tests_total']} tests fail."})
        if fresh < 1:
            flags.append({"sev": "warn", "title": "Older than a day", "text": f"Last refreshed {d['refresh_age_hours']} h ago."})
        entities[dsid] = {
            "id": dsid, "uid": f"tbl_{dsid}", "type": "dataset", "name": dsid,
            "status": "certified" if tests_ok else "uncertified",
            "trust": round(0.6 * (d["tests_passed"] / max(d["tests_total"], 1)) + 0.4 * fresh, 2),
            "updated": today.isoformat(), "summary": f"Source table {d['table']} with {d['rows']:,} rows.",
            "props": {"Table": d["table"], "Rows": f"{d['rows']:,}", "Refreshed": f"{d['refresh_age_hours']} h ago",
                      "Quality tests": f"{d['tests_passed']} / {d['tests_total']} passing", "Owner": d["owner"],
                      "Columns": ", ".join(d["columns"])},
            "flags": flags,
        }

    owners: dict[str, dict[str, Any]] = {}
    for d in C["datasets"].values():
        owners.setdefault(d["owner"], {"status": "active", "role": "Data team"})
    for a in C["assets"]:
        owners[a["owner"]] = {"status": "left" if a.get("owner_status") == "left" else "active", "role": "Report owner"}
    for name, info in owners.items():
        pid = PERSON_ID(name)
        entities[pid] = {"id": pid, "uid": pid, "type": "person", "name": name, "initials": _initials(name),
                         "status": info["status"], "trust": 1.0 if info["status"] == "active" else 0.0,
                         "updated": today.isoformat(), "summary": f"{info['role']}.", "props": {"Role": info["role"]},
                         "flags": [] if info["status"] == "active" else
                         [{"sev": "warn", "title": "Left the company", "text": "Assets still list this person as owner."}]}

    # Reports
    for a in C["assets"]:
        gov, checks = governance(a, today)
        flags = [{"sev": "bad", "title": f"Conflicting definition: {C['measures'].get(m, {}).get('name', m)}", "text": why}
                 for m, why in (a.get("conflicts") or {}).items()]
        flags += [{"sev": "warn", "title": f"Governance check failed: {c.label}", "text": f"Weight {c.weight:.2f} of the governance score."}
                  for c in checks if not c.passed and c.id != "definitions_match"]
        entities[a["id"]] = {
            "id": a["id"], "uid": a["id"], "type": "dashboard", "name": a["name"], "status": _asset_status(a, gov, today),
            "trust": gov, "updated": a.get("last_review") or today.isoformat(), "views": a.get("views_90d", 0),
            "summary": f"{a['workspace']}. {len(a['measures'])} measures, {a['grain']}ly grain." if a["grain"] != "day"
                       else f"{a['workspace']}. {len(a['measures'])} measures, daily grain.",
            "props": {"Workspace": a["workspace"], "Grain": a["grain"], "Views (90 days)": f"{a.get('views_90d', 0):,}",
                      "Refreshed": f"{a.get('refresh_age_hours')} h ago", "Last review": a.get("last_review") or "Never",
                      "Governance score": f"{gov:.2f}", "Owner": a["owner"],
                      "Backup owner": a.get("backup_owner") or "None"},
            "flags": flags,
        }

    # Edges
    for mid, m in C["measures"].items():
        edge(m["dataset"], "feeds", mid)
        dept = cat.DATASET_DEPARTMENT.get(m["dataset"])
        if dept:
            edge(mid, "belongs_to", DEPT_ID(dept))
    for dsid, d in C["datasets"].items():
        edge(PERSON_ID(d["owner"]), "owns", dsid)
    for r in C["relationships"]:
        s, t = r["from"].split(".")[0], r["to"].split(".")[0]
        if s != t:
            edge(s, "joins", t)
    for a in C["assets"]:
        for m in a["measures"]:
            edge(a["id"], "uses", m)
        for ds in a.get("datasets", []):
            edge(ds, "sources", a["id"])
        edge(PERSON_ID(a["owner"]), "owns", a["id"])
        for m in (a.get("conflicts") or {}):
            edge(a["id"], "conflicts_with", m)

    # Overlapping reports: shared measures relative to the smaller report.
    for a, b in combinations(C["assets"], 2):
        shared = set(a["measures"]) & set(b["measures"])
        if not shared or len(shared) / min(len(a["measures"]), len(b["measures"])) < 0.5:
            continue
        ga, gb = entities[a["id"]]["trust"], entities[b["id"]]["trust"]
        weak, strong = (a, b) if ga < gb else (b, a)
        if min(ga, gb) < THRESHOLDS["ungoverned_governance"] or entities[weak["id"]]["status"] in ("conflict", "orphaned"):
            edge(weak["id"], "duplicate_of", strong["id"])
            entities[weak["id"]]["flags"].append({"sev": "warn", "title": f"Overlaps {strong['name']}",
                                                  "text": "Poorly governed overlap. Candidate for merge or retirement."})
            entities[weak["id"]]["action"] = f"Merge into {strong['name']} or retire"
        else:
            edge(a["id"], "overlaps", b["id"])

    focus = next((a["id"] for a in C["assets"] if a.get("certified")), next(iter(entities)))
    return {"entities": list(entities.values()), "edges": edges, "focus": focus,
            "counts": {"reports": len(C["assets"]), "measures": len(C["measures"]), "datasets": len(C["datasets"])}}
