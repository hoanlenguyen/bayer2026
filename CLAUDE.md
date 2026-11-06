# Engineering context

Read `docs/IMPLEMENTATION_HANDOVER.md` for current behavior and remaining external validation. The implementation brief is `docs/Bayer_Challenge_Implementation_Prompt.md`. Earlier concept documents may describe obsolete behavior.

## Product and boundaries

This is an internal **dashboard request and lifecycle workbench**, not primarily an insights chatbot. A nontechnical employee requests a dashboard or a change; intent/evidence/spec agents assist while Python evaluates the estate and enforces lifecycle transitions.

The challenge is broader than manufacturing. This MVP is intentionally grounded in the provided synthetic Pharmaceuticals workbook: commercial, supply, market access, launch, finance and BI governance. Do not invent R&D assays, patients, real Bayer services, tenant IDs, executable Bayer models or performance claims.

## Core invariants

- Approval records a particular specification and source snapshot. It does not execute a repair, certify an asset or prove publication.
- All required specification checks and the executable binding contract must pass before generation.
- Imported metadata is preserved. Runtime drafts and actions are overlays with their own IDs.
- Generated assets are `validation_pending`, lifecycle `draft`, endorsement `none`, certified `false`, and excluded from trusted reuse. Only a separately implemented and verified publication/endorsement workflow may change that.
- Stable owner IDs are authoritative. Names are nonunique. Mutation actors come from the signed server session, never a client display name.
- The explicit demo policy permits configured actors to inspect synthetic source metadata and the shared action queue. Requests, evidence/spec traces and downloads belong to their requester or a configured reviewer. Demo role selection is not enterprise SSO.
- Never silently fall back to volatile storage when a configured database fails.
- No model should invent a usable measure by matching a KPI label. `bindings.py` is the narrow executable **team-defined** demo contract.
- Unknown terms, unsupported periods, missing ownership and source-scope contradictions must remain visible.
- Agent traces distinguish live model, offline rules and error fallback. Do not describe deterministic functions as autonomous agents.
- Source hashing is conservative: catalogue/workbook changes invalidate pending review. Restart after a workbook replacement so both cached readers reload.

## Data and interpretation

Source: `materials/Bayer_Pharmaceuticals_SinceAI_2026_FINAL_Builder_Data_Pack.xlsx`.

| Records | Count | Interpretation |
| --- | ---: | --- |
| Analytics assets | 360 | 266 Power BI, 94 Tableau |
| Semantic models | 75 | Metadata; executable models are not supplied |
| KPI definitions | 56 | 18 canonical KPIs plus 38 variants |
| Asset/KPI mappings | 1,454 | Exact ID associations |
| Usage observations | 3,600 | January–October 2026 monthly values |
| Directed lineage | 438 | Source evidence; preserve direction |
| Governance signals | 410 | Keep unresolved signals visible |
| Data-quality records | 147 | Supplied findings |
| Migration candidates | 94 | Unapproved suggestions |
| Business requests | 150 | Ten recurring texts; structured context may conflict |
| Owners/workspaces/products/markets | 60 / 16 / 7 / 14 | Join by ID |
| Product-market-month facts | 980 | Synthetic values and original value-type labels |

`workbook_source.py` exposes all 24 worksheets, including narrative sheets, original Excel row/cell metadata and workbook SHA. `datapack.py` builds the decision catalogue. The graph shows January–October summed views and latest monthly users. The decision engine uses **August–October 2026**. Legacy fields named `views_90d` retain API compatibility; UI labels identify the actual three calendar months. Period-unique users are unknown, never the sum of monthly distinct counts.

The supplied Eylea Japan scenario references a model declared for Nubeqa. It requires metadata repair/review. The Brazil portfolio scenario (`AST-0019`) demonstrates metadata-compatible reuse. A scope match does not grant real tenant access.

## Implementation map

| Component | Responsibility |
| --- | --- |
| `agents/intent.py` | Interpret request; retain unresolved terms; ask material clarification without a turn cap |
| `decision.py` | Deterministic relevance, governance, scope contradictions and lifecycle proposal |
| `agents/evidence.py` | Read-only catalogue tools and checked model proposal |
| `agents/spec.py` | Agent layout choice; Python ownership, contract and validation |
| `governance.py` | Demo actors, signed sessions, permissions, source/spec hashes, immutable audit |
| `pipeline.py` | Versioned requests, review, blocked actions, gated generation, pending output reuse |
| `bindings.py` | Exact workbook facts; EUR conversion; two SUM measures; reference values |
| `pbip.py`, `schemas/` | Enhanced PBIR, embedded demo model, official schema checks |
| `main.py` | Signed-session API, submission keys, revision checks, action versions, ZIP download |
| `store.py` | SQLite single-worker default, optional MongoDB, explicit disposable memory |
| `graph.py`, `workbook_source.py` | Source entities/edges, provenance, runtime requests/actions/drafts |
| `validate_demo.py` | Reproducible offline artifact evidence and validation handoff |
| `frontend/src/pages/AskPage.tsx` | Request brief, resumption, stages, evidence, review and delivery |

## Decision policy

The weights and thresholds in `THRESHOLDS` are **team policy**, inspired by but not quoted from the eight supplied RULE-00x records. Coverage weights requested KPIs at 0.6 and product/market scope at 0.4. Governance checks approval, endorsement, ownership, signals, lifecycle and model readiness. Similarity is not eligibility. Missing terms block fulfilment before reuse; pending drafts are not candidates. Scope contradictions require steward review. Migration and retirement remain proposals.

## Development and verification

Use Python 3.12+, FastAPI, React 19, strict TypeScript and Vite. Keep scoring pure and UI copy simple. Preserve the workbench and exact source-evidence graph.

Run backend pytest, frontend `npm test` with `WORKBENCH_PYTHON` if needed, and `npm run build`. `python -m app.validate_demo` generates the reproducibility package. Tests cover mocked live-agent responses and offline fallback; they do not prove real OpenAI access, Atlas, Power BI rendering or production identity.

Default persistence is SQLite at `backend/data/workbench.sqlite`, generated files at `backend/output`. Both are ignored. Run **one application worker** for this MVP; its mutation lock and snapshot store are not distributed transactions. Mount both paths when running the container. Production needs durable object storage, database transactions/leases, SSO and real workspace permissions.

Never commit `.env`, credentials, database state or user runtime output. The existing GitHub workflow builds the backend image on main; pushing an image is not deployment of a running app. See the handover for ownership and publication responsibilities.
