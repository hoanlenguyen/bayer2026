"""Evidence & governance inside the BI Portfolio.

Three questions from the BI department head: what triggered a finding (evidence), which guidance applies to a
dashboard and why (applicability), and what should happen next (risks, reviews, history). Facts come from the
challenge workbook, the app's own records and owner submissions, each labelled with its authority. Python decides
applicability from explicit mappings and recorded facts; nothing is inferred from keywords or a model.

Stored here (append-only or status-checked): registered documents and revisions, applicability mappings,
exceptions, owner-submitted evidence and review events with their assessment snapshots. Everything else is
derived on read from the workbook and the app's existing records.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from . import bi_estate as be
from . import catalog, datapack
from .report_register import _events as register_events

router = APIRouter(prefix="/api/bi-governance")

DOCS, REVS, MAPS, EXCS, SUBMITTED, EVENTS = ("gov_documents", "gov_doc_revisions", "gov_mappings", "gov_exceptions",
                                             "gov_evidence", "gov_events")
AUTHORITY = {"company_document": "Company document", "demo_document": "Demo document",
             "challenge_workbook": "Challenge workbook", "analytiq_check": "AnalytIQ check",
             "source_observation": "Source observation", "app_record": "AnalytIQ record",
             "owner_statement": "Owner statement", "verified_statement": "Owner statement, verified"}
CHECKS = {c["id"]: c for c in (be.PAIR_RULE, be.SCOPE_RULE, be.DEFINITION_RULE)}
SOURCES_DIR = Path(__file__).parent / "data" / "governance"
PRIORITY = {"high": 0, "medium": 1, "low": 2, None: 3}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _today() -> str:
    return date.today().isoformat()


def _sheet(key: str) -> str:
    return "_".join("KPI" if w == "kpi" else w.capitalize() for w in key.split("_"))


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:16]


@lru_cache(maxsize=1)
def sources() -> dict[str, dict]:
    data = json.loads((SOURCES_DIR / "sources.json").read_text())
    return {s["ref"]: s for s in data["sources"]}


# --------------------------------------------------------------------------- access

def scoped_assets(records: list[dict], actor: dict | None) -> dict[str, dict]:
    """The assets this viewer may see. One BI estate per installation, so every inventory asset is in the portfolio.
    A real membership relation would narrow this; every read and write goes through here."""
    return {r["id"]: r for r in records}


def doc_visible(doc: dict | None, actor: dict | None) -> bool:
    if not doc:
        return False
    if doc.get("access", "public_demo") == "public_demo":
        return True
    return bool(actor and actor["role"] in doc.get("access_roles", []))


def _not_found(what: str = "item") -> HTTPException:
    # The same answer for "does not exist" and "not yours to see", so guesses learn nothing.
    return HTTPException(404, f"No {what} with this ID is available to you.")


def _require(actor: dict | None, *roles: str) -> dict:
    if not actor:
        raise HTTPException(401, "Choose a demo identity to make changes. Viewers can only read.")
    if actor["role"] not in roles:
        raise HTTPException(403, "Your role cannot do this here.")
    return actor


# --------------------------------------------------------------------------- workbook evidence (derived, cached per snapshot)

def _wb_source(sheet: str, row: int, record_id: str | None, fields: list[str] | None = None) -> dict:
    wb = _workbook()
    return {"kind": "workbook", "authority": "challenge_workbook", "label": AUTHORITY["challenge_workbook"],
            "file": wb["file"], "revision": wb["sha"], "sheet": _sheet(sheet), "row": row, "record_id": record_id,
            "fields": fields or []}


@lru_cache(maxsize=1)
def _workbook() -> dict:
    path = datapack.workbook_path()
    return {"file": path.name, "sha": be._workbook_sha(str(path))[:12], "collected_at": _now()}


def _item(eid: str, kind: str, label: str, value: Any, source: dict, *, observed_at: str | None = None,
          observed_meaning: str | None = None, authority: str = "challenge_workbook", links: list[str] | None = None) -> dict:
    return {"id": eid, "kind": kind, "label": label, "value": value, "source": source, "authority": authority,
            "authority_label": AUTHORITY[authority], "observed_at": observed_at, "observed_meaning": observed_meaning,
            "collected_at": _workbook()["collected_at"], "availability": "available", "links": links or []}


def _row(sheet: str, row: int) -> dict:
    return catalog.SHEETS[sheet][row - 2]


@lru_cache(maxsize=2)
def _workbook_evidence(snapshot_key: int) -> dict[str, list[dict]]:
    """Evidence items for every workbook asset, keyed by asset. Items for a shared record (a KPI definition) repeat
    the same ID under each asset that binds it."""
    proj = be.projection()
    ws_rows = {r["workspace_id"]: (i, r) for i, r in enumerate(catalog.SHEETS["workspaces"], 2)}
    owner_rows = {r["owner_id"]: i for i, r in enumerate(catalog.SHEETS["owners"], 2)}
    market_rows = {m: v["row"] for m, v in proj["markets"].items()}
    out: dict[str, list[dict]] = {}
    for aid, a in proj["assets"].items():
        raw = _row("analytics_assets", a["row"])
        items = [_item(f"ev-analytics_assets-{a['row']}", "asset_record",
                       f"{raw['asset_name']}: {raw['platform']} {raw['asset_type'].lower()} in {raw['workspace_id']}, "
                       f"model {raw['model_id']}, declared {raw['product_scope']} / {raw['market_scope']}, endorsement {raw['endorsement']}",
                       {k: raw[k] for k in ("asset_type", "platform", "workspace_id", "model_id", "product_scope", "market_scope",
                                            "owner_id", "lifecycle_status", "endorsement", "estimated_audience")},
                       _wb_source("analytics_assets", a["row"], aid), observed_meaning="As recorded in the workbook")]
        if raw["workspace_id"] in ws_rows:
            i, w = ws_rows[raw["workspace_id"]]
            items.append(_item(f"ev-workspaces-{i}", "workspace", f"Workspace {w['workspace_id']} {w['workspace_name']} is {w['environment']}",
                               {k: w[k] for k in ("environment", "platform", "governance_mode", "classification")},
                               _wb_source("workspaces", i, w["workspace_id"], ["environment"])))
        if raw["owner_id"] in owner_rows:
            o = proj["owners"].get(raw["owner_id"])
            items.append(_item(f"ev-owners-{owner_rows[raw['owner_id']]}", "owner", f"Imported owner {o['name']} {o['id']} is {o['status']}",
                               {"status": o["status"], "role": o["role"]}, _wb_source("owners", owner_rows[raw["owner_id"]], o["id"], ["status"])))
        m = a["model"]
        if m and m.get("row"):
            items.append(_item(f"ev-semantic_models-{m['row']}", "model",
                               f"Model {m['id']} {m['name']} covers {m['product']} / {m['region']}, refresh {m['refresh_status']}",
                               {"product_scope": m["product"], "region_scope": m["region"], "refresh_status": m["refresh_status"],
                                "refresh_frequency": m["cadence"], "endorsement": m["endorsement"]},
                               _wb_source("semantic_models", m["row"], m["id"])))
        for b in proj["bindings"][aid]:
            k = proj["kpis"].get(b["kpi_id"])
            items.append(_item(f"ev-asset_kpi_map-{b['row']}", "kpi_binding",
                               f"Binds {b['kpi_id']} {k['kpi_name'] if k else ''} ({b['usage_role']})".replace("  ", " "),
                               {"kpi_id": b["kpi_id"], "usage_role": b["usage_role"]}, _wb_source("asset_kpi_map", b["row"], aid)))
            if k:
                items.append(_item(f"ev-kpi_catalog-{k['row']}", "kpi_definition",
                                   f"{b['kpi_id']} {k['kpi_name']}: {k['definition_status'].replace('_', ' ')}, {k['approval_status']}",
                                   {"canonical_metric": k["canonical_metric"], "definition_status": k["definition_status"],
                                    "approval_status": k["approval_status"], "unit": k["unit"]},
                                   _wb_source("kpi_catalog", k["row"], b["kpi_id"])))
        for e in proj["upstream"][aid]:
            items.append(_item(f"ev-lineage_edges-{e['row']}", "lineage", f"{e['source_id']} → {aid} ({e['relationship']})",
                               {"edge_type": e["edge_type"], "source_id": e["source_id"], "target_id": e["target_id"]},
                               _wb_source("lineage_edges", e["row"], f"{e['source_id']}→{e['target_id']}")))
        for e in proj["downstream"][aid]:
            items.append(_item(f"ev-lineage_edges-{e['row']}", "lineage", f"{aid} → {e['target_id']} ({e['relationship']})",
                               {"edge_type": e["edge_type"], "source_id": e["source_id"], "target_id": e["target_id"]},
                               _wb_source("lineage_edges", e["row"], f"{e['source_id']}→{e['target_id']}")))
        for s in proj["signals"][aid]:
            items.append(_item(f"ev-governance_signals-{s['row']}", "source_signal",
                               f"{s['signal_id']} {s['signal_code'].replace('_', ' ').lower()}: {s['severity']} severity, {s['status']}",
                               {k: s[k] for k in ("signal_id", "signal_code", "severity", "status", "detected_by")},
                               _wb_source("governance_signals", s["row"], s["signal_id"]), authority="source_observation"))
        for q in proj["quality"].get(m["id"] if m else "", []) + proj["quality"].get(aid, []):
            items.append(_item(f"ev-data_quality-{q['row']}", "quality_issue", f"{q['issue_id']} on {q['record_id']}.{q['field']}: {q['impact']}",
                               {k: q[k] for k in ("issue_id", "record_id", "field", "issue_value", "severity")},
                               _wb_source("data_quality", q["row"], q["issue_id"]), authority="source_observation"))
        if a["usage"]["last_view_row"]:
            items.append(_item(f"ev-asset_usage-{a['usage']['last_view_row']}", "usage_month",
                               f"Last month with views: {a['usage']['last_view_month']}, {a['usage']['last_view_count']:,} views",
                               {"month": a["usage"]["last_view_month"], "views": a["usage"]["last_view_count"]},
                               _wb_source("asset_usage", a["usage"]["last_view_row"], aid, ["month", "views"]),
                               observed_at=a["usage"]["last_view_month"], observed_meaning="Reporting month (a monthly count, not an open time)"))
        # AnalytIQ's own derived checks, linking the records they join.
        ids = {i["kind"]: i["id"] for i in items}
        if a["variant_kpi_ids"]:
            # Only the definitions in conflict and the other bindings of the same metric family, e.g. both Net Sales KPIs.
            families = {proj["kpis"][v]["canonical_metric"] for v in a["variant_kpi_ids"]}
            related = {k for k in a["kpi_ids"] if k in proj["kpis"] and proj["kpis"][k]["canonical_metric"] in families}
            linked = [i["id"] for i in items if (i["kind"] == "kpi_binding" and i["value"]["kpi_id"] in related)
                      or (i["kind"] == "kpi_definition" and i["source"]["record_id"] in related)]
            items.append(_item(f"ev-check-DEF-1-{aid}", "derived", f"DEF-1: binds {', '.join(a['variant_kpi_ids'])}, marked definition conflict",
                               {"conflicting_kpis": a["variant_kpi_ids"]}, {"kind": "check", **CHECKS["DEF-1"]},
                               authority="analytiq_check", links=linked))
        if a["scope"] and a["scope"]["mismatch"]:
            links = [ids.get("asset_record"), ids.get("model")] + [i["id"] for i in items if i["kind"] == "lineage" and i["value"]["target_id"] == aid]
            if a["market"] in market_rows:
                links.append(f"ev-markets-{market_rows[a['market']]}")
            items.append(_item(f"ev-check-SCOPE-1-{aid}", "derived",
                               f"SCOPE-1: report declares {a['product']} / {a['market']}, model {m['id']} covers {m['product']} / {m['region']}",
                               {"product": a["scope"]["product"], "geography": a["scope"]["geography"]},
                               {"kind": "check", **CHECKS["SCOPE-1"]}, authority="analytiq_check", links=[l for l in links if l]))
        out[aid] = items
    return out


def workbook_evidence() -> dict[str, list[dict]]:
    return _workbook_evidence(id(catalog.SHEETS.get("analytics_assets")))


def _market_item(row: int) -> dict:
    r = _row("markets", row)
    return _item(f"ev-markets-{row}", "market", f"Market {r['market_id']} {r['market_name']} is in {r['region']}",
                 {"region": r["region"]}, _wb_source("markets", row, r["market_id"]))


async def _app_evidence(store, r: dict, proj: dict) -> list[dict]:
    items = []
    if r["origin"] == "app_report":
        for kid in r["kpi_ids"]:
            k = proj["kpis"].get(kid)
            if k:
                items.append(_item(f"ev-kpi_catalog-{k['row']}", "kpi_definition",
                                   f"{kid} {k['kpi_name']}: {k['definition_status'].replace('_', ' ')}, {k['approval_status']}",
                                   {"definition_status": k["definition_status"], "approval_status": k["approval_status"]},
                                   _wb_source("kpi_catalog", k["row"], kid)))
        for e in await register_events(store, r["id"]):
            items.append(_item(f"ev-register-{e['_id']}", "report_revision",
                               f"Report register: {e['kind']} by {e['actor_name']}" + (f", revision {e['revision']}" if e.get("revision") else ""),
                               {"kind": e["kind"], "revision": e.get("revision"), "note": e.get("note")},
                               {"kind": "app", "label": "BI report register", "collection": "report_register_events", "record_id": e["_id"]},
                               observed_at=e.get("at"), observed_meaning="When the change was recorded", authority="app_record"))
    elif r["origin"] == "generated":
        d = await store.get_artifact("dashboards", r["id"]) or {}
        src = {"kind": "app", "label": "Saved dashboard", "collection": "dashboards", "record_id": r["id"]}
        items.append(_item(f"ev-dash-{r['id']}-brief", "approved_brief",
                           f"Approved brief: {d.get('decision_goal') or 'no goal recorded'} · {(d.get('period') or {}).get('start')} to {(d.get('period') or {}).get('end')}",
                           {"decision_goal": d.get("decision_goal"), "period": d.get("period"), "scope": d.get("scope"),
                            "measures": [{"kpi_id": c.get("kpi_id"), "name": c.get("name"), "field": c.get("field"), "unit": c.get("unit")}
                                         for c in d.get("columns") or []], "run_id": d.get("run_id"),
                            "conversation_id": d.get("conversation_id"), "omitted_measures": d.get("omitted_measures")},
                           src, observed_at=d.get("created_at"), observed_meaning="When the dashboard was saved", authority="app_record"))
        if d.get("created_by"):
            items.append(_item(f"ev-dash-{r['id']}-creator", "creator", f"Built by {d['created_by']['name']}",
                               d["created_by"], src, observed_at=d["created_by"].get("at"), observed_meaning="Build time",
                               authority="app_record"))
        for rec in d.get("source_records") or []:
            sheet = (d.get("source") or "Product_Market_Monthly").lower()
            rows = catalog.SHEETS.get(sheet, [])
            now_row = rows[rec["row"] - 2] if 0 <= rec["row"] - 2 < len(rows) else None
            values = {k: v for k, v in rec.items() if k != "row"}
            changed = now_row is None or any(now_row.get(k) != v for k, v in values.items())
            item = _item(f"ev-dash-{r['id']}-row-{rec['row']}", "source_record",
                         f"{d.get('source')} row {rec['row']}: {rec['product_id']} {rec['market_id']} {rec['month'][:7]}",
                         values, _wb_source(sheet, rec["row"], f"{rec['product_id']}·{rec['market_id']}·{rec['month'][:7]}"),
                         observed_at=rec["month"][:7], observed_meaning="Reporting month")
            if changed:
                item["availability"] = "changed_since_cited"  # the cited values stay as they were saved
            items.append(item)
    return items


def _submitted_view(s: dict) -> dict:
    status = s.get("status", "statement")
    authority = "verified_statement" if status == "verified" else "owner_statement"
    return {"id": s["_id"], "kind": "owner_submission", "label": s["supports"], "value": {"reference": s["reference"],
            "revision_or_section": s["revision_or_section"], "record_evidence_id": s.get("record_evidence_id")},
            "source": {"kind": "submission", "label": "Submitted in AnalytIQ", "record_id": s["_id"]},
            "authority": authority, "authority_label": AUTHORITY[authority], "observed_at": s["at"],
            "observed_meaning": "When it was submitted", "collected_at": s["at"], "availability": "available",
            "links": [x for x in (s.get("record_evidence_id"),) if x], "status": status, "submitted_by": s["actor_name"],
            "finding_id": s.get("finding_id"), "clause_ref": s.get("clause_ref"), "supersedes": s.get("supersedes"),
            "superseded_by": s.get("superseded_by"), "reviews": s.get("reviews", []), "asset_id": s["asset_id"], "seq": s["seq"]}


# --------------------------------------------------------------------------- documents, mappings, exceptions (stored)

def workbook_rules() -> dict[str, dict]:
    wb = _workbook()
    out = {}
    for i, r in enumerate(catalog.SHEETS["governance_rules"], 2):
        out[r["rule_id"]] = {
            "id": r["rule_id"], "title": r["rule_name"], "authority": "challenge_workbook", "authority_label": AUTHORITY["challenge_workbook"],
            "issuer": "SinceAI challenge workbook", "owner": None, "accountable_team": None, "access": "public_demo",
            "priority": r["priority"], "note": "No signed document, effective date, owner, reach threshold or expiry is given in the workbook.",
            "revisions": [{"revision": 1, "version": None, "effective_from": None, "effective_to": None, "workbook_revision": wb["sha"],
                           "clauses": {"1": {"title": r["rule_name"], "text": r["rule_description"]}},
                           "source": _wb_source("governance_rules", i, r["rule_id"], ["rule_description", "priority"])}],
        }
    return out


async def documents(store, actor: dict | None) -> dict[str, dict]:
    """Registered documents the viewer may see, with their revisions in order. Effective ends come from the next revision."""
    docs = {d["_id"]: d for d in await be._find(store, DOCS)}
    revs = await be._find(store, REVS, sort="_id")
    out = {}
    for did, d in docs.items():
        if not doc_visible(d, actor):
            continue
        rs = sorted(({**r, "effective_to": None} for r in revs if r["doc_id"] == did), key=lambda r: r["revision"])
        for a, b in zip(rs, rs[1:]):
            a["effective_to"] = b["effective_from"]
        out[did] = {**{k: v for k, v in d.items() if k != "_id"}, "id": did,
                    "authority_label": AUTHORITY[d["authority"]], "revisions": rs}
    return out


def revision_at(doc: dict, at: str) -> dict | None:
    current = None
    for r in doc["revisions"]:
        if r["effective_from"] is None or r["effective_from"] <= at:
            current = r
    return current


def _clause_view(doc: dict, rev: dict, clause_id: str) -> dict:
    c = rev["clauses"][clause_id]
    return {"doc_id": doc["id"], "doc_title": doc["title"], "authority": doc["authority"], "authority_label": doc["authority_label"],
            "revision": rev["revision"], "version": rev.get("version"), "effective_from": rev.get("effective_from"),
            "effective_to": rev.get("effective_to"), "clause_id": clause_id, "clause_title": c["title"], "text": c["text"],
            "source": rev.get("source")}


async def _exceptions(store) -> list[dict]:
    return await be._find(store, EXCS, sort="_id")


def _exception_state(e: dict, at: str) -> str:
    if e["status"] != "approved":
        return e["status"]
    return "active" if at <= e["expires"] else "expired"


# --------------------------------------------------------------------------- risks (derived) and their review state

def _risk(r: dict, code: str, title: str, observation: str, consequence: str, *, origin: str, evidence: list[str],
          rules: list[str] = (), checks: list[str] = (), source_severity: str | None = None, source_status: str | None = None,
          signal_id: str | None = None, next_action: str = "") -> dict:
    rid = f"RISK-{r['id']}-{signal_id or code}"
    return {"id": rid, "asset_id": r["id"], "asset_title": r["title"], "code": code, "title": title, "observation": observation,
            "consequence": consequence, "origin": origin, "origin_label": AUTHORITY[origin], "evidence_ids": [e for e in evidence if e],
            "rule_ids": list(rules), "checks": [CHECKS[c] for c in checks], "source_severity": source_severity,
            "source_status": source_status, "signal_id": signal_id, "next_action": next_action,
            "impact": "Unknown: the workbook does not measure the effect on results or on the people who use this report.",
            "owner": r["owner"], "owner_state": r["owner_state"], "case_ids": r.get("case_ids", [])}


SIGNAL_RISKS = {
    "HIGH_REACH_UNENDORSED": ("High reach without endorsement", ["RULE-005"],
                              "Many people may read figures from a report nobody has certified or reviewed.",
                              "Record a trust review, or ask for certification or promotion."),
    "SELF_SERVICE_HIGH_REACH": ("Self-service report with high reach", ["RULE-005"],
                                "A self-service report reaches a wide audience without central review.",
                                "Record a trust review or move it under central BI."),
    "MIGRATION_CANDIDATE": ("Migration candidate", ["RULE-006"],
                            "A migration could copy content that should be rationalised first.",
                            "Record the rationalisation decision before any migration."),
    "LIFECYCLE_REVIEW": ("Lifecycle review flagged", ["RULE-008"],
                         "A keep, retire or consolidate decision is pending; it needs cited evidence when it is made.",
                         "Open an owner review or record the lifecycle decision with its evidence."),
    "MISSING_OWNER": ("Missing owner signal", ["RULE-003"],
                      "Nobody may be accountable for corrections or questions about this report.",
                      "Assign an accountable owner."),
}


def asset_risks(r: dict, evidence: list[dict]) -> list[dict]:
    proj = be.projection()
    ev = {i["kind"]: [] for i in evidence}
    for i in evidence:
        ev[i["kind"]].append(i["id"])
    first = lambda kind: (ev.get(kind) or [None])[0]
    out = []
    if r["origin"] == "workbook":
        if r["variant_kpi_ids"]:
            fams = {}
            for k in r["kpi_ids"]:
                kk = proj["kpis"].get(k)
                if kk:
                    fams.setdefault(kk["canonical_metric"], []).append(k)
            parts = []
            for v in r["variant_kpi_ids"]:
                fam = proj["kpis"][v]["canonical_metric"]
                same = fams.get(fam, [])
                parts.append(f"{len(same)} {fam} definitions are bound to this report ({', '.join(same)})" if len(same) > 1
                             else f"{v} uses a {fam} definition marked as a conflict")
            out.append(_risk(r, "definition", "Definition conflict", "; ".join(dict.fromkeys(parts)) + ".",
                             "Figures labelled with the same KPI name may not match the governed definition, so comparisons across "
                             "reports could rest on different numbers. The workbook does not quantify the difference.",
                             origin="analytiq_check", evidence=[f"ev-check-DEF-1-{r['id']}"], rules=["RULE-002"], checks=["DEF-1"],
                             next_action="Check for a documented exception, then route the binding to the KPI steward and the report owner."))
        if r["scope"] and r["scope"]["mismatch"]:
            s = r["scope"]
            out.append(_risk(r, "scope", "Report and model scope differ",
                             f"The report declares {r['product']} / {r['market_name'] or r['market']}, but its model {r['model']['id']} "
                             f"covers {s['model_product']} / {s['model_region']}.",
                             "Someone reusing this report may read figures built for a different product or region. SCOPE-1 detects the "
                             "mismatch; it does not prove a policy breach.",
                             origin="analytiq_check", evidence=[f"ev-check-SCOPE-1-{r['id']}"], checks=["SCOPE-1"],
                             next_action="Before reuse, the owner confirms which model and filters the report actually reads."))
        if r["model"] and r["model"].get("refresh_status") in ("warning", "failed"):
            out.append(_risk(r, "refresh", "Model refresh issue", f"Model {r['model']['id']} refresh status is {r['model']['refresh_status']}.",
                             "Figures may be older than readers expect. The workbook has no refresh timestamps.",
                             origin="source_observation", evidence=[first("model")], source_status=r["model"]["refresh_status"],
                             next_action="Ask the model owner to restore the refresh."))
        if "chronology" in r["issues"]:
            out.append(_risk(r, "chronology", "Source date anomaly",
                             f"Last modified {r['modified']['value']} is before created {r['created']['value']} in the workbook.",
                             "Age-based judgments about this report (stale, recently changed) may be wrong.", origin="source_observation",
                             evidence=[first("asset_record")], next_action="Ask the owner or the catalogue team to confirm the dates."))
        for s in proj["signals"][r["id"]]:
            title, rules, consequence, action = SIGNAL_RISKS.get(s["signal_code"], (s["signal_code"].replace("_", " ").capitalize(), [], "", ""))
            out.append(_risk(r, s["signal_code"].lower(), title,
                             f"Imported signal {s['signal_id']} ({s['signal_code']}) detected by {s['detected_by'].replace('_', ' ')}: "
                             f"{s['severity']} severity, {s['status']} in the source.",
                             consequence, origin="source_observation", evidence=[f"ev-governance_signals-{s['row']}"], rules=rules,
                             source_severity=s["severity"], source_status=s["status"], signal_id=s["signal_id"], next_action=action))
    if r["owner_state"] != "active" and r["origin"] != "generated":
        out.append(_risk(r, "owner", "No active accountable owner",
                         "No owner is on record." if r["owner_state"] == "absent" else f"Owner {r['owner']['id']} is {r['owner'].get('status')}.",
                         "Nobody is accountable for corrections or questions about this report.", origin="analytiq_check",
                         evidence=[first("asset_record"), first("owner")], rules=["RULE-003"], next_action="Assign an active accountable owner."))
    if r.get("pair_ids"):
        pair = proj["pairs"][r["pair_ids"][0]]
        other = next(a for a in pair["assets"] if a != r["id"])
        out.append(_risk(r, "consolidation", "Consolidation candidate",
                         f"Shares {len(pair['shared_kpi_ids'])} approved KPIs with {other} for the same product and market.",
                         "Two reports may answer the same question with separate maintenance.", origin="analytiq_check",
                         evidence=[i["id"] for i in evidence if i["kind"] == "kpi_binding" and i["value"]["kpi_id"] in pair["shared_kpi_ids"]],
                         checks=["PAIR-1"], next_action="Compare the pair and start or open the owner review."))
    return out


async def _events(store, subject: str) -> list[dict]:
    return sorted(await be._find(store, EVENTS, {"subject": subject}), key=lambda e: e["seq"])


def review_state(events: list[dict]) -> dict:
    state = {"status": "not_reviewed", "label": "Not reviewed", "assignee": None, "seq": events[-1]["seq"] if events else 0,
             "last_assessment": None, "evidence_requested": None}
    for e in events:
        if e["kind"] == "assign":
            state.update(status="in_review", label=f"Review assigned to {e['assignee_name']}",
                         assignee={"id": e["assignee_id"], "name": e["assignee_name"]})
        elif e["kind"] == "request_evidence":
            state.update(status="evidence_requested", label="Evidence requested from the owner", evidence_requested=e["note"])
        elif e["kind"] == "assessment":
            state["last_assessment"] = {"id": e["_id"], "judgment": e["judgment"], "judgment_label": JUDGMENTS[e["judgment"]],
                                        "actor_name": e["actor_name"], "at": e["at"], "reason": e["reason"]}
            closed = e["judgment"] in CLOSING
            state.update(status="closed" if closed else "reviewed",
                         label=("Closed: " if closed else "Reviewed: ") + JUDGMENTS[e["judgment"]].lower())
    return state


JUDGMENTS = {"clear": "No finding after review", "needs_action": "Needs action", "remediated": "Remediation verified",
             "exception": "Covered by an accepted exception", "not_applicable": "Guidance does not apply"}
CLOSING = {"clear", "remediated", "exception", "not_applicable"}


# --------------------------------------------------------------------------- applicability (workbook rules and registered documents)

def _assess(doc: dict, status: str, result: str | None, facts: list[tuple[str, str | None]], *, reason: str = "",
            risk_ids: list[str] = (), clause: dict | None = None, mapping: dict | None = None, exception: dict | None = None) -> dict:
    return {"doc_id": doc["id"], "title": doc["title"], "authority": doc["authority"], "authority_label": doc["authority_label"],
            "priority": doc.get("priority"), "status": status, "result": result, "reason": reason, "risk_ids": list(risk_ids),
            "facts": [{"text": t, "evidence_id": e} for t, e in facts], "clause": clause, "mapping": mapping, "exception": exception}


RESULT_LABELS = {"finding": "Finding", "clear": "Assessed: no finding", "needs_evidence": "Evidence missing",
                 "exception": "Exception in force", "expired_exception": "Exception expired: reassess", "limitation": "Cannot be checked"}
STATUS_LABELS = {"applies": "Applies", "undetermined": "Applicability undetermined", "not_applicable": "Does not apply"}


def assess_rules(r: dict, evidence: list[dict], risks: list[dict], excs: list[dict], cases: list[dict], at: str) -> list[dict]:
    rules = workbook_rules()
    ev = {}
    for i in evidence:
        ev.setdefault(i["kind"], []).append(i)
    first = lambda kind: (ev.get(kind) or [{}])[0].get("id")
    risk_by = {x["code"]: x for x in risks}
    signals = [i for i in ev.get("source_signal", [])]
    sig_codes = {i["value"]["signal_code"]: i for i in signals}
    clause = lambda rid: _clause_view(rules[rid], rules[rid]["revisions"][0], "1")
    out = []
    # RULE-001 Reuse before build
    d = rules["RULE-001"]
    if r["origin"] == "generated":
        out.append(_assess(d, "applies", "clear", [("Built after Ask recommended a new build; the reuse search is in that run.", first("approved_brief"))],
                           clause=clause("RULE-001")))
    else:
        out.append(_assess(d, "undetermined", "limitation", [], clause=clause("RULE-001"),
                           reason="No creation decision is recorded for this report, so its reuse search cannot be checked."))
    # RULE-002 Canonical KPI first
    d = rules["RULE-002"]
    binds = ev.get("kpi_binding", []) or ev.get("kpi_definition", []) or ev.get("approved_brief", [])
    if not r["kpi_ids"]:
        out.append(_assess(d, "not_applicable", None, [], reason="No KPI binding is recorded for this report.", clause=clause("RULE-002")))
    else:
        facts = [(i["label"], i["id"]) for i in binds]
        variants = r.get("variant_kpi_ids") or []
        if not variants:
            out.append(_assess(d, "applies", "clear", facts, clause=clause("RULE-002")))
        else:
            mine = [e for e in excs if r["id"] in e["asset_ids"] and e["rule_ref"] == "RULE-002" and (e.get("kpi_id") in variants or not e.get("kpi_id"))]
            states = [(e, _exception_state(e, at)) for e in mine]
            active = next((e for e, s in states if s == "active"), None)
            expired = next((e for e, s in states if s == "expired"), None)
            if active:
                out.append(_assess(d, "applies", "exception", facts, clause=clause("RULE-002"), exception=_exc_view(active, at)))
            else:
                out.append(_assess(d, "applies", "expired_exception" if expired else "finding", facts, clause=clause("RULE-002"),
                                   risk_ids=[risk_by["definition"]["id"]] if "definition" in risk_by else [],
                                   exception=_exc_view(expired, at) if expired else None,
                                   reason="No documented exception covers this report and KPI." if not expired else "The exception has expired."))
    # RULE-003 Owner required
    d = rules["RULE-003"]
    ws = next(iter(ev.get("workspace", [])), None)
    if not ws:
        out.append(_assess(d, "undetermined", None, [], clause=clause("RULE-003"),
                           reason="No workspace metadata establishes whether this is production analytics."))
    elif ws["value"]["environment"] not in ("Production", "Certified"):
        out.append(_assess(d, "not_applicable", None, [(ws["label"], ws["id"])], clause=clause("RULE-003"),
                           reason=f"Workspace environment is {ws['value']['environment']}, not production."))
    else:
        ok = r["owner_state"] == "active"
        facts = [(ws["label"], ws["id"]), (f"Accountable owner: {r['owner']['name']} ({r['owner'].get('status', 'unknown')})" if r["owner"] else "No owner on record",
                                          first("owner") or first("asset_record"))]
        out.append(_assess(d, "applies", "clear" if ok else "finding", facts, clause=clause("RULE-003"),
                           risk_ids=[risk_by["owner"]["id"]] if not ok and "owner" in risk_by else []))
    # RULE-004 Lineage required
    d = rules["RULE-004"]
    recommendation = (["marked for retirement"] if r.get("lifecycle") == "candidate_retire" else []) + \
                     (["consolidation candidate"] if r.get("pair_ids") else []) + (["migration candidate"] if "MIGRATION_CANDIDATE" in sig_codes else [])
    important = (f"endorsement {r.get('endorsement')}" if r.get("endorsement") in ("certified", "promoted") else
                 "open high-reach signal" if any(c in sig_codes and sig_codes[c]["value"]["status"] == "open" for c in ("HIGH_REACH_UNENDORSED", "SELF_SERVICE_HIGH_REACH")) else None)
    if not recommendation:
        out.append(_assess(d, "not_applicable", None, [], clause=clause("RULE-004"), reason="No lifecycle recommendation is recorded for this report."))
    elif not important:
        out.append(_assess(d, "undetermined", None, [], clause=clause("RULE-004"),
                           reason=f"A recommendation exists ({', '.join(recommendation)}), but nothing establishes that the report is important."))
    else:
        up = [i for i in ev.get("lineage", []) if i["value"]["target_id"] == r["id"]]
        facts = [(f"Recommendation: {', '.join(recommendation)}", first("asset_record")), (f"Importance established by {important}", first("asset_record"))]
        facts += [(i["label"], i["id"]) for i in up]
        facts.append(("Downstream impact beyond the workbook lineage is unknown.", None))
        out.append(_assess(d, "applies", "clear" if up else "needs_evidence", facts, clause=clause("RULE-004"),
                           reason="" if up else "No upstream lineage is recorded."))
    # RULE-005 High reach requires trust
    d = rules["RULE-005"]
    reach = [sig_codes[c] for c in ("HIGH_REACH_UNENDORSED", "SELF_SERVICE_HIGH_REACH") if c in sig_codes]
    if not reach:
        out.append(_assess(d, "not_applicable", None, [], clause=clause("RULE-005"),
                           reason="No high-reach signal; the workbook gives no reach threshold to apply instead."))
    else:
        facts = [(i["label"], i["id"]) for i in reach] + [(f"Endorsement: {r.get('endorsement') or 'none'}", first("asset_record"))]
        trusted = r.get("endorsement") in ("certified", "promoted")
        reviewed = [x for x in risks if x["code"] in ("high_reach_unendorsed", "self_service_high_reach") and (x.get("review") or {}).get("status") == "closed"]
        rids = [x["id"] for x in risks if x["code"] in ("high_reach_unendorsed", "self_service_high_reach")]
        if trusted:
            out.append(_assess(d, "applies", "clear", facts, clause=clause("RULE-005")))
        elif reviewed:
            out.append(_assess(d, "applies", "clear", facts + [(f"Documented review {reviewed[0]['review']['last_assessment']['id']}", None)], clause=clause("RULE-005")))
        else:
            out.append(_assess(d, "applies", "finding", facts, clause=clause("RULE-005"), risk_ids=rids,
                               reason="Not certified or promoted, and no qualifying review is recorded."))
    # RULE-006 Do not migrate waste
    d = rules["RULE-006"]
    if r.get("platform") != "Tableau":
        out.append(_assess(d, "not_applicable", None, [(f"Platform {r.get('platform')}", first("asset_record"))], clause=clause("RULE-006"),
                           reason="Not a Tableau asset; a retirement or lifecycle flag alone is not a migration decision."))
    elif r.get("lifecycle") != "legacy" and "MIGRATION_CANDIDATE" not in sig_codes:
        out.append(_assess(d, "not_applicable", None, [], clause=clause("RULE-006"), reason="No migration or legacy rationalisation is recorded."))
    else:
        facts = [(f"Tableau, lifecycle {r.get('lifecycle')}", first("asset_record"))]
        if "MIGRATION_CANDIDATE" in sig_codes:
            facts.append((sig_codes["MIGRATION_CANDIDATE"]["label"], sig_codes["MIGRATION_CANDIDATE"]["id"]))
        decided = [c for c in cases if c["status"] == "closed"]
        out.append(_assess(d, "applies", "clear" if decided else "needs_evidence", facts, clause=clause("RULE-006"),
                           risk_ids=[x["id"] for x in risks if x["code"] == "migration_candidate"],
                           reason="" if decided else "No rationalisation decision is recorded before migration."))
    # RULE-007 AI-ready semantics
    d = rules["RULE-007"]
    if r["origin"] == "generated":
        b = first("approved_brief")
        out.append(_assess(d, "applies", "clear", [("Built for agentic analytics in Ask, with named measures, units and a monthly date grain", b)],
                           clause=clause("RULE-007")))
    else:
        out.append(_assess(d, "not_applicable", None, [], clause=clause("RULE-007"),
                           reason="No record that this report feeds agentic analytics. A healthy refresh would not establish semantic readiness."))
    # RULE-008 Explain every lifecycle action
    d = rules["RULE-008"]
    decided = [c for c in cases if c["status"] == "closed"]
    if r["origin"] == "generated":
        out.append(_assess(d, "applies", "clear", [("New-build recommendation traced in its Ask run, with the six analysis steps", first("approved_brief"))],
                           clause=clause("RULE-008")))
    elif decided:
        out.append(_assess(d, "applies", "clear", [(f"Decision in {c['id']}: {c['decision']['outcome_label']}", None) for c in decided],
                           clause=clause("RULE-008")))
    else:
        out.append(_assess(d, "undetermined", "limitation", [], clause=clause("RULE-008"),
                           reason="No lifecycle decision has been traced for this report yet."))
    return out


def _exc_view(e: dict | None, at: str) -> dict | None:
    if not e:
        return None
    return {"id": e["_id"], "rule_ref": e["rule_ref"], "kpi_id": e.get("kpi_id"), "revision": e.get("revision"), "asset_ids": e["asset_ids"],
            "rationale": e["rationale"], "expires": e["expires"], "reference": e.get("reference"), "status": e["status"],
            "state": _exception_state(e, at), "proposed_by": e["actor_name"], "decided_by": e.get("decided_by"), "decided_at": e.get("decided_at")}


def assess_documents(r: dict, evidence: list[dict], docs: dict[str, dict], maps: list[dict], excs: list[dict],
                     subjects: dict[str, list[dict]], at: str) -> list[dict]:
    out = []
    ev = {}
    for i in evidence:
        ev.setdefault(i["kind"], []).append(i)
    for m in maps:
        if m["asset_id"] != r["id"] or m["doc_id"] not in docs:
            continue
        doc = docs[m["doc_id"]]
        rev = revision_at(doc, at)
        mapping = _map_view(m)
        if m["status"] != "accepted":
            out.append(_assess(doc, "undetermined", None, [], mapping=mapping,
                               reason="Mapping proposed and awaiting confirmation. It does not apply until a reviewer accepts it."))
            continue
        if not rev or m["clause_id"] not in rev["clauses"]:
            out.append(_assess(doc, "undetermined", None, [], mapping=mapping,
                               reason="No revision of this document is effective on the requested date."))
            continue
        clause = _clause_view(doc, rev, m["clause_id"])
        facts = [(f"Explicit mapping {m['_id']} proposed by {m['actor_name']}, accepted by {m['decided_by']}: {m['reason']}", None)]
        facts += [(i["label"], i["id"]) for i in ev.get("asset_record", [])[:1] + ev.get("workspace", [])[:1]]
        ws = next(iter(ev.get("workspace", [])), None)
        if ws and ws["value"]["environment"] not in ("Production", "Certified"):
            out.append(_assess(doc, "not_applicable", None, facts, clause=clause, mapping=mapping,
                               reason="Mapped, but the clause's scope requires a production workspace."))
            continue
        subject = clause_subject(doc["id"], m["clause_id"], r["id"])
        state = review_state(subjects.get(subject, []))
        linked = [i for i in evidence if i.get("clause_ref") == f"{doc['id']}#{m['clause_id']}" and i.get("status") != "superseded"]
        exc = next((e for e in excs if r["id"] in e["asset_ids"] and e["rule_ref"] == f"{doc['id']}#{m['clause_id']}"), None)
        if exc and _exception_state(exc, at) == "active":
            result = "exception"
        elif state["last_assessment"]:
            j = state["last_assessment"]["judgment"]
            result = "clear" if j in ("clear", "remediated", "not_applicable") else "exception" if j == "exception" else "finding"
        elif exc and _exception_state(exc, at) == "expired":
            result = "expired_exception"
        else:
            result = "needs_evidence"
        a = _assess(doc, "applies", result, facts + [(i["label"], i["id"]) for i in linked], clause=clause, mapping=mapping,
                    exception=_exc_view(exc, at), reason="" if result != "needs_evidence" else
                    ("Supporting evidence is linked but not yet assessed." if linked else "No evidence for this clause has been submitted."))
        a["subject"] = subject
        a["review"] = state
        out.append(a)
    return out


def clause_subject(doc_id: str, clause_id: str, asset_id: str) -> str:
    return f"POL~{doc_id}~{clause_id}~{asset_id}"


def _map_view(m: dict) -> dict:
    return {"id": m["_id"], "doc_id": m["doc_id"], "clause_id": m["clause_id"], "asset_id": m["asset_id"], "status": m["status"],
            "criteria": m.get("criteria"), "reason": m["reason"], "proposed_by": m["actor_name"], "proposed_at": m["at"],
            "decided_by": m.get("decided_by"), "decided_at": m.get("decided_at"), "decision_reason": m.get("decision_reason")}


# --------------------------------------------------------------------------- one asset, assembled

class Context:
    """Everything a request needs, loaded once: inventory, documents, mappings, exceptions, review events."""

    async def load(self, request: Request):
        self.store = request.app.state.pipeline.store
        self.actor = be.resolve_actor(request)
        records, _ = await be.inventory(self.store)
        self.assets = scoped_assets(records, self.actor)
        self.docs = await documents(self.store, self.actor)
        self.maps = await be._find(self.store, MAPS, sort="_id")
        self.excs = await _exceptions(self.store)
        events = await be._find(self.store, EVENTS)
        self.subjects: dict[str, list[dict]] = {}
        for e in sorted(events, key=lambda e: e["seq"]):
            self.subjects.setdefault(e["subject"], []).append(e)
        self.cases = {c["_id"]: c for c in await be._find(self.store, be.CASES)}
        self.submitted = {s["_id"]: s for s in await be._find(self.store, SUBMITTED)}
        return self

    def asset(self, aid: str) -> dict:
        if aid not in self.assets:
            raise _not_found("dashboard")
        return self.assets[aid]

    async def evidence(self, r: dict) -> list[dict]:
        if r["origin"] == "workbook":
            items = list(workbook_evidence().get(r["id"], []))
        else:
            items = await _app_evidence(self.store, r, be.projection())
        items += [_submitted_view(s) for s in self.submitted.values() if s["asset_id"] == r["id"]]
        seen, out = set(), []
        for i in items:
            if i["id"] not in seen:
                seen.add(i["id"])
                out.append(i)
        return out

    async def governance(self, r: dict, at: str) -> dict:
        evidence = await self.evidence(r)
        risks = asset_risks(r, evidence)
        for x in risks:
            x["review"] = review_state(self.subjects.get(x["id"], []))
        cases = []
        for cid in r.get("case_ids", []) + [c for c, v in self.cases.items() if r["id"] in v["assets"] and v.get("status") == "closed"]:
            view = await be.case_view(self.store, cid)
            if view["id"] not in {c["id"] for c in cases}:
                cases.append(view)
        rules = assess_rules(r, evidence, risks, self.excs, cases, at)
        docs = assess_documents(r, evidence, self.docs, self.maps, self.excs, self.subjects, at)
        policies = docs + rules
        for p in policies:
            p["status_label"] = STATUS_LABELS[p["status"]]
            p["result_label"] = RESULT_LABELS.get(p["result"]) if p["result"] else None
        return {"evidence": evidence, "risks": risks, "policies": policies, "cases": cases}


def _actor_view(actor: dict | None) -> dict | None:
    return {"id": actor["id"], "name": actor["name"], "role": actor["role"]} if actor else None


def _permissions(actor: dict | None, r: dict | None = None) -> dict:
    role = actor["role"] if actor else None
    owner = bool(actor and r and r.get("owner") and r["owner"]["id"] == actor["id"] and r["owner_state"] == "active")
    return {"submit_evidence": owner, "review": role in ("governance_reviewer", "bi_steward"), "steward": role == "bi_steward",
            "approve": role == "governance_reviewer", "read_only": role in (None, "auditor", "employee")}


@router.get("/assets/{asset_id}")
async def asset_governance(asset_id: str, request: Request, at: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$")) -> dict:
    ctx = await Context().load(request)
    r = ctx.asset(asset_id)
    at = at or _today()
    g = await ctx.governance(r, at)
    missing = [{"policy": p["doc_id"], "text": p["reason"]} for p in g["policies"] if p["result"] == "needs_evidence"]
    requested = [{"risk": x["id"], "text": x["review"]["evidence_requested"]} for x in g["risks"] if x["review"]["status"] == "evidence_requested"]
    history = []
    for subject in [x["id"] for x in g["risks"]] + [p.get("subject") for p in g["policies"] if p.get("subject")]:
        for e in ctx.subjects.get(subject, []):
            history.append(_event_view(e))
    for s in g["evidence"]:
        if s["kind"] == "owner_submission":
            history.append({"id": s["id"], "kind": "evidence_submitted", "actor_name": s["submitted_by"], "at": s["observed_at"],
                            "text": f"Submitted evidence: {s['label']}"})
            for rv in s["reviews"]:
                history.append({"id": f"{s['id']}#{rv['seq']}", "kind": "evidence_review", "actor_name": rv["actor_name"], "at": rv["at"],
                                "text": f"{rv['decision'].replace('_', ' ').capitalize()}: {rv['note']}"})
    for m in ctx.maps:
        if m["asset_id"] == asset_id and m["doc_id"] in ctx.docs:
            history.append({"id": m["_id"], "kind": "mapping", "actor_name": m["actor_name"], "at": m["at"],
                            "text": f"Proposed mapping to {m['doc_id']} clause {m['clause_id']}"})
            if m.get("decided_at"):
                history.append({"id": m["_id"] + "#d", "kind": "mapping", "actor_name": m["decided_by"], "at": m["decided_at"],
                                "text": f"Mapping {m['status']}: {m.get('decision_reason', '')}"})
    for c in g["cases"]:
        history.append({"id": c["id"], "kind": "case", "actor_name": c["coordinator"], "at": c["created_at"],
                        "text": f"Owner review {c['id']}: {c['status_label']}", "case": c["id"]})
    history.sort(key=lambda h: h["at"] or "", reverse=True)
    return {
        "asset": {k: r.get(k) for k in ("id", "title", "origin", "type", "platform", "product", "market", "market_name", "owner",
                                        "owner_state", "issues", "lifecycle")},
        "as_of": at, "workbook": _workbook(), "actor": _actor_view(ctx.actor), "permissions": _permissions(ctx.actor, r),
        "evidence": [_strip(i) for i in g["evidence"]], "risks": g["risks"],
        "policies": [p for p in g["policies"] if p["status"] != "not_applicable"],
        "not_applicable": [p for p in g["policies"] if p["status"] == "not_applicable"],
        "missing_evidence": missing + requested, "history": history,
        "unavailable": _unavailable(r),
        "finding_map": {code: [x["id"] for x in g["risks"] if x["code"] in FINDING_RISKS.get(code, (code,))
                               or (code == "signal" and x["signal_id"] and x["source_status"] == "open")] for code in r["issues"]},
        "mapping_tasks": [_map_view(m) for m in ctx.maps if m["asset_id"] == asset_id and m["status"] == "proposed"
                          and m["doc_id"] in ctx.docs] if _permissions(ctx.actor)["steward"] or _permissions(ctx.actor)["approve"] else [],
    }


FINDING_RISKS = {"needs_owner": ("owner", "missing_owner"), "retirement": ("lifecycle_review",), "signal": ()}


def _unavailable(r: dict) -> list[str]:
    if r["origin"] == "workbook":
        return ["Refresh timestamps (the workbook records status and cadence only)", "Exact open times (only monthly usage counts)",
                "Who created the report"]
    if r["origin"] == "generated":
        return ["Workspace and production status (built inside AnalytIQ)", "Imported usage (only AnalytIQ opens)"]
    return ["Workspace and production status", "Imported usage", "Creation date"]


def _strip(i: dict) -> dict:
    return {k: v for k, v in i.items() if k != "record"}


def _event_view(e: dict) -> dict:
    text = {"assign": lambda: f"Review assigned to {e['assignee_name']}", "request_evidence": lambda: f"Evidence requested: {e['note']}",
            "assessment": lambda: f"{JUDGMENTS[e['judgment']]}: {e['reason']}"}[e["kind"]]()
    return {"id": e["_id"], "kind": e["kind"], "actor_name": e["actor_name"], "at": e["at"], "text": text, "subject": e["subject"],
            "assessment": e["_id"] if e["kind"] == "assessment" else None}


# --------------------------------------------------------------------------- portfolio index (evidence, policies, risks)

@router.get("")
async def index(request: Request, tab: Literal["policies", "risks", "evidence"] = "policies", q: str = "",
                origin: str | None = None, platform: str | None = None, issue: str | None = None, lifecycle: str | None = None,
                owner_state: str | None = None, product: str | None = None, market: str | None = None,
                page: int = Query(1, ge=1), size: int = Query(25, ge=1, le=100),
                at: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$")) -> dict:
    ctx = await Context().load(request)
    at = at or _today()
    scope = [r for r in ctx.assets.values() if be._matches(r, "", origin, platform, issue, lifecycle, owner_state, product, market)]
    words = q.casefold().split()
    hit = lambda *parts: all(w in " ".join(str(p) for p in parts if p).casefold() for w in words)
    rows: list[dict] = []
    if tab == "policies":
        entries: dict[str, dict] = {}
        for r in scope:
            g = await ctx.governance(r, at)
            for p in g["policies"]:
                if p["status"] != "applies":
                    continue
                e = entries.setdefault(p["doc_id"], {"id": p["doc_id"], "title": p["title"], "authority_label": p["authority_label"],
                                                     "priority": p.get("priority"), "assets": [], "findings": 0, "search": []})
                e["assets"].append({"id": r["id"], "title": r["title"], "result": p["result"]})
                e["findings"] += p["result"] in ("finding", "expired_exception", "needs_evidence")
                e["search"].append(" ".join(str(x) for x in (r["id"], r["title"], (r["owner"] or {}).get("name"), " ".join(r["kpi_ids"]))))
        for e in entries.values():
            doc = ctx.docs.get(e["id"]) or workbook_rules().get(e["id"])
            rev = revision_at(doc, at) if doc and doc.get("revisions") else None
            if not hit(e["id"], e["title"], e["authority_label"], " ".join(e["search"])):
                e["assets"] = []  # out of the search, so out of the count
                continue
            rows.append({"id": e["id"], "title": e["title"], "authority_label": e["authority_label"], "priority": e["priority"],
                         "version": (rev or {}).get("version"), "revision": (rev or {}).get("revision"),
                         "effective_from": (rev or {}).get("effective_from"), "affected": len(e["assets"]), "with_findings": e["findings"],
                         "sample": e["assets"][:3]})
        rows.sort(key=lambda x: (-x["with_findings"], x["id"]))
        distinct = len({a["id"] for e in entries.values() for a in e["assets"]})  # same rows as the table
    elif tab == "risks":
        for r in scope:
            ev = await ctx.evidence(r)
            for x in asset_risks(r, ev):
                x["review"] = review_state(ctx.subjects.get(x["id"], []))
                if hit(x["id"], x["title"], x["observation"], r["id"], r["title"], (r["owner"] or {}).get("name"), " ".join(r["kpi_ids"]), " ".join(x["rule_ids"])):
                    rows.append({k: x[k] for k in ("id", "asset_id", "asset_title", "title", "observation", "origin_label", "source_severity",
                                                   "source_status", "rule_ids", "review", "owner", "owner_state", "signal_id")}
                                | {"rule_priority": _rule_priority(x["rule_ids"]), "action_priority": action_priority(x)})
        rows.sort(key=lambda x: (PRIORITY[x["action_priority"]], x["asset_id"], x["id"]))
        distinct = len({x["asset_id"] for x in rows})
    else:
        seen: dict[str, dict] = {}
        for r in scope:
            for i in await ctx.evidence(r):
                if not hit(i["id"], i["label"], r["id"], r["title"], (r["owner"] or {}).get("name"), i["source"].get("sheet"), i["source"].get("record_id")):
                    continue
                e = seen.setdefault(i["id"], {**_strip(i), "assets": []})
                e["assets"].append({"id": r["id"], "title": r["title"]})
        rows = sorted(seen.values(), key=lambda i: (i["kind"] != "owner_submission", i["source"].get("sheet") or "", i["source"].get("row") or 0, i["id"]))
        distinct = len({a["id"] for i in rows for a in i["assets"]})
        for i in rows:
            i["asset_count"] = len(i["assets"])
            i["assets"] = i["assets"][:3]
    start = (page - 1) * size
    return {"tab": tab, "rows": rows[start:start + size], "total": len(rows), "page": page, "size": size,
            "pages": max(1, -(-len(rows) // size)), "distinct_assets": distinct, "scope_assets": len(scope),
            "portfolio_assets": len(ctx.assets), "as_of": at, "workbook": _workbook(), "permissions": _permissions(ctx.actor),
            "mapping_tasks": [_map_view(m) for m in ctx.maps if m["status"] == "proposed" and m["doc_id"] in ctx.docs]
            if (_permissions(ctx.actor)["steward"] or _permissions(ctx.actor)["approve"]) else []}


def _rule_priority(rule_ids: list[str]) -> str | None:
    rules = workbook_rules()
    ps = [rules[r]["priority"] for r in rule_ids if r in rules]
    return min(ps, key=lambda p: PRIORITY[p]) if ps else None


def action_priority(x: dict) -> str:
    """AnalytIQ's own ordering for the BI head's queue, kept apart from source severity and rule priority."""
    if x["review"]["status"] == "closed":
        return "low"
    if x["source_status"] == "acknowledged":
        return "low"
    if x["source_severity"] == "high" or (x["origin"] == "analytiq_check" and _rule_priority(x["rule_ids"]) == "high"):
        return "high"
    return "medium"


# --------------------------------------------------------------------------- single items

@router.get("/evidence/{evidence_id}")
async def evidence_detail(evidence_id: str, request: Request, asset: str) -> dict:
    ctx = await Context().load(request)
    r = ctx.asset(asset)
    items = {i["id"]: i for i in await ctx.evidence(r)}
    if evidence_id not in items:
        raise _not_found("evidence")
    item = dict(items[evidence_id])
    src = item["source"]
    if src.get("kind") == "workbook" and item["kind"] != "source_record":
        try:
            item["record"] = _row(src["sheet"].lower(), src["row"])
        except (KeyError, IndexError):
            item["availability"] = "source_unavailable"
    item["linked"] = [_strip(items[l]) if l in items else _linked(l) for l in item["links"]]
    item["asset"] = {"id": r["id"], "title": r["title"]}
    item["permissions"] = _permissions(ctx.actor, r)
    return item


def _linked(eid: str) -> dict:
    m = re.match(r"^ev-markets-(\d+)$", eid)
    if m:
        return _strip(_market_item(int(m.group(1))))
    return {"id": eid, "label": "Linked record", "availability": "source_unavailable"}


@router.get("/risks/{risk_id}")
async def risk_detail(risk_id: str, request: Request, at: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$")) -> dict:
    ctx = await Context().load(request)
    m = re.match(r"^RISK-(.+?)-([A-Za-z_]+|SIG-\d+)$", risk_id)
    if not m:
        raise _not_found("risk")
    r = ctx.asset(m.group(1))
    at = at or _today()
    g = await ctx.governance(r, at)
    x = next((x for x in g["risks"] if x["id"] == risk_id), None)
    if not x:
        raise _not_found("risk")
    by_id = {i["id"]: i for i in g["evidence"]}
    evidence = []
    for eid in x["evidence_ids"]:
        i = by_id.get(eid)
        if i:
            evidence.append(_strip(i))
            evidence += [_strip(by_id[l]) if l in by_id else _linked(l) for l in i["links"] if l not in x["evidence_ids"]]
    evidence += [_strip(i) for i in g["evidence"] if i.get("finding_id") == risk_id]
    rules = workbook_rules()
    guidance = [_clause_view(rules[rid], rules[rid]["revisions"][0], "1") | {"priority": rules[rid]["priority"]} for rid in x["rule_ids"]]
    related = [p for p in g["policies"] if risk_id in p["risk_ids"]]
    return {**x, "evidence": evidence, "guidance": guidance, "assessments": related, "as_of": at,
            "rule_priority": _rule_priority(x["rule_ids"]), "action_priority": action_priority(x),
            "history": [_event_view(e) for e in ctx.subjects.get(risk_id, [])], "permissions": _permissions(ctx.actor, r),
            "evidence_hash": _digest([i.get("value") for i in evidence] + [r["owner"]]),
            "cases": [c for c in g["cases"] if c["id"] in x["case_ids"]], "pair_ids": r.get("pair_ids", [])}


@router.get("/documents/{doc_id}")
async def document_detail(doc_id: str, request: Request, asset: str | None = None, q: str = "",
                          at: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$")) -> dict:
    ctx = await Context().load(request)
    at = at or _today()
    doc = ctx.docs.get(doc_id) or workbook_rules().get(doc_id)
    if not doc:
        raise _not_found("document")
    rev = revision_at(doc, at)
    affected, why = [], None
    for r in ctx.assets.values():
        if doc["authority"] != "challenge_workbook" and not any(m["doc_id"] == doc_id and m["asset_id"] == r["id"] for m in ctx.maps):
            continue
        g = await ctx.governance(r, at)
        p = next((p for p in g["policies"] if p["doc_id"] == doc_id), None)
        if p and p["status"] == "applies":
            affected.append({"id": r["id"], "title": r["title"], "owner": (r["owner"] or {}).get("name"), "result": p["result"],
                             "result_label": RESULT_LABELS.get(p["result"])})
        if asset and r["id"] == asset:
            why = p
    if asset and asset not in ctx.assets:
        raise _not_found("dashboard")
    words = q.casefold().split()
    if words:
        affected = [a for a in affected if all(w in f"{a['id']} {a['title']} {a['owner']}".casefold() for w in words)]
    perms = _permissions(ctx.actor)
    return {"id": doc["id"], "title": doc["title"], "authority": doc["authority"], "authority_label": doc["authority_label"],
            "issuer": doc.get("issuer"), "owner": doc.get("owner"), "accountable_team": doc.get("accountable_team"),
            "priority": doc.get("priority"), "note": doc.get("note"), "as_of": at,
            "current": rev and {**{k: v for k, v in rev.items() if k not in ("_id",)}, "status": "Effective" if rev else None},
            "revisions": [{k: v for k, v in r.items() if k != "_id"} for r in doc["revisions"]],
            "why": why, "affected": affected, "affected_count": len(affected),
            "mappings": [_map_view(m) for m in ctx.maps if m["doc_id"] == doc_id] if perms["steward"] or perms["approve"] else
                        [_map_view(m) for m in ctx.maps if m["doc_id"] == doc_id and m["status"] == "accepted"],
            "exceptions": [_exc_view(e, at) for e in ctx.excs if e["rule_ref"].split("#")[0] == doc_id],
            "permissions": perms}


@router.get("/documents/{doc_id}/revisions/{revision}/original")
async def document_original(doc_id: str, revision: int, request: Request) -> dict:
    ctx = await Context().load(request)
    doc = ctx.docs.get(doc_id)
    if not doc:
        if doc_id in workbook_rules():
            rule = workbook_rules()[doc_id]
            return {"title": rule["title"], "text": rule["revisions"][0]["clauses"]["1"]["text"], "source": rule["revisions"][0]["source"],
                    "availability": "available"}
        raise _not_found("document")
    rev = next((r for r in doc["revisions"] if r["revision"] == revision), None)
    if not rev:
        raise _not_found("revision")
    src = sources().get(rev["source_ref"])
    path = SOURCES_DIR / src["file"] if src else None
    if not path or not path.exists():
        return {"title": doc["title"], "text": None, "availability": "unavailable", "source": rev.get("source")}
    return {"title": doc["title"], "text": path.read_text(), "availability": "available", "source": rev.get("source"),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()[:12]}


@router.get("/assessments/{assessment_id}")
async def assessment_detail(assessment_id: str, request: Request) -> dict:
    """Reopen a recorded judgment exactly as it was made, with what has changed since."""
    ctx = await Context().load(request)
    e = next((e for es in ctx.subjects.values() for e in es if e["_id"] == assessment_id and e["kind"] == "assessment"), None)
    if not e or e["asset_id"] not in ctx.assets:
        raise _not_found("assessment")
    snap = e["snapshot"]
    if snap.get("clause") and snap["clause"]["authority"] != "challenge_workbook" and snap["clause"]["doc_id"] not in ctx.docs:
        raise _not_found("assessment")  # the governing document is not visible to this viewer
    changes = []
    clause = snap.get("clause")
    if clause and clause["doc_id"] in ctx.docs:
        cur = revision_at(ctx.docs[clause["doc_id"]], _today())
        if cur and cur["revision"] != clause["revision"]:
            changes.append(f"{clause['doc_id']} is now at revision {cur['revision']} (effective {cur['effective_from']}). "
                           f"This assessment used revision {clause['revision']}.")
    r = ctx.assets[e["asset_id"]]
    current = {i["id"]: i for i in await ctx.evidence(r)}
    for i in snap["evidence"]:
        now = current.get(i["id"])
        if not now:
            changes.append(f"{i['id']} is no longer available; the cited values are kept here.")
        elif _digest(now.get("value")) != _digest(i.get("value")):
            changes.append(f"{i['id']} has changed since the assessment.")
    if (snap.get("owner") or {}).get("id") != (r["owner"] or {}).get("id"):
        changes.append("The accountable owner has changed since the assessment.")
    return {"id": e["_id"], "subject": e["subject"], "asset": {"id": r["id"], "title": r["title"]}, "judgment": e["judgment"],
            "judgment_label": JUDGMENTS[e["judgment"]], "reason": e["reason"], "actor_name": e["actor_name"], "actor_id": e["actor_id"],
            "at": e["at"], "snapshot": snap, "changes_since": changes}


# --------------------------------------------------------------------------- writes

class RegisterDoc(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_ref: str
    doc_id: str = Field(pattern=r"^[A-Z0-9-]{3,40}$")
    title: str = Field(min_length=3, max_length=200)
    issuer: str = Field(min_length=3, max_length=200)
    accountable_team: str = Field(min_length=2, max_length=200)
    version: str = Field(min_length=1, max_length=20)
    effective_from: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    clause_id: str = Field(min_length=1, max_length=10)
    excerpt: str = Field(min_length=10, max_length=2000)
    expected_revision: int = Field(ge=0)


def _verify_source(body: RegisterDoc) -> dict:
    """Authority, version, dates and wording must match the permitted source supplied. AnalytIQ does not approve documents."""
    src = sources().get(body.source_ref)
    if not src:
        raise HTTPException(422, "Choose a permitted source. Only registered, approved-for-publication sources can be used.")
    problems = [name for name, ok in (("document ID", src["doc_id"] == body.doc_id), ("title", src["title"] == body.title),
                                      ("issuer", src["issuer"] == body.issuer), ("accountable team", src["accountable_team"] == body.accountable_team),
                                      ("version", src["version"] == body.version), ("effective date", src["effective_from"] == body.effective_from),
                                      ("clause", body.clause_id in src["clauses"])) if not ok]
    if not problems and " ".join(body.excerpt.split()) not in " ".join(src["clauses"][body.clause_id]["text"].split()):
        problems.append("excerpt (it must be quoted from the clause)")
    if problems:
        raise HTTPException(422, "These do not match the source document: " + ", ".join(problems) + ".")
    return src


@router.get("/sources")
async def permitted_sources(request: Request) -> dict:
    _require(be.resolve_actor(request), "bi_steward")
    return {"sources": [{k: v for k, v in s.items() if k != "file"} for s in sources().values()]}


@router.post("/documents", status_code=201)
async def register_document(body: RegisterDoc, request: Request) -> dict:
    """Register a document (expected_revision 0) or publish its next revision (expected_revision = current)."""
    store = request.app.state.pipeline.store
    actor = _require(be.resolve_actor(request), "bi_steward")
    src = _verify_source(body)
    existing = next(iter(await be._find(store, DOCS, {"_id": body.doc_id})), None)
    revs = sorted(await be._find(store, REVS, {"doc_id": body.doc_id}), key=lambda r: r["revision"])
    current = revs[-1]["revision"] if revs else 0
    same = next((r for r in revs if r["source_ref"] == body.source_ref), None)
    if same:
        return {"document": body.doc_id, "revision": same["revision"], "created": False}  # a retry of the same registration
    if body.expected_revision != current:
        raise HTTPException(409, f"The document is at revision {current}. Reload before publishing.")
    if revs and body.effective_from <= revs[-1]["effective_from"]:
        raise HTTPException(422, "A new revision must take effect after the current one.")
    if not existing:
        await be._insert_once(store, DOCS, {"_id": body.doc_id, "title": src["title"], "authority": src["authority"],
                                            "issuer": src["issuer"], "accountable_team": src["accountable_team"], "owner": src["owner"],
                                            "access": src["access"], "access_roles": src.get("access_roles", []),
                                            "registered_by": actor["name"], "registered_at": _now()})
    rev = {"_id": f"{body.doc_id}:r{current + 1}", "doc_id": body.doc_id, "revision": current + 1, "version": src["version"],
           "effective_from": src["effective_from"], "status": src["status"], "source_ref": src["ref"],
           "clauses": src["clauses"], "excerpt": {"clause_id": body.clause_id, "text": body.excerpt},
           "source": {"kind": "bundled", "label": AUTHORITY[src["authority"]], "file": src["file"], "ref": src["ref"],
                      "sha256": hashlib.sha256((SOURCES_DIR / src["file"]).read_bytes()).hexdigest()[:12]},
           "registered_by": actor["name"], "registered_at": _now(), "supersedes": revs[-1]["_id"] if revs else None}
    _, inserted = await be._insert_once(store, REVS, rev)
    if not inserted:
        raise HTTPException(409, "Another revision was published meanwhile. Reload.")
    return {"document": body.doc_id, "revision": current + 1, "created": True}


class Mapping(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: str
    clause_id: str
    reason: str = Field(min_length=5, max_length=600)


@router.post("/documents/{doc_id}/mappings", status_code=201)
async def propose_mapping(doc_id: str, body: Mapping, request: Request) -> dict:
    ctx = await Context().load(request)
    actor = _require(ctx.actor, "bi_steward")
    doc = ctx.docs.get(doc_id)
    if not doc:
        raise _not_found("document")
    ctx.asset(body.asset_id)
    if not any(body.clause_id in r["clauses"] for r in doc["revisions"]):
        raise HTTPException(422, "This clause is not in the document.")
    doc_ = {"_id": f"MAP-{doc_id}-{body.clause_id}-{body.asset_id}", "doc_id": doc_id, "clause_id": body.clause_id,
            "asset_id": body.asset_id, "criteria": {"kind": "explicit_asset", "asset_id": body.asset_id}, "reason": body.reason.strip(),
            "status": "proposed", "actor_id": actor["id"], "actor_name": actor["name"], "at": _now()}
    saved, _ = await be._insert_once(ctx.store, MAPS, doc_)
    return _map_view(saved)


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["accepted", "rejected"]
    reason: str = Field(min_length=5, max_length=600)


@router.post("/mappings/{mapping_id}/decision")
async def decide_mapping(mapping_id: str, body: Decision, request: Request) -> dict:
    ctx = await Context().load(request)
    actor = _require(ctx.actor, "governance_reviewer")
    m = next((m for m in ctx.maps if m["_id"] == mapping_id and m["doc_id"] in ctx.docs), None)
    if not m:
        raise _not_found("mapping")
    if m["status"] != "proposed":
        if m["status"] == body.decision and m.get("decided_by") == actor["name"]:
            return _map_view(m)  # retry of the same decision
        raise HTTPException(409, f"This mapping is already {m['status']}.")
    if m["actor_id"] == actor["id"]:
        raise HTTPException(403, "The person who proposed a mapping cannot confirm it.")
    fields = {"status": body.decision, "decided_by": actor["name"], "decided_by_id": actor["id"], "decided_at": _now(),
              "decision_reason": body.reason.strip()}
    if not await _set_if(ctx.store, MAPS, mapping_id, {"status": "proposed"}, fields):
        raise HTTPException(409, "This mapping changed meanwhile. Reload.")
    return _map_view({**m, **fields})


async def _set_if(store, kind: str, doc_id: str, expect: dict, fields: dict) -> bool:
    """Compare-and-set on the stored fields: the write happens only if the record is still as the caller saw it."""
    if store.name == "mongodb":
        res = await store.db[kind].update_one({"_id": doc_id, **expect}, {"$set": fields})
        return res.modified_count == 1
    row = store.artifacts.setdefault(kind, {}).get(doc_id)
    if not row or any(row.get(k) != v for k, v in expect.items()):
        return False
    row.update(fields)
    return True


class ExceptionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_ids: list[str] = Field(min_length=1, max_length=20)
    rule_ref: str = Field(pattern=r"^(RULE-\d{3}|[A-Z0-9-]+#\w+)$")
    kpi_id: str | None = None
    rationale: str = Field(min_length=10, max_length=800)
    expires: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    reference: str = Field(min_length=3, max_length=300)


@router.post("/exceptions", status_code=201)
async def propose_exception(body: ExceptionIn, request: Request) -> dict:
    ctx = await Context().load(request)
    actor = _require(ctx.actor, "bi_steward")
    for a in body.asset_ids:
        ctx.asset(a)
    doc_id = body.rule_ref.split("#")[0]
    if doc_id not in ctx.docs and doc_id not in workbook_rules():
        raise _not_found("document")
    revision = None
    if doc_id in ctx.docs:
        cur = revision_at(ctx.docs[doc_id], _today())
        revision = cur and cur["revision"]
    key = _digest([sorted(body.asset_ids), body.rule_ref, body.kpi_id, body.expires, body.rationale])[:10]
    e = {"_id": f"EXC-{key}", "asset_ids": sorted(body.asset_ids), "rule_ref": body.rule_ref, "kpi_id": body.kpi_id,
         "revision": revision, "rationale": body.rationale.strip(), "expires": body.expires, "reference": body.reference.strip(),
         "status": "proposed", "actor_id": actor["id"], "actor_name": actor["name"], "at": _now()}
    saved, _ = await be._insert_once(ctx.store, EXCS, e)
    return _exc_view(saved, _today())


@router.post("/exceptions/{exception_id}/decision")
async def decide_exception(exception_id: str, body: Decision, request: Request) -> dict:
    ctx = await Context().load(request)
    actor = _require(ctx.actor, "governance_reviewer")
    e = next((e for e in ctx.excs if e["_id"] == exception_id), None)
    if not e:
        raise _not_found("exception")
    if e["status"] != "proposed":
        raise HTTPException(409, f"This exception is already {e['status']}.")
    fields = {"status": "approved" if body.decision == "accepted" else "rejected", "decided_by": actor["name"],
              "decided_at": _now(), "decision_reason": body.reason.strip()}
    if not await _set_if(ctx.store, EXCS, exception_id, {"status": "proposed"}, fields):
        raise HTTPException(409, "This exception changed meanwhile. Reload.")
    return _exc_view({**e, **fields}, _today())


class EvidenceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_seq: int = Field(ge=0)
    record_evidence_id: str | None = None
    reference: str = Field(default="", max_length=400)
    revision_or_section: str = Field(min_length=1, max_length=200)
    supports: str = Field(min_length=5, max_length=800)
    finding_id: str | None = None
    clause_ref: str | None = Field(default=None, pattern=r"^[A-Z0-9-]+#\w+$")
    supersedes: str | None = None


@router.post("/assets/{asset_id}/evidence", status_code=201)
async def submit_evidence(asset_id: str, body: EvidenceIn, request: Request) -> dict:
    ctx = await Context().load(request)
    r = ctx.asset(asset_id)
    actor = _require(ctx.actor, "owner")
    if not _permissions(actor, r)["submit_evidence"]:
        raise HTTPException(403, "Only the active accountable owner of this dashboard can add evidence here.")
    if not body.record_evidence_id and not body.reference.strip():
        raise HTTPException(422, "Select a source record or enter a reference.")
    if body.reference and re.match(r"^\w+://", body.reference) and not body.reference.startswith("https://"):
        raise HTTPException(422, "Only https references are permitted.")
    items = {i["id"] for i in await ctx.evidence(r)}
    if body.record_evidence_id and body.record_evidence_id not in items:
        raise HTTPException(422, "That source record is not part of this dashboard's evidence.")
    if body.clause_ref and body.clause_ref.split("#")[0] not in ctx.docs and body.clause_ref.split("#")[0] not in workbook_rules():
        raise _not_found("document")
    mine = sorted((s for s in ctx.submitted.values() if s["asset_id"] == asset_id), key=lambda s: s["seq"])
    seq = mine[-1]["seq"] if mine else 0
    payload = {k: v for k, v in body.model_dump().items() if k != "expected_seq"}
    if mine and body.expected_seq == seq - 1 and {k: mine[-1].get(k) for k in payload} == payload:
        return _submitted_view(mine[-1])  # the same submission, retried
    if body.expected_seq != seq:
        raise HTTPException(409, "Evidence on this dashboard changed meanwhile. Reload.")
    if body.supersedes and (body.supersedes not in ctx.submitted or ctx.submitted[body.supersedes]["asset_id"] != asset_id):
        raise HTTPException(422, "You can only supersede evidence on this dashboard.")
    doc = {"_id": f"EVS-{asset_id}-{seq + 1:04d}", "asset_id": asset_id, "seq": seq + 1, **payload,
           "reference": body.reference.strip(), "status": "statement", "actor_id": actor["id"], "actor_name": actor["name"],
           "at": _now(), "reviews": []}
    _, inserted = await be._insert_once(ctx.store, SUBMITTED, doc)
    if not inserted:
        raise HTTPException(409, "Evidence on this dashboard changed meanwhile. Reload.")
    if body.supersedes:
        await be._set(ctx.store, SUBMITTED, body.supersedes, {"status": "superseded", "superseded_by": doc["_id"]})
    return _submitted_view(doc)


class EvidenceReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["verified", "correction_requested"]
    note: str = Field(min_length=5, max_length=600)
    expected_reviews: int = Field(ge=0)


@router.post("/evidence/{evidence_id}/reviews", status_code=201)
async def review_evidence(evidence_id: str, body: EvidenceReview, request: Request) -> dict:
    ctx = await Context().load(request)
    actor = _require(ctx.actor, "governance_reviewer", "bi_steward")
    s = ctx.submitted.get(evidence_id)
    if not s or s["asset_id"] not in ctx.assets:
        raise _not_found("evidence")
    if s["status"] == "superseded":
        raise HTTPException(409, "This evidence was superseded. Review the newer item.")
    reviews = s.get("reviews", [])
    if len(reviews) != body.expected_reviews:
        raise HTTPException(409, "Someone reviewed this evidence meanwhile. Reload.")
    review = {"seq": len(reviews) + 1, "decision": body.decision, "note": body.note.strip(), "actor_id": actor["id"],
              "actor_name": actor["name"], "at": _now()}
    status = "verified" if body.decision == "verified" else "correction_requested"
    if ctx.store.name == "mongodb":
        res = await ctx.store.db[SUBMITTED].update_one({"_id": evidence_id, "reviews": {"$size": len(reviews)}},
                                                       {"$push": {"reviews": review}, "$set": {"status": status}})
        if res.modified_count != 1:
            raise HTTPException(409, "Someone reviewed this evidence meanwhile. Reload.")
    else:
        row = ctx.store.artifacts[SUBMITTED][evidence_id]
        if len(row.get("reviews", [])) != len(reviews):
            raise HTTPException(409, "Someone reviewed this evidence meanwhile. Reload.")
        row["reviews"] = [*reviews, review]
        row["status"] = status
    return _submitted_view({**s, "reviews": [*reviews, review], "status": status})


class SubjectEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["assign", "request_evidence", "assessment"]
    expected_seq: int = Field(ge=0)
    assignee_id: str | None = None
    note: str = Field(default="", max_length=600)
    judgment: Literal["clear", "needs_action", "remediated", "exception", "not_applicable"] | None = None
    reason: str = Field(default="", max_length=1200)
    evidence_ids: list[str] = Field(default_factory=list, max_length=30)
    acknowledge_changes: bool = False


async def _record(ctx: Context, subject: str, r: dict, body: SubjectEvent, *, evidence: list[dict], clause: dict | None,
                  facts: list[dict], checks: list[dict], rule_ids: list[str]) -> dict:
    actor = ctx.actor
    events = ctx.subjects.get(subject, [])
    seq = events[-1]["seq"] if events else 0
    base = {"_id": f"{subject}:{seq + 1:04d}", "subject": subject, "asset_id": r["id"], "seq": seq + 1, "kind": body.kind,
            "actor_id": actor["id"], "actor_name": actor["name"], "at": _now()}
    current_hash = _digest([i.get("value") for i in evidence] + [(r["owner"] or {}).get("id")])
    last = events[-1] if events else None
    if last and body.expected_seq == seq - 1 and last["kind"] == body.kind and last["actor_id"] == actor["id"] and \
            all(last.get(k) == v for k, v in body.model_dump(exclude={"expected_seq", "acknowledge_changes"}).items() if v not in (None, "", [])):
        return _event_view(last)  # double submit: the first one already counted
    if body.expected_seq != seq:
        raise HTTPException(409, "This review changed meanwhile. Reload before submitting.")
    if body.kind == "assign":
        _require(actor, "bi_steward")
        person = be.DEMO_PERSONAS.get(body.assignee_id or "") or be.people().get(body.assignee_id or "")
        if not person or person.get("status", "active") != "active":
            raise HTTPException(422, "Assign the review to an active person.")
        doc = base | {"assignee_id": person["id"], "assignee_name": person["name"], "evidence_hash": current_hash,
                      "owner_id": (r["owner"] or {}).get("id"), "note": body.note.strip()}
    elif body.kind == "request_evidence":
        _require(actor, "bi_steward", "governance_reviewer")
        if len(body.note.strip()) < 5:
            raise HTTPException(422, "Say what evidence is needed.")
        doc = base | {"note": body.note.strip()}
    else:
        _require(actor, "governance_reviewer", "bi_steward")
        if not body.judgment or len(body.reason.strip()) < 5:
            raise HTTPException(422, "Choose a judgment and give a reason.")
        by_id = {i["id"]: i for i in evidence}
        cited = [by_id[e] for e in body.evidence_ids if e in by_id]
        if len(cited) != len(body.evidence_ids):
            raise HTTPException(422, "Cite only evidence shown for this dashboard.")
        if body.judgment in CLOSING and not cited:
            raise HTTPException(422, "Closing a review needs at least one piece of cited evidence.")
        started = next((e for e in reversed(events) if e["kind"] == "assign"), None)
        if started and (started["evidence_hash"] != current_hash) and not body.acknowledge_changes:
            raise HTTPException(409, "The owner or the evidence changed since this review started. Reassess, then confirm.")
        snapshot = {"evidence": [{k: i.get(k) for k in ("id", "kind", "label", "value", "source", "authority_label", "observed_at")}
                                 for i in cited], "clause": clause, "facts": facts, "checks": checks, "rule_ids": rule_ids,
                    "owner": r["owner"] and {"id": r["owner"]["id"], "name": r["owner"]["name"]},
                    "workbook": _workbook(), "acknowledged_changes": bool(started and started["evidence_hash"] != current_hash)}
        doc = base | {"judgment": body.judgment, "reason": body.reason.strip(), "evidence_ids": body.evidence_ids, "snapshot": snapshot}
    _, inserted = await be._insert_once(ctx.store, EVENTS, doc)
    if not inserted:
        raise HTTPException(409, "This review changed meanwhile. Reload before submitting.")
    return _event_view(doc)


@router.post("/risks/{risk_id}/events", status_code=201)
async def risk_event(risk_id: str, body: SubjectEvent, request: Request) -> dict:
    ctx = await Context().load(request)
    if not ctx.actor:
        raise HTTPException(401, "Choose a demo identity to make changes. Viewers can only read.")
    m = re.match(r"^RISK-(.+?)-([A-Za-z_]+|SIG-\d+)$", risk_id)
    if not m:
        raise _not_found("risk")
    r = ctx.asset(m.group(1))
    g = await ctx.governance(r, _today())
    x = next((x for x in g["risks"] if x["id"] == risk_id), None)
    if not x:
        raise _not_found("risk")
    rules = workbook_rules()
    clause = _clause_view(rules[x["rule_ids"][0]], rules[x["rule_ids"][0]]["revisions"][0], "1") if x["rule_ids"] else None
    return await _record(ctx, risk_id, r, body, evidence=g["evidence"], clause=clause,
                         facts=[{"text": x["observation"], "evidence_ids": x["evidence_ids"]}], checks=x["checks"], rule_ids=x["rule_ids"])


@router.post("/documents/{doc_id}/clauses/{clause_id}/assets/{asset_id}/events", status_code=201)
async def clause_event(doc_id: str, clause_id: str, asset_id: str, body: SubjectEvent, request: Request) -> dict:
    ctx = await Context().load(request)
    if not ctx.actor:
        raise HTTPException(401, "Choose a demo identity to make changes. Viewers can only read.")
    if doc_id not in ctx.docs:
        raise _not_found("document")
    r = ctx.asset(asset_id)
    g = await ctx.governance(r, _today())
    p = next((p for p in g["policies"] if p["doc_id"] == doc_id and (p.get("clause") or {}).get("clause_id") == clause_id), None)
    if not p or p["status"] != "applies":
        raise HTTPException(409, "This clause does not currently apply to this dashboard.")
    return await _record(ctx, clause_subject(doc_id, clause_id, asset_id), r, body, evidence=g["evidence"], clause=p["clause"],
                         facts=p["facts"], checks=[], rule_ids=[doc_id])
