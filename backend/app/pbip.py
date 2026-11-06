"""Render an approved DashboardSpec into a Power BI Project (PBIP) folder.

Plain Python, no AI: the same spec always produces the same files, so the
output can be committed to Git and reviewed like code.

Status: skeleton. The folder layout follows the PBIP project structure
(.pbip, .Report, .SemanticModel with TMDL), but the files have not yet been
opened in Power BI Desktop. Validate before relying on them.
"""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

from .catalog import CATALOG


def slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_") or "Report"


def _lineage(*parts: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "/".join(parts)))


def _q(name: str) -> str:
    return f"'{name}'" if re.search(r"[^A-Za-z0-9_]", name) else name


def table_tmdl(table: str, spec: dict[str, Any]) -> str:
    ds = CATALOG["datasets"][table]
    schema, item = ds["table"].split(".", 1)
    lines = [f"table {table}", f"\tlineageTag: {_lineage(spec['name'], table)}", ""]
    for m in spec["measures"]:
        if m["dataset"] == table:
            lines += [f"\tmeasure {_q(m['name'])} = {m['expression']}",
                      f"\t\tlineageTag: {_lineage(spec['name'], table, m['id'])}",
                      f"\t\t/// {m['definition']}", ""]
    for col in spec["columns"].get(table, []):
        lines += [f"\tcolumn {col}", "\t\tdataType: string", f"\t\tsourceColumn: {col}",
                  f"\t\tlineageTag: {_lineage(spec['name'], table, col)}", "\t\tsummarizeBy: none", ""]
    lines += [f"\tpartition {table} = m", "\t\tmode: import",
              f"\t\tsource = Sql.Database(\"<fabric-sql-endpoint>\", \"<lakehouse>\"){{[Schema=\"{schema}\",Item=\"{item}\"]}}[Data]", ""]
    return "\n".join(lines)


def relationships_tmdl(spec: dict[str, Any]) -> str:
    out = []
    for i, r in enumerate(spec["relationships"]):
        out += [f"relationship rel_{i + 1}", f"\tfromColumn: {r['from']}", f"\ttoColumn: {r['to']}", ""]
    return "\n".join(out)


def report_json(spec: dict[str, Any]) -> dict[str, Any]:
    sections = []
    for p_i, page in enumerate(spec["pages"]):
        containers = []
        for v_i, v in enumerate(page["visuals"]):
            col, row = v_i % 3, v_i // 3
            containers.append({
                "x": 20 + col * 420, "y": 20 + row * 240, "width": 400, "height": 220 if v["type"] != "card" else 120,
                "config": json.dumps({"name": f"v{v_i}", "singleVisual": {"visualType": {"card": "card", "bar": "clusteredBarChart",
                                      "line": "lineChart", "table": "tableEx"}.get(v["type"], "tableEx"),
                                      "title": v["title"], "measure": v["measure"], "by": v.get("by")}}),
            })
        sections.append({"name": f"page{p_i}", "displayName": page["name"], "ordinal": p_i, "visualContainers": containers})
    return {"config": json.dumps({"version": "5.43"}), "sections": sections}


def render_pbip(spec: dict[str, Any], out_root: Path, run_key: str) -> dict[str, Any]:
    name = slug(spec["name"])
    root = out_root / run_key / name
    files: dict[str, str] = {
        f"{name}.pbip": json.dumps({"version": "1.0", "artifacts": [{"report": {"path": f"{name}.Report"}}],
                                     "settings": {"enableAutoRecovery": True}}, indent=2),
        f"{name}.Report/definition.pbir": json.dumps({"version": "4.0", "datasetReference": {"byPath": {"path": f"../{name}.SemanticModel"}}}, indent=2),
        f"{name}.Report/report.json": json.dumps(report_json(spec), indent=2),
        f"{name}.SemanticModel/definition.pbism": json.dumps({"version": "4.0", "settings": {}}, indent=2),
        f"{name}.SemanticModel/definition/model.tmdl": "model Model\n\tculture: en-US\n\n" + "".join(f"ref table {t}\n" for t in spec["entities"]),
        f"{name}.SemanticModel/definition/relationships.tmdl": relationships_tmdl(spec),
        "governance.json": json.dumps({k: spec[k] for k in ("name", "owner", "review_date", "decision", "base_asset_id",
                                                           "change_type", "rationale", "approved_by", "approved_at") if k in spec}, indent=2),
        "spec.json": json.dumps(spec, indent=2),
    }
    for t in spec["entities"]:
        files[f"{name}.SemanticModel/definition/tables/{t}.tmdl"] = table_tmdl(t, spec)

    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    return {
        "folder": str(root.relative_to(out_root.parent)),
        "files": [{"path": rel, "bytes": len(c.encode())} for rel, c in sorted(files.items())],
        "preview": {"model": files[f"{name}.SemanticModel/definition/tables/{spec['entities'][0]}.tmdl"]},
        "validated_in_power_bi": False,
    }
