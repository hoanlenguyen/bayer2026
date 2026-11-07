# CLAUDE.md

Project context for Claude Code and for the team. Keep this file current: it is the source of truth for scope, architecture and decisions.

## Project

**Agentic Analytics Manager** (working name). Bayer Hackathon 2026, challenge "Build Less, Build Better: AI for Governed Analytics".

An AI workspace that helps a pharma manufacturing plant ask the right business question, reuse or create trustworthy analytics, and manage the follow-up actions. It decides what deserves to exist before anything is built.

### Bayer context (from the briefing)
- Setting: Bayer manufacturing plant in Turku, Finland (contraceptives, IUDs, implants).
- Problem: overlapping dashboards, unclear ownership, no lifecycle for BI. Point-and-click BI cannot be version controlled or debugged.
- Stack at Bayer: Power BI, Microsoft Fabric. Target output is **.PBIP** (Power BI Project, text files, Git friendly).
- Users: any department (production, quality, supply chain, HR, finance, IT). Mostly non-technical. Ask about decisions, not specifications.
- Principle: reduce cognitive load. Show only what matters now. Limit content; do not maximise it.
- Bayer reference pipeline: Prompt → /grill-me → Intent → /explore (Fabric) → Evidence → /to-spec → Spec (`DashboardSpec` dataclass) → render_preview (plain Python, no AI) → Report (.PBIP).
- Bayer provides a synthetic dataset. Any extra data is allowed.

## Processing flow (team design)

```
User intent (free text or department preset)
  → Intent agent (/grill-me)               AI, asks at most 2 questions
  → Analytics discovery                    catalog search + scoring (Python)
  → Governance check (per candidate)       deterministic Python
  → Decision formula                       deterministic Python
       ├─ Reuse        → link to existing report (no new PBIP)
       ├─ Extend       → Evidence agent → Spec agent (change) → approval → updated PBIP
       ├─ Create       → Evidence agent → Spec agent (new)    → approval → new PBIP → register
       └─ Not feasible → ask the user to adjust the intent
```

Rules:
- The AI extracts facts (intent fields, matching measures). **Python decides.** Same inputs, same decision.
- Agents propose, Python verifies: unknown catalog IDs, tables and columns are removed; numbers shown as proof come from the catalog, never from the model.
- Every decision shows its scores in the UI.
- A human approves Extend, Create, certification and retirement.

## Decision formula (`backend/app/decision.py`)

- **Coverage** = 0.5 × measures found/required + 0.3 × dimensions found/required + 0.2 × grain supported. Uses canonical IDs, not names.
- **Freshness**: target by grain (hour 2 h, day 24 h, week 7 d, month 31 d). 1.0 if data age ≤ target, linear to 0 at 3 × target.
- **Governance score** (weights): certified definitions match 0.30, certified asset 0.20, active owner 0.20, quality tests pass 0.15, reviewed within 12 months 0.10, documented 0.05.
- **Hard gates** (block Reuse/Extend): metric conflict with a certified definition, no access, owner left with no backup.
- **Reuse**: gates pass, Coverage ≥ 0.90, Freshness ≥ 0.90, Governance ≥ 0.80.
- **Extend (business)**: gates pass, 0.60 ≤ Coverage < 0.90, Governance ≥ 0.80. Add the missing measures, dimensions or grain.
- **Extend (maintenance)**: gates pass, Coverage ≥ 0.90, Governance ≥ 0.80 but Freshness < 0.90. Fix the refresh schedule instead of building a copy.
- **Create**: required data exists in the catalog. Otherwise **Not feasible**.
- Side flag (any decision): assets with Coverage ≥ 0.40 that are poorly governed (Governance < 0.60) or fail a gate are flagged for merge or retirement.
- Thresholds live in one config dict (`THRESHOLDS`). Change them there only.

## Department presets (`backend/app/data/presets.json`)

Preset = starting intent mapped to certified KPIs. Grill-me then asks only for missing details (line, shift, horizon). Time-based presets (shift start, weekly review, month-end) are in scope.

## Agents (`backend/app/agents/`)

Each agent has `run_llm` (OpenAI) and `run_rules` (offline, deterministic). Same output shape. If the model call fails, the agent falls back to rules and records why. Every run returns a trace (steps: tool / model / rule / check / note) that is shown in the flow panel and saved to `agent_runs`.

| Agent | Model role | What it does | Python verification |
|---|---|---|---|
| Intent (/grill-me) | fast (`gpt-6-luna`) | JSON extraction of decision, measures, dimensions, grain, filters; max 2 questions | `sanitize_intent` drops IDs not in the catalog |
| Evidence (/explore) | reasoning (`gpt-6-astra`) | Tool loop over read-only catalog tools: `search_catalog`, `get_measure`, `get_dataset`, `get_relationships`, `get_report` | `finalize`: removes unknown tables/columns, adds required ones, builds proof lines from catalog facts |
| Spec (/to-spec) | reasoning | Designs the page (visuals, name, rationale); Python assembles the rest from evidence | `validate`: 11 checks; errors go back to the model, up to 3 attempts |

## Architecture

```
frontend/  React + TypeScript + Vite
  #ask       Ask page: chat, example question chips (each sends its preset), verdict card (scores + approval), "How this was decided" panel
  #explorer  Estate Explorer: entity details + relationship graph ("molecular view"),
             loaded from GET /api/graph (live plant catalog, same governance scoring as the Ask flow)
  /cala-graph  Knowledge graph: full-screen 3D canvas (path route, "Knowledge Graph" in the sidebar), loaded from
             GET /api/graph and grouped by domain (workspace) using the catalog's own links
backend/   Python 3.12+, FastAPI
  app/main.py        HTTP API, Server-Sent Events stream of pipeline events
  app/pipeline.py    orchestrates stages, emits events
  app/agents/        intent, evidence, spec agents + read-only catalog tools
  app/llm.py         OpenAI access: text, JSON and tool-calling loop; "mock" = offline
  app/graph.py       catalog → Explorer graph (entities, edges, status, flags)
  app/seed.py        python -m app.seed [--reset]: load catalog + presets into MongoDB
  app/decision.py    scores, gates, decision (pure functions, unit tested)
  app/pbip.py        Spec → PBIP folder (plain Python, no AI)
  app/store.py       MongoDB (pymongo async) or in-memory fallback
  app/data/          sample catalog and presets (fictional)
```

### API
- `GET  /api/health` – provider and store in use
- `GET  /api/presets` – department presets
- `GET  /api/catalog` – sample catalog
- `POST /api/chat` – body `{conversation_id?, message, preset_id?}`; streams SSE events: `stage` (started/done with payload), `message`, `question`, `done`, `error`
- `POST /api/approve` – body `{conversation_id, approved, approver}`; streams approval → render → register
- `GET  /api/conversations`, `GET /api/conversations/{id}` – stored conversations with runs and events
- `GET  /api/graph` – Estate Explorer entities and edges from the live catalog
- `GET  /api/specs?conversation_id=` – DashboardSpec versions with status (draft / approved / rejected / superseded)
- `GET  /api/agent-runs?conversation_id=` – audit log of agent runs

### Models
- OpenAI GPT-6 family. `MODEL_REASONING` (default `gpt-6-astra`) for discovery reasoning and spec; `MODEL_FAST` (default `gpt-6-luna`) for grill-me and summaries. Verify exact IDs in the OpenAI dashboard.
- `LLM_PROVIDER=mock` runs fully offline with rule-based extraction. Default when no `OPENAI_API_KEY` is set.
- Privacy position: the model sees catalog metadata and the user's question, not raw production data. Production path: models hosted in Bayer's own Azure tenant (EU region).

### Database
- MongoDB when `MONGODB_URI` is set, otherwise in-memory (data lost on restart). Database name: `MONGODB_DB` (default `analytics_manager`).
- The catalog lives in MongoDB. On startup an empty database is seeded from `app/data/*.json`; `python -m app.seed --reset` reloads it.
- Collections: `conversations`, `intents`, `evidence`, `specs`, `agent_runs`, `catalog_measures`, `catalog_dimensions`, `catalog_datasets`, `catalog_assets`, `catalog_relationships`, `presets`.
- Registered or extended reports are written back to `catalog_assets`, so they survive restarts and are reused.
- Tests use `mongomock` through an async adapter (`tests/fakes.py`); the real Atlas connection has not been exercised yet.
- The MongoDB MCP connector is not usable: Atlas reports MCP access disabled for the organization (an Organization Owner must enable AI client access).

## Request triage and vector search (`app/triage.py`, `app/vectors.py`)
- Business_Requests urgency/status labels are not predictable from text (all 10 texts have mixed labels; best possible 54% vs 52% majority), so no classifier.
- Urgency: stated (grill-me "When do you need this?") / inferred (time words, quoted evidence, model claims verified) / default normal. Status is not shown while the request is being understood (Understand the request shows urgency only). When the intent is complete the request is created as `REQ-APP-…` with status new and added to the vector corpus (`request_vectors` in Atlas, or in memory); the decision step sets it to triaged and shows the tag. Later requests count it as a duplicate. `build_vectors` keeps these live requests and re-embeds them.
- Vector search: duplicate and similar requests at intake, KPI suggestion chips. OpenAI embeddings or local hashed fallback; MongoDB Atlas `$vectorSearch` (`python -m app.build_vectors`) or in-memory. Endpoints `/api/requests/similar`, `/api/requests/clusters`, `/api/requests/label-check`.

## Deployment
Every option serves frontend and API from one address (no CORS, no `VITE_API_BASE`).

**Free (current choice): Cloudflare Workers Free + Azure Container Apps (`docs/DEPLOY_FREE.md`)**
- Frontend: `deploy/cloudflare/wrangler.free.jsonc` + `src/proxy.js`, static assets, `/api/*` forwarded to `BACKEND_URL`. No tunnel.
- Backend: `.github/workflows/backend-image.yml` pushes `ghcr.io/<owner>/bayer2026-backend`; `deploy/azure/containerapp.sh create|update|url|logs` (Cloud Shell) runs it on Container Apps, 0.5 vCPU / 1 GiB, 0 to 1 replica, secrets as Container Apps secrets, no Log Analytics. Atlas must allow `0.0.0.0/0`.

**Azure for Students VM (`deploy/server/`, `docs/DEPLOY_AZURE.md`)**, tested end to end with Docker:
- Ubuntu 24.04 on `Standard_B2ats_v2` (free 750 h/month for 12 months), 64 GiB disk, France Central, DNS label `<name>.<region>.cloudapp.azure.com`.
- Docker Compose: `backend` (backend/Dockerfile, port 8000 not published) and `web` (React build served by Caddy, `/api/*` proxied, automatic HTTPS via `SITE_ADDRESS`, e.g. `<ip>.sslip.io`).
- Keys stay in `backend/.env` on the server. Fixed IP, so Atlas allows only that IP. PBIP output on a named volume.

**Cloudflare (`deploy/cloudflare/`, `docs/DEPLOY_CLOUDFLARE.md`)**, config validated with a dry run, needs Workers Paid:
- Cloudflare Workers Paid plan. One Worker serves the frontend build (static assets, SPA fallback) and forwards `/api/*` to a Container running `backend/Dockerfile` (one named instance, `standard-1`, sleeps after 30 min).
- Secrets `OPENAI_API_KEY` and `MONGODB_URI` are set with `wrangler secret put`; other settings are `vars` in `wrangler.jsonc`. Atlas must allow `0.0.0.0/0` (no fixed egress IP).
- Deploy: GitHub Actions "Deploy to Cloudflare" (manual) or `npm run deploy` in `deploy/cloudflare` (needs Docker).

## Secrets
- Never commit keys. `backend/.env` is git-ignored; `backend/.env.example` lists variable names only.
- Never paste keys into chat.

## Commands

```bash
# backend
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
pytest                 # 28 tests: decision rules, agents (incl. scripted OpenAI tool calls), MongoDB store, graph, API flows
python -m app.seed     # load catalog into MongoDB (needs MONGODB_URI)

# frontend (proxies /api to :8000)
cd frontend && npm install && npm run dev
```

## Conventions
- Python: type hints, Pydantic models for API payloads, pure functions for scoring.
- TypeScript: strict mode; shared API types in `frontend/src/api/types.ts`.
- UI copy: plain language for non-technical plant staff. No em-dashes. Agent traces, rules and raw specs sit behind the "Technical details" switch.
- UI decisions (look, layout, what to keep consistent): `DESIGN.md`.
- All sample data is fictional and labelled as sample data in the UI.
- Commit messages: imperative mood, explain why.

## Status
- [x] Build plan page: https://claude.ai/artifact/NWgjoee8m5ZYAYoBkDmYCC
- [x] Proposal draft (`docs/PROPOSAL.md`, earlier "Curator" concept, partly superseded by this file)
- [x] Estate Explorer prototype (frontend)
- [x] Backend: pipeline, decision formula (unit tested), mock + OpenAI provider, MongoDB/in-memory store, PBIP skeleton
- [x] Ask page with department presets, grill-me questions, approval step and live processing flow
- [x] Estate Explorer on the plant catalog (`/api/graph`)
- [x] Agents for intent, evidence and spec with tool calling, verification, fallback and audit log
- [x] MongoDB persistence for catalog, conversations, intents, evidence, specs, agent runs
- [ ] Test the OpenAI provider with a real key (model path tested only with a scripted fake client)
- [ ] Connect to the team's MongoDB Atlas (code tested with mongomock only)
- [ ] Load Bayer synthetic dataset into the catalog
- [ ] Action tracker (follow-up actions with owners)
- [ ] Validate generated PBIP in Power BI Desktop
