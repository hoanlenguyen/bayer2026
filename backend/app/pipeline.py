"""Orchestrates the processing flow and streams events to the UI.

Flow: intent → discovery → governance → decision → (reuse: deliver)
                                               → (extend/create: evidence → spec → approval → render → register)
                                               → (not feasible: explain)

Every stage emits ``stage`` events (running / waiting / done) with a payload
the UI can show, so the user always sees how a decision was reached.
"""
from __future__ import annotations

import asyncio
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, AsyncIterator

from . import catalog as cat
from .decision import Decision, data_availability, decide, rank_candidates
from .llm import MockProvider, OpenAIProvider, sanitize_intent
from .pbip import render_pbip, slug
from .settings import settings
from .store import Store

STAGES = {
    "intent": "Understand the request",
    "discovery": "Find existing analytics",
    "governance": "Check governance",
    "decision": "Decide: reuse, extend or create",
    "deliver": "Open the existing report",
    "evidence": "Gather evidence",
    "spec": "Write the specification",
    "approval": "Human approval",
    "render": "Generate PBIP files",
    "register": "Register in the catalog",
}

DIM_COLUMN_HINTS = {
    "customer": "customer_id", "carrier": "carrier_id", "line": "line_id", "product": "product_id",
    "batch": "batch_id", "material": "material_id", "supplier": "supplier_id", "priority": "priority",
    "deviation_category": "category", "shift": "shift", "department": "department", "cost_center": "cost_center",
    "destination_country": "destination_country",
}

Event = dict[str, Any]
GRAIN_ADJ = {"hour": "hourly", "day": "daily", "week": "weekly", "month": "monthly"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def public(intent: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in intent.items() if not k.startswith("_")}


def label_list(ids: list[str], kind: str) -> str:
    src = cat.CATALOG["measures" if kind == "m" else "dimensions"]
    return ", ".join(src[i]["name"] for i in ids if i in src)


class Pipeline:
    def __init__(self, store: Store, llm: MockProvider | OpenAIProvider) -> None:
        self.store = store
        self.llm = llm

    # ------------------------------------------------------------ helpers
    def _event(self, conv: dict[str, Any], type_: str, **data: Any) -> Event:
        ev = {"type": type_, "ts": now(), **data}
        if conv["runs"]:
            conv["runs"][-1]["events"].append(ev)
        return ev

    def _stage(self, conv: dict[str, Any], stage: str, status: str, summary: str = "", data: Any = None) -> Event:
        return self._event(conv, "stage", stage=stage, title=STAGES[stage], status=status, summary=summary, data=data)

    def _say(self, conv: dict[str, Any], text: str, **extra: Any) -> Event:
        msg = {"role": "assistant", "content": text, "ts": now(), **extra}
        conv["messages"].append(msg)
        return self._event(conv, "message", **msg)

    async def _pause(self) -> None:
        if settings.stage_delay:
            await asyncio.sleep(settings.stage_delay)

    async def _load(self, conv_id: str | None) -> dict[str, Any]:
        conv = await self.store.get(conv_id) if conv_id else None
        if conv:
            return conv
        return {"_id": conv_id or uuid.uuid4().hex[:12], "title": None, "created_at": now(), "updated_at": now(),
                "state": "idle", "messages": [], "intent": {}, "asked": 0, "preset_id": None, "plan": None, "runs": []}

    async def _save(self, conv: dict[str, Any]) -> None:
        conv["updated_at"] = now()
        await self.store.save(conv)

    # ------------------------------------------------------------ chat turn
    async def chat(self, conv_id: str | None, message: str, preset_id: str | None) -> AsyncIterator[Event]:
        conv = await self._load(conv_id)
        try:
            preset = cat.preset_by_id(preset_id)
            text = message.strip() or (preset["prompt"] if preset else "")
            conv["title"] = conv["title"] or text[:70]
            yield {"type": "conversation", "id": conv["_id"], "provider": self.llm.name, "store": self.store.name}

            new_run = conv["state"] != "clarifying"
            if new_run:
                if conv["state"] == "awaiting_approval":
                    conv["plan"] = None  # a new request replaces an unapproved plan
                conv["runs"].append({"id": uuid.uuid4().hex[:8], "started_at": now(), "events": [],
                                     "msg_start": len(conv["messages"])})
                conv["preset_id"] = preset["id"] if preset else None
                conv["asked"] = 0
                conv["intent"] = {"question": text, "measures": [], "dimensions": [], "grain": None, "filters": {},
                                  "unmatched_terms": [], "decision": None}
                if preset:
                    conv["intent"].update(measures=list(preset["measures"]), dimensions=list(preset["dimensions"]),
                                          grain=preset["grain"], decision=preset["decision"],
                                          unmatched_terms=list(preset.get("requested_terms", [])),
                                          department=preset["department"])
            run = conv["runs"][-1]
            conv["messages"].append({"role": "user", "content": text, "ts": now(), "preset_id": conv["preset_id"]})
            yield self._event(conv, "user_message", content=text)
            if new_run:
                yield self._stage(conv, "intent", "running", "Reading your request")
                await self._pause()

            # ---- 1. Intent extraction (/grill-me)
            transcript = [{"role": m["role"], "content": m["content"]} for m in conv["messages"][run["msg_start"]:]]
            result = await self.llm.grill(transcript, conv["intent"], conv["asked"], cat.preset_by_id(conv["preset_id"]))
            pending = result["intent"].get("_pending")
            intent = sanitize_intent(result["intent"])
            if pending:
                intent["_pending"] = pending
            conv["intent"] = intent

            if result["status"] == "ask" and result.get("question"):
                conv["asked"] += 1
                conv["state"] = "clarifying"
                yield self._stage(conv, "intent", "waiting", f"Question {conv['asked']} of up to 2", public(intent))
                yield self._say(conv, result["question"], kind="question", suggestions=result.get("suggestions", []))
                yield self._event(conv, "done", state=conv["state"])
                return

            intent.pop("_pending", None)
            if not intent.get("grain"):
                first = intent["measures"][0] if intent["measures"] else None
                intent["grain"] = cat.measure(first)["default_grain"] if first else "day"
            intent["decision"] = intent.get("decision") or f"Monitor {label_list(intent['measures'], 'm') or 'the requested numbers'}"
            intent["department"] = intent.get("department") or cat.department_for(intent["measures"])
            conv["intent"] = intent
            summary = (f"{label_list(intent['measures'], 'm') or 'No catalog measures'}"
                       f"{' by ' + label_list(intent['dimensions'], 'd') if intent['dimensions'] else ''}, per {intent['grain']}")
            yield self._stage(conv, "intent", "done", summary, public(intent))
            await self._pause()

            async for ev in self._plan(conv):
                yield ev
        finally:
            await self._save(conv)

    # ------------------------------------------------------------ discovery → decision → branch
    async def _plan(self, conv: dict[str, Any]) -> AsyncIterator[Event]:
        intent = conv["intent"]

        # ---- 2. Discovery
        yield self._stage(conv, "discovery", "running", "Searching the catalog")
        await self._pause()
        candidates = rank_candidates(intent, cat.CATALOG["assets"])
        availability = data_availability(intent, cat.CATALOG)
        yield self._stage(conv, "discovery", "done",
                          f"{len(candidates)} related report{'s' if len(candidates) != 1 else ''} found in {len(cat.CATALOG['assets'])} catalog assets",
                          {"candidates": [c.to_dict() for c in candidates], "availability": availability,
                           "searched": len(cat.CATALOG["assets"])})
        await self._pause()

        # ---- 3. Governance check
        yield self._stage(conv, "governance", "running", "Scoring each candidate")
        await self._pause()
        passing = sum(1 for c in candidates if c.gates_pass and c.governance >= 0.8)
        yield self._stage(conv, "governance", "done", f"{passing} of {len(candidates)} candidates are well governed",
                          {"candidates": [{"asset_id": c.asset_id, "name": c.name, "governance": c.governance,
                                           "checks": [vars(k) for k in c.checks], "gates_failed": c.gates_failed}
                                          for c in candidates]})
        await self._pause()

        # ---- 4. Decision (deterministic)
        result = decide(candidates, availability["available"])
        decision = result.to_dict()
        missing = availability["missing_terms"] + [cat.CATALOG["dimensions"][d]["name"] for d in availability["missing_dimensions"]]
        decision["availability"] = availability
        conv["plan"] = {"decision": decision}
        label = {"reuse": "Reuse", "extend": "Extend", "create": "Create", "not_feasible": "Not feasible"}[result.decision.value]
        if result.change_type:
            label += f" ({result.change_type})"
        yield self._stage(conv, "decision", "done", label, decision)
        explanation = await self.llm.explain("decision", {"decision": decision, "intent": public(intent),
                                                           "missing_text": ("Missing: " + ", ".join(missing) + ".") if missing else ""})
        await self._pause()

        if result.decision == Decision.REUSE:
            c = result.candidate
            asset = cat.asset_by_id(c.asset_id)
            yield self._stage(conv, "deliver", "done", f"Opened '{c.name}'",
                              {"asset": asset, "filters": intent.get("filters", {})})
            yield self._say(conv, explanation, kind="result", decision="reuse", asset_id=c.asset_id)
            conv["state"] = "idle"
            yield self._event(conv, "done", state="idle")
            return

        if result.decision == Decision.NOT_FEASIBLE:
            yield self._say(conv, explanation + " You can rephrase the request, or ask the data team to add a source.",
                            kind="result", decision="not_feasible",
                            suggestions=["Which deliveries need action today?", "What needs attention on my lines this shift?"])
            conv["state"] = "idle"
            yield self._event(conv, "done", state="idle")
            return

        # ---- 5. Evidence
        yield self._stage(conv, "evidence", "running", "Collecting proof from sources")
        await self._pause()
        evidence = self._evidence(intent, decision, availability)
        conv["plan"]["evidence"] = evidence
        yield self._stage(conv, "evidence", "done", f"{len(evidence['proofs'])} checks on {len(evidence['datasets'])} source table(s)", evidence)
        await self._pause()

        # ---- 6. Specification
        yield self._stage(conv, "spec", "running", "Drafting the DashboardSpec")
        spec = await self._spec(conv, intent, decision, evidence)
        conv["plan"]["spec"] = spec
        n_vis = sum(len(p["visuals"]) for p in spec["pages"])
        yield self._stage(conv, "spec", "done", f"{len(spec['measures'])} certified measures, {n_vis} visuals", spec)
        await self._pause()

        # ---- 7. Human approval
        conv["state"] = "awaiting_approval"
        approver = spec.get("approver", "Report owner")
        yield self._stage(conv, "approval", "waiting", f"Waiting for {approver}", {"approver": approver})
        yield self._say(conv, explanation + " Review the evidence and specification, then approve to generate the PBIP files.",
                        kind="approval", decision=result.decision.value)
        yield self._event(conv, "done", state=conv["state"])

    def _evidence(self, intent: dict[str, Any], decision: dict[str, Any], availability: dict[str, Any]) -> dict[str, Any]:
        C = cat.CATALOG
        cand = decision.get("candidate")
        base = cat.asset_by_id(cand["asset_id"]) if cand and decision["decision"] == "extend" else None
        datasets = availability["datasets"] or (base["datasets"] if base else [])
        datasets = [d for d in datasets if d in C["datasets"]]

        columns: dict[str, list[str]] = {}
        for ds in datasets:
            cols = C["datasets"][ds]["columns"]
            used: list[str] = []
            for m in intent["measures"]:
                for col in re.findall(rf"{ds}\[(\w+)\]", C["measures"][m]["expression"]):
                    used.append(col)
            for d in intent["dimensions"] + ["date"]:
                hint = DIM_COLUMN_HINTS.get(d)
                if d == "date":
                    used += [c for c in cols if c.endswith("_date") or c.endswith("_ts") or c == "date"][:1]
                elif hint and hint in cols:
                    used.append(hint)
            columns[ds] = [c for c in dict.fromkeys(used) if c in cols]

        proofs = []
        for ds in datasets:
            d = C["datasets"][ds]
            proofs.append({"ok": d["tests_passed"] == d["tests_total"],
                           "text": f"{d['table']}: {d['rows']:,} rows, refreshed {d['refresh_age_hours']} h ago, "
                                   f"{d['tests_passed']}/{d['tests_total']} quality tests pass. Owner: {d['owner']}."})
        for m in intent["measures"]:
            md = C["measures"][m]
            proofs.append({"ok": md["certified"], "text": f"{md['name']} uses the certified definition: {md['definition']}"})
        if base:
            if decision["change_type"] == "maintenance":
                proofs.append({"ok": False, "text": f"'{base['name']}' was refreshed {base['refresh_age_hours']} h ago; "
                                                    f"a {GRAIN_ADJ[intent['grain']]} decision needs fresher data."})
            else:
                gaps = cand["measures_missing"] + cand["dimensions_missing"]
                if gaps:
                    proofs.append({"ok": True, "text": f"Missing in '{base['name']}': {', '.join(gaps)}. All are available in the source tables above."})
                if not cand["grain_supported"]:
                    proofs.append({"ok": True, "text": f"'{base['name']}' is {GRAIN_ADJ[base['grain']]}; the request needs {GRAIN_ADJ[intent['grain']]}. Source data supports it."})

        rels = [r for r in C["relationships"] if r["from"].split(".")[0] in datasets]
        return {"datasets": datasets, "columns": columns, "relationships": rels, "proofs": proofs,
                "base_asset": base, "measures": intent["measures"], "dimensions": intent["dimensions"]}

    async def _spec(self, conv, intent, decision, evidence) -> dict[str, Any]:
        C = cat.CATALOG
        base = evidence["base_asset"]
        preset = cat.preset_by_id(conv.get("preset_id"))
        if base:
            name = base["name"]
        elif preset:
            name = f"{preset['department']} · {preset['title']}"
        else:
            name = label_list(intent["measures"][:2], "m") + (f" by {label_list(intent['dimensions'][:1], 'd').lower()}" if intent["dimensions"] else "")
        measures = [{"id": m, **{k: C["measures"][m][k] for k in ("name", "expression", "definition", "dataset", "unit")},
                     "certified": C["measures"][m]["certified"]} for m in intent["measures"]]
        draft = {"name": name, "decision": intent["decision"], "grain": intent["grain"], "measures": measures,
                 "dimensions": intent["dimensions"]}
        layout = await self.llm.spec_layout(draft)
        change: dict[str, Any] = {}
        if decision["change_type"] == "maintenance":
            change = {"refresh_schedule": "every 4 hours", "note": "Maintenance change: no new visuals."}
        elif base:
            cand = decision["candidate"]
            change = {"add_measures": cand["measures_missing"], "add_dimensions": cand["dimensions_missing"],
                      "grain": intent["grain"] if not cand["grain_supported"] else base["grain"]}
        return {
            "name": name,
            "decision": intent["decision"],
            "decision_type": decision["decision"],
            "change_type": decision.get("change_type"),
            "base_asset_id": base["id"] if base else None,
            "change": change,
            "entities": evidence["datasets"],
            "columns": evidence["columns"],
            "grain": {ds: intent["grain"] for ds in evidence["datasets"]},
            "relationships": evidence["relationships"],
            "measures": measures,
            "dimensions": intent["dimensions"],
            "filters": intent.get("filters", {}),
            "pages": layout["pages"],
            "rationale": layout.get("rationale", ""),
            "owner": base["owner"] if base else "You (requester)",
            "approver": base["owner"] if base else "Data steward",
            "review_date": (date.today() + timedelta(days=180)).isoformat(),
        }

    # ------------------------------------------------------------ approval → render → register
    async def approve(self, conv_id: str, approved: bool, approver: str) -> AsyncIterator[Event]:
        conv = await self._load(conv_id)
        try:
            yield {"type": "conversation", "id": conv["_id"], "provider": self.llm.name, "store": self.store.name}
            if conv["state"] != "awaiting_approval" or not conv.get("plan", {}).get("spec"):
                yield {"type": "error", "message": "There is nothing waiting for approval in this conversation."}
                return
            spec = conv["plan"]["spec"]
            if not approved:
                yield self._stage(conv, "approval", "rejected", f"Rejected by {approver}", {"approver": approver})
                yield self._say(conv, "Understood. Nothing was built. Tell me what to change, or ask a new question.", kind="result")
                conv["state"] = "idle"
                yield self._event(conv, "done", state="idle")
                return

            spec.update(approved_by=approver, approved_at=now())
            yield self._stage(conv, "approval", "done", f"Approved by {approver}", {"approver": approver, "approved_at": spec["approved_at"]})
            await self._pause()

            yield self._stage(conv, "render", "running", "Writing PBIP files (plain Python, no AI)")
            await self._pause()
            output = render_pbip(spec, settings.output_dir, conv["_id"])
            yield self._stage(conv, "render", "done", f"{len(output['files'])} files in {output['folder']}", output)
            await self._pause()

            entry = self._register(spec)
            yield self._stage(conv, "register", "done", f"'{entry['name']}' is now in the catalog with owner and review date", entry)
            yield self._say(conv, f"Done. **{entry['name']}** is generated as a PBIP project and registered with owner "
                                  f"{entry['owner']} and a review date of {entry['next_review']}. Ask the same question again and I will reuse it.",
                            kind="result", decision=spec["decision_type"], asset_id=entry["id"])
            conv["state"] = "idle"
            yield self._event(conv, "done", state="idle")
        finally:
            await self._save(conv)

    def _register(self, spec: dict[str, Any]) -> dict[str, Any]:
        today = date.today().isoformat()
        base = cat.asset_by_id(spec["base_asset_id"]) if spec.get("base_asset_id") else None
        if base:
            if spec["change_type"] == "maintenance":
                base["refresh_age_hours"] = 1
                for ds in base["datasets"]:
                    if ds in cat.CATALOG["datasets"]:
                        cat.CATALOG["datasets"][ds]["refresh_age_hours"] = 1
            else:
                base["measures"] = list(dict.fromkeys(base["measures"] + spec["change"].get("add_measures", [])))
                base["dimensions"] = list(dict.fromkeys(base["dimensions"] + spec["change"].get("add_dimensions", [])))
                base["grain"] = spec["change"].get("grain", base["grain"])
            base["last_review"] = today
            return {**base, "next_review": spec["review_date"], "change": spec["change"]}

        asset = {
            "id": "rpt_" + slug(spec["name"]).lower(), "name": spec["name"], "workspace": "Generated · Pending certification",
            "grain": next(iter(spec["grain"].values()), "day"), "measures": [m["id"] for m in spec["measures"]],
            "dimensions": list(dict.fromkeys(spec["dimensions"] + ["date"])), "datasets": spec["entities"],
            "certified": False, "owner": spec["owner"], "owner_status": "active", "backup_owner": "Data steward",
            "refresh_age_hours": 1, "last_review": today, "documented": True, "tests_passing": True,
            "conflicts": {}, "restricted": False, "views_90d": 0,
        }
        cat.CATALOG["assets"].append(asset)
        return {**asset, "next_review": spec["review_date"]}
