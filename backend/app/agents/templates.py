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
        return f"Good news: **{cand.get('name')}** ({cand.get('asset_id')}) already answers this with approved KPIs, so nothing new needs to be built.{tail}"
    if dec == "repair":
        return f"**{cand.get('name')}** ({cand.get('asset_id')}) covers your request and is well used, so I recommend reusing it after a repair. {d.get('reason', '')}{tail}"
    if dec == "consolidate":
        missing = [cat.CATALOG["measures"][m]["name"] for m in cand.get("measures_missing", []) if m in cat.CATALOG["measures"]]
        return (f"**{cand.get('name')}** covers most of this. I recommend extending it with {', '.join(missing) or 'the missing KPIs'} "
                f"and folding overlapping reports into it.{tail}")
    if dec == "migrate":
        return f"I recommend a migration. {d.get('reason', '')}"
    if dec == "new_build":
        model = cat.model_by_id(d.get("target_model_id")) or {}
        others = ", ".join((p.get("intent") or {}).get("other_markets") or [])
        if others:
            return (f"No existing report covers {others}, and the catalog holds no data for it yet. I recommend one new thin report on the "
                    f"shared model **{model.get('name', d.get('target_model_id'))}** once that data is added. Nothing has been built.{tail}")
        return (f"No existing report is both close enough and well governed. I recommend one new thin report on the shared model "
                f"**{model.get('name', d.get('target_model_id'))}** using approved KPIs only. Nothing has been built.{tail}")
    if dec == "review":
        return f"I recommend a human review first. {d.get('reason', '')}"
    if dec == "retire":
        return f"I recommend retirement. {d.get('reason', '')}{tail}"
    terms = ", ".join((d.get("availability") or {}).get("missing_terms") or [])
    return ("This can't be answered from the governed estate"
            + (f": it needs {terms}" if terms else "") +
            ". The data pack holds aggregated commercial and operational data only, with no patient or prescriber-level data.")
