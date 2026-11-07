"""Render an approved DashboardSpec into a Power BI Project (PBIP) folder.

Plain Python, no AI: the same spec always produces the same files.

Following RULE-001 (reuse shared semantic models), a new report is a *thin
report*: it connects to an existing shared semantic model instead of copying
data into a new one. So the output has a .pbip and a .Report folder, and the
report's definition.pbir points at the shared model by connection.

Status: skeleton. The layout follows the PBIP structure but has not been opened
in Power BI Desktop. Validate before relying on it.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

VISUAL_TYPES = {"card": "card", "bar": "clusteredBarChart", "line": "lineChart", "table": "tableEx"}


def slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_") or "Report"


def report_json(spec: dict[str, Any]) -> dict[str, Any]:
    sections = []
    for p_i, page in enumerate(spec["pages"]):
        containers = []
        for v_i, v in enumerate(page["visuals"]):
            col, row = v_i % 3, v_i // 3
            containers.append({
                "x": 20 + col * 420, "y": 20 + row * 240, "width": 400, "height": 120 if v["type"] == "card" else 220,
                "config": json.dumps({"name": f"v{v_i}", "singleVisual": {
                    "visualType": VISUAL_TYPES.get(v["type"], "tableEx"), "title": v["title"],
                    "measure": v["measure"], "by": v.get("by")}}),
            })
        sections.append({"name": f"page{p_i}", "displayName": page["name"], "ordinal": p_i, "visualContainers": containers})
    filters = [{"field": k, "values": v} for k, v in (spec.get("filters") or {}).items() if v]
    return {"config": json.dumps({"version": "5.43"}), "filters": json.dumps(filters), "sections": sections}


def render_pbip(spec: dict[str, Any], out_root: Path, run_key: str) -> dict[str, Any]:
    name = slug(spec["name"])
    root = out_root / run_key / name
    model = spec.get("semantic_model") or {}
    workspace = model.get("workspace") or "Shared"
    files: dict[str, str] = {
        f"{name}.pbip": json.dumps({"version": "1.0", "artifacts": [{"report": {"path": f"{name}.Report"}}],
                                     "settings": {"enableAutoRecovery": True}}, indent=2),
        f"{name}.Report/definition.pbir": json.dumps({"version": "4.0", "datasetReference": {"byConnection": {
            "connectionString": f"Data Source=powerbi://api.powerbi.com/v1.0/myorg/{workspace};Initial Catalog={model.get('name')}",
            "pbiModelDatabaseName": model.get("id"), "connectionType": "pbiServiceXmlaStyleLive"}}}, indent=2),
        f"{name}.Report/report.json": json.dumps(report_json(spec), indent=2),
        "measures.md": "\n".join([f"# Approved KPIs used by {spec['name']}", ""] + [
            f"- **{m['name']}** ({m['kpi_id']}, {m['unit']}): {m['definition']}" for m in spec["measures"]]) + "\n",
        "governance.json": json.dumps({k: spec.get(k) for k in (
            "name", "owner", "review_date", "decision_type", "change_type", "base_asset_id", "replaces",
            "rules_applied", "rationale", "approved_by", "approved_at")}, indent=2),
        "spec.json": json.dumps(spec, indent=2),
    }
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return {
        "folder": str(root.relative_to(out_root.parent)),
        "files": [{"path": rel, "bytes": len(c.encode())} for rel, c in sorted(files.items())],
        "preview": {"model": files[f"{name}.Report/definition.pbir"]},
        "thin_report_on": model.get("id"),
        "validated_in_power_bi": False,
    }
