# CLAUDE.md

Project context for Claude Code and for the team. Keep this file current: it is the source of truth for scope, architecture and decisions.

## Project

**Agentic Analytics Manager** (working name). Bayer Hackathon 2026 (Since AI), challenge "Build Less, Build Better: AI for Governed Analytics".

An AI workspace that takes a business question, finds what already exists in the BI estate, and recommends with evidence whether to **reuse, repair, consolidate, migrate or build** analytics, then tracks the follow-up actions. It decides what deserves to exist before anything is built.

### Scope (from Bayer's data pack)
- **Bayer Pharmaceuticals, prescription-medicine analytics only.** No Crop Science, no Consumer Health. (An earlier version of this repo assumed the Turku manufacturing plant; that was wrong and has been removed.)
- Commercial, market access, launch, supply, finance and BI-governance analytics over a Power BI + Tableau estate.
- **Out of scope:** clinical decision support, treatment recommendations, pharmacovigilance, patient profiling, patient/HCP-level data, real Bayer systems, any claim that synthetic figures are Bayer performance.
- Bayer's recommended MVP: business question → intent → find governed KPIs, semantic models and reports → check usage, ownership, lineage, governance → recommend reuse / consolidation / migration / retirement / new build **with evidence**.
- Output format: **.PBIP** (Power BI Project, Git friendly). Users are business people: ask about decisions, not specifications.

## Data: `materials/Bayer_Pharmaceuticals_SinceAI_2026_FINAL_Builder_Data_Pack.xlsx`

All values are **synthetic**. Product and therapeutic-area names are public context only. There are no ground-truth answers in the workbook.

| Sheet | Rows | Used for |
|---|---|---|
| Analytics_Assets | 360 | Reports / dashboards / apps / workbooks (266 Power BI, 94 Tableau) |
| Semantic_Models | 75 | Shared models: endorsement, refresh, AI readiness |
| KPI_Catalog | 56 | 18 canonical KPIs + 38 variants (definition_conflict, duplicate_candidate, local_variant) |
| Asset_KPI_Map | 1,454 | Which KPIs each asset uses |
| Asset_Usage | 3,600 | Monthly views/users/errors, Jan–Oct 2026 (last 3 months used as "90 days") |
| Lineage_Edges | 438 | Model→asset, asset→asset, model→model |
| Governance_Signals | 410 | HIGH_REACH_UNENDORSED, MIGRATION_CANDIDATE, LIFECYCLE_REVIEW, MISSING_OWNER, ... |
| Data_Quality | 147 | Model refresh/AI-readiness issues, missing owners |
| Migration_Backlog | 94 | Tableau → Power BI path: MIGRATE, RETIRE, REBUILD_ON_SHARED_MODEL, CONSOLIDATE_BEFORE_MIGRATION, HUMAN_REVIEW |
| Business_Requests | 150 | 10 distinct request texts → the 10 presets |
| Governance_Rules | 8 | RULE-001..008, cited in every decision |
| Owners, Workspaces, Products, Markets | 60, 16, 7, 14 | Context |
| Product_Market_Monthly, Market_Access, Supply_Operations, Launch_Milestones | 980, 98, 98, 35 | Synthetic business facts for previews and action verification |

`app/datapack.py` reads the workbook and builds the catalog: measures = canonical KPIs with their variants; each asset gets canonical measures, `conflicts` (definition_conflict variants), `variants` (other unapproved variants), 90-day usage, open signals, migration entry, model refresh and AI readiness.

## Processing flow

```
User request (free text or one of 14 presets)
  → Intent agent (/grill-me)          AI; ≤2 questions; KPIs, breakdowns, product/market/region/TA filters, Tableau migration flag
  → Discovery                         Python: score all 360 assets
  → Governance check                  Python: checks + gates per candidate
  → Decision                          Python: reuse | repair | consolidate | migrate | new build | not feasible
  → Follow-up actions proposed        Python; a person accepts
       ├─ Reuse        → open the existing report (+ preview numbers)
       ├─ Not feasible → explain (e.g. patient-level data is out of scope)
       └─ Repair / Consolidate / Migrate / New build
              → Evidence agent → Spec agent → human approval → PBIP (thin report on shared model) → register in catalog
```

Rules: the AI extracts facts, **Python decides** (same input, same decision); agents propose, Python verifies; every decision shows scores, the rule that fired and the Bayer RULE ids it applies.

## Decision formula (`backend/app/decision.py`)

- **Coverage** = 0.6 × requested KPIs found (canonical ids, variants count as found) + 0.4 × scope fit. Scope fit = mean of product fit and market fit: an "All Pharma" / "Global" asset fits multi-product / multi-market requests; a single-product or single-market request also accepts an exact match.
- **Freshness** from the semantic model refresh: healthy 1.0, warning 0.7, failed 0.3.
- **Governance** (request-relative): requested KPIs use approved definitions 0.30 (RULE-002), certified or promoted 0.20 (RULE-005), active owner 0.20 (RULE-003), no open high-severity signal 0.15, lifecycle active 0.10, model AI-ready 0.05 (RULE-007).
- **Gates:** conflicting definition for a requested KPI; lifecycle candidate_retire (RULE-006); owner inactive/missing (repairable).
- Only candidates with scope ≥ 0.75 can be reused, repaired or consolidated.
- **Reuse:** gates pass, coverage ≥ 0.90, freshness ≥ 0.90, governance ≥ 0.80.
- **Repair:** coverage ≥ 0.90, only repairable gates, governance ≥ 0.30, and (≥ 300 views in 90 days or governance ≥ 0.80), with a fixable issue (refresh, owner, variants, endorsement, AI readiness). Never rebuild a governed report.
- **Consolidate:** gates pass, 0.60 ≤ coverage < 0.90, ≥ half the KPIs found, governance ≥ 0.60.
- **Migrate** (Tableau replacement requests, RULE-006): if a governed Power BI report already covers it → reuse and retire the Tableau assets; else rebuild the most-used product Tableau asset (not RETIRE, ≥ 150 views, not candidate_retire) on the backlog's target model; flag every other Tableau asset with a verdict and reason (retire / human review / fold in).
- **New build:** approved KPIs exist → one thin report on the best shared model (`rank_models`: KPI coverage, endorsement, refresh, AI readiness, Power BI, scope).
- **Not feasible:** unknown or out-of-scope terms (patient, prescriber, HCP, adherence...).
- **Flags:** overlapping assets (coverage ≥ 0.60) that are candidate_retire, low use (< 150 views), poorly governed (< 0.50) or use a conflicting KPI → consolidate/retire actions. Max 5.
- All thresholds are in `THRESHOLDS`.

What the 14 presets give on the untouched estate: migrate (Xarelto Tableau), new build (8 Bayer requests: the estate has no in-scope report that is both complete and governed for them), reuse (Eylea JP), repair (Xarelto MX owner; Canada refresh), not feasible (patient-level). A repeated request after approval is answered by reuse.

## Presets (`backend/app/datapack.py`)
- `PRESETS`: the 10 distinct Business_Requests texts, each mapped to canonical KPIs, breakdowns and scope, with how often Bayer asked it.
- `SCENARIOS`: 4 estate scenarios built from real assets to show reuse, repair and not feasible. Labelled "Estate scenario" in the UI.

## Agents (`backend/app/agents/`)

Each agent has `run_llm` (OpenAI) and `run_rules` (offline). If the model fails it falls back to rules and records why. Every run returns a trace shown in the flow panel and saved to `agent_runs`.

| Agent | Model | Does | Python verification |
|---|---|---|---|
| Intent (/grill-me) | fast | JSON intent; ≤2 questions; presets are taken as-is | `sanitize_intent` drops unknown KPI ids, products, markets |
| Evidence (/explore) | reasoning | Tool loop: `search_catalog`, `get_kpi`, `get_model`, `get_report`, `get_lineage` | `finalize`: rejects unknown models, keeps repair/consolidate on the report's model, writes all proof lines from catalog facts (model, KPI variants to avoid, usage, signals, backlog, lineage) |
| Spec (/to-spec) | reasoning | Page design only | `assemble` + `validate` (approved KPIs, shared model, owner, ≤6 visuals, ...); errors go back, ≤3 attempts. Repair = no pages |

## Action tracker (`backend/app/actions.py`, `#actions`)
- Proposals after every decision: one **business** action (verify a KPI moves in the right direction) and **maintenance** actions (assign owner, consolidate/retire flagged assets, fix model data-quality issues, add missing KPIs to the shared model).
- Statuses open → in progress → blocked → done → verified (or dismissed). Blocked needs a blocker, done needs an outcome, verified needs a result. **Done is not verified.** Full history. Proposal `key`s dedupe against open actions (409).
- Four sample actions are seeded from real signals in the data pack.

## Architecture

```
materials/                 Bayer data pack (committed)
frontend/  React + TypeScript + Vite
  #ask       chat, 10 Bayer requests + 4 estate scenarios, live flow panel with previews
  #explorer  Estate Explorer: reports, models, KPIs (+variants), owners, workspaces from GET /api/graph
  #actions   action tracker board
backend/   Python 3.12+, FastAPI
  app/datapack.py      workbook → catalog, presets, scenarios
  app/decision.py      scores, gates, lifecycle decision (pure functions)
  app/agents/          intent, evidence, spec agents + read-only catalog tools
  app/pipeline.py      orchestration, SSE events, register approved changes
  app/facts.py         preview numbers from Product_Market_Monthly
  app/pbip.py          thin report PBIP (definition.pbir → shared model by connection)
  app/actions.py       follow-up actions
  app/graph.py         catalog → Explorer graph
  app/store.py         MongoDB (pymongo async) or in-memory
  app/load_datapack.py python -m app.load_datapack [--reset]
```

### API
- `GET /api/health`, `/api/presets`, `/api/catalog`, `/api/graph`, `/api/datapack` (sheet counts, rules), `/api/requests` (150 Business_Requests)
- `POST /api/chat` `{conversation_id?, message, preset_id?}` → SSE; `POST /api/approve` `{conversation_id, approved, approver}` → SSE
- `GET /api/conversations[/{id}]`, `/api/specs`, `/api/agent-runs`
- `GET/POST /api/actions`, `GET/PATCH /api/actions/{id}`

### Models
- OpenAI GPT-6: `MODEL_REASONING` (`gpt-6-astra`) for evidence and spec, `MODEL_FAST` (`gpt-6-luna`) for intent and explanations. Verify IDs in the dashboard. `LLM_PROVIDER=mock` = offline rules (default without key).
- The model sees catalog metadata only. Production path: models in Bayer's Azure tenant (EU).

### Database (MongoDB, or in-memory without `MONGODB_URI`)
- `datapack_<sheet>`: every table sheet, row for row. `catalog_<key>`: measures, dimensions, models, owners, workspaces, products, markets, assets, lineage, rules (+ `catalog_meta`). `presets`.
- `conversations`, `intents`, `evidence`, `specs`, `agent_runs`, `actions`.
- Empty database is seeded from the workbook on startup; `python -m app.load_datapack --reset` reloads it. Registered/repaired reports are written back to `catalog_assets`.
- Not verified against Atlas from the cloud session (no network route); tests use mongomock. The MongoDB MCP connector is disabled at the Atlas organization level.

## Secrets
Never commit keys; `backend/.env` is git-ignored. Never paste keys into chat.

## Commands
```bash
cd backend && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
python -m app.load_datapack          # optional: load into MongoDB (needs MONGODB_URI)
uvicorn app.main:app --reload --port 8000
pytest                               # 41 tests
cd frontend && npm install && npm run dev
```

## Conventions
- Python: type hints, pure functions for scoring, Pydantic for API bodies. TypeScript strict.
- UI copy: plain language for business users; no em-dashes; synthetic data always labelled.
- Cite Bayer rule ids (RULE-00x) when a rule drives a decision.
- Commit messages: imperative mood, explain why.

## Status
- [x] Data pack loaded; catalog, presets, scenarios built from it
- [x] Decision rules for reuse / repair / consolidate / migrate / new build / not feasible, citing Bayer rules
- [x] Agents with tool calling, verification, fallback, audit log
- [x] Thin-report PBIP on shared models; preview numbers from synthetic facts
- [x] Action tracker; Estate Explorer on the Bayer estate
- [ ] Run with a real OpenAI key (model path tested only with a scripted fake client)
- [ ] Load into the team's MongoDB Atlas (`python -m app.load_datapack`)
- [ ] Validate generated PBIP in Power BI Desktop
- [ ] Previews for KPIs not in Product_Market_Monthly (e.g. reimbursement from Market_Access)
- [ ] Build plan page (artifact) still describes the old plant scope: update
