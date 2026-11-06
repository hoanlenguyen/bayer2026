"""Plain-language templates used when no model is available."""
from __future__ import annotations

from typing import Any

from .. import catalog as cat


def _names(ids: list[str], kind: str) -> list[str]:
    src = cat.CATALOG["measures" if kind == "m" else "dimensions"]
    return [src[i]["name"].lower() for i in ids if i in src]


def decision_text(p: dict[str, Any]) -> str:
    d = p.get("decision", {})
    cand = d.get("candidate") or {}
    dec = d.get("decision")
    if dec == "reuse":
        return f"Good news: **{cand.get('name')}** already answers this with certified data, so nothing new needs to be built. {d.get('reason', '')}"
    if dec == "extend":
        if d.get("change_type") == "maintenance":
            return (f"**{cand.get('name')}** covers everything you asked for, but its data is too old for this decision. "
                    "I propose a maintenance change to its refresh schedule instead of a new report.")
        missing = _names(cand.get("measures_missing", []), "m") + _names(cand.get("dimensions_missing", []), "d")
        extra = " and a finer time grain" if not cand.get("grain_supported", True) else ""
        return (f"**{cand.get('name')}** covers most of this. I propose adding {' and '.join(missing) or 'the missing parts'}"
                f"{extra} to it instead of building a new report.")
    if dec == "create":
        return "Nothing governed in the catalog answers this yet, but the data exists. I drafted a new report built only from certified definitions."
    return "I couldn't find the data for this in the catalog. " + p.get("missing_text", "")
