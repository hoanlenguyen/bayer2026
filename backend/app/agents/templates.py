"""Plain-language templates used when no model is available."""
from __future__ import annotations

from typing import Any

from .. import catalog as cat


def decision_text(p: dict[str, Any]) -> str:
    d = p.get("decision", {})
    cand = d.get("candidate") or {}
    dec = d.get("decision")
    n_flags = len(d.get("flags") or [])
    tail = f" I also flagged {n_flags} overlapping report{'s' if n_flags != 1 else ''} to consolidate or retire." if n_flags else ""
    if dec == "reuse":
        return f"**{cand.get('name')}** ({cand.get('asset_id')}) matches these requirements in the imported metadata, so nothing new needs to be built.{tail}"
    if dec == "repair":
        return f"**{cand.get('name')}** ({cand.get('asset_id')}) covers your request and is well used, but it needs repair first. {d.get('reason', '')}{tail}"
    if dec == "consolidate":
        missing = [cat.CATALOG["measures"][m]["name"] for m in cand.get("measures_missing", []) if m in cat.CATALOG["measures"]]
        return (f"**{cand.get('name')}** covers most of this. I propose extending it with {', '.join(missing) or 'the missing KPIs'} "
                f"and folding overlapping reports into it.{tail}")
    if dec == "migrate":
        return f"Migration plan: {d.get('reason', '')}"
    if dec == "new_build":
        model = cat.model_by_id(d.get("target_model_id")) or {}
        return (f"No existing report is both close enough and well governed. I prepared a proposal using the catalogued KPIs and suggested model "
                f"**{model.get('name', d.get('target_model_id'))}**. Generation depends on a separate executable binding contract.{tail}")
    terms = ", ".join((d.get("availability") or {}).get("missing_terms") or [])
    return ("This dashboard request cannot be fulfilled as specified"
            + (f": it needs {terms}" if terms else "") +
            ". The data pack holds aggregated commercial and operational data only, with no patient or prescriber-level data.")
