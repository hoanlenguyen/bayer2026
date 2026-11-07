# CLAUDE.md

Project context for Claude Code and for the team. Keep this file current: it is the source of truth for scope, architecture and decisions.

## Project

**Agentic Analytics Manager** (working name). SinceAI Hackathon 2026, challenge "Build Less, Build Better: AI for Governed Analytics".

An AI workspace that helps a pharma manufacturing plant ask the right business question, reuse or create trustworthy analytics, and manage the follow-up actions. It decides what deserves to exist before anything is built.

### SinceAI context (from the briefing)
- Setting: SinceAI manufacturing plant in Turku, Finland (contraceptives, IUDs, implants).
- Problem: overlapping dashboards, unclear ownership, no lifecycle for BI. Point-and-click BI cannot be version controlled or debugged.
- Stack at SinceAI: Power BI, Microsoft Fabric. Target output is **.PBIP** (Power BI Project, text files, Git friendly).
- Users: any department (production, quality, supply chain, HR, finance, IT). Mostly non-technical. Ask about decisions, not specifications.
- Principle: reduce cognitive load. Show only what matters now. Limit content; do not maximise it.
- SinceAI reference pipeline: Prompt → /grill-me → Intent → /explore (Fabric) → Evidence → /to-spec → Spec (`DashboardSpec` dataclass) → render_preview (plain Python, no AI) → Report (.PBIP).
- SinceAI provides a synthetic dataset. Any extra data is allowed.

## Processing flow (team design)

The system recommends; people act on the recommendation. It changes and retires no report and publishes nothing to Power BI. The one thing it builds is an in-app dashboard: when the recommendation is a new build and every requested KPI can be calculated from the workbook, the employee reviews a dashboard brief and builds it in Analytics Manager (`app/dashboard_builder.py`). Review, repair and migration stay with the responsible owner, as assignments in the BI report register.

```
User request (free text or preset)
  → 0 Check the message            relevance agent (AI), rejected messages change nothing
  → 1 Parse business question      Business_Requests                  intent agent (AI), at most 2 questions
  → 2 Resolve metric definitions   KPI_Catalog                        Python
  → 3 Find existing analytics      Analytics_Assets + Asset_Usage     Python
  → 4 Trace data dependencies      Semantic_Models + Lineage_Edges    Python
  → 5 Check trust and ownership    Governance_Signals + Data_Quality  Python
  → 6 Handle Tableau → Power BI    Migration_Backlog                  Python
  → Recommendation with evidence:  reuse / consolidation / migration / retirement / human review / new build (or not feasible)
```

Rules:
- The AI extracts facts (intent fields). **Python decides.** Same inputs, same recommendation.
- Agents propose, Python verifies: unknown catalog IDs are removed; numbers shown as evidence come from the catalog, never from the model.
- Every recommendation shows its scores, rules applied and the evidence from all six steps (RULE-008).
- Classification can use Jev (TypeSafe AI, `app/decider.py`), off unless `TYPESAFE_API_KEY` is set and `JEV_PHASES` names phases (`relevance`, `kpis`, `urgency`). Order: Jev if confident, else GPT, else rules. Jev cannot write text, so follow-up questions, decision text and explanations stay with GPT or templates. Thresholds live in `JEV_THRESHOLDS`. Turn a phase on only if it passes `python scripts/eval_classification.py --modes rules,gpt,jev`.
- Conversation simulation (`/simulator`, under Ask in the sidebar): SinceAI and Brainrot chat (speakers `A` and `B` in the API; Analytics Manager is `C`), the gate agent labels each sentence off topic, business talk or needs a decision (Jev, then GPT, then rules; `speak` 0.70, `stay_quiet` 0.30 in `JEV_THRESHOLDS`). Its `conversation` phase is on whenever `TYPESAFE_API_KEY` is set. Only "needs a decision" runs `classify_request` on the open thread. A request too vague to check (no KPI, or a loose match with no product or market) gets no reply: Analytics Manager keeps listening, and business talk that follows is checked with it until there is enough. It never asks questions; Analytics Manager's sentence comes from Python templates, never a model, and its evidence is the same verdict and six steps as Ask (`analyse()` in `pipeline.py`, shared by both), and only a plain Reuse is called "already exists". Its accuracy on this question has not been measured yet.
- A preset's own text skips the Intent model call: its intent is already known.
- Token use is recorded per agent run (`usage` in `agent_runs`) and per question (`runs[].tokens`).
- `repair` stays an internal decision, shown as "Reuse after repair". Follow-up actions are proposed, and a person accepts them.
- `app/agents/evidence.py`, `app/agents/spec.py` and `app/pbip.py` are no longer part of the flow.

## Decision formula (`backend/app/decision.py`)

- **Coverage** = 0.5 × measures found/required + 0.3 × dimensions found/required + 0.2 × grain supported. Uses canonical IDs, not names.
- **Freshness**: target by grain (hour 2 h, day 24 h, week 7 d, month 31 d). 1.0 if data age ≤ target, linear to 0 at 3 × target.
- **Governance score** (weights): certified definitions match 0.30, certified asset 0.20, active owner 0.20, quality tests pass 0.15, reviewed within 12 months 0.10, documented 0.05.
- **Hard gates** (block Reuse/Extend): metric conflict with a certified definition, no access, owner left with no backup.
- **Reuse**: gates pass, Coverage ≥ 0.90, Freshness ≥ 0.90, Governance ≥ 0.80.
- **Extend (business)**: gates pass, 0.60 ≤ Coverage < 0.90, Governance ≥ 0.80. Add the missing measures, dimensions or grain.
- **Extend (maintenance)**: gates pass, Coverage ≥ 0.90, Governance ≥ 0.80 but Freshness < 0.90. Fix the refresh schedule instead of building a copy.
- **Create**: required data exists in the catalog. Otherwise **Not feasible**.
- **Country outside the catalog** (`app/geo.py`): a request naming a country the catalog has no data for fits no report, not even a Global one, so it ends in a new build that says the data must be added first. No preview, and nothing is flagged or replaced. Earlier requests for clearly different places are not shown as similar.
- **Human review** (Tableau requests): a report the backlog marks HUMAN_REVIEW is never the one picked to migrate. If nothing else is cleared to move, the recommendation itself is Human review.
- Side flag (any decision): assets with Coverage ≥ 0.40 that are poorly governed (Governance < 0.60) or fail a gate are flagged for merge or retirement.
- Thresholds live in one config dict (`THRESHOLDS`). Change them there only.

## Department presets (`backend/app/data/presets.json`)

Preset = starting intent mapped to certified KPIs. Grill-me then asks only for missing details (line, shift, horizon). Time-based presets (shift start, weekly review, month-end) are in scope.

## Agents (`backend/app/agents/`)

Each agent has `run_llm` (OpenAI) and `run_rules` (offline, deterministic). Same output shape. If the model call fails, the agent falls back to rules and records why. Every run returns a trace (steps: tool / model / rule / check / note) that is shown in the flow panel and saved to `agent_runs`.

| Agent | Model role | What it does | Python verification |
|---|---|---|---|
| Relevance | fast (`gpt-6-luna`) | Verdict on each typed message before anything else: accept, meaningless, off_topic, not_enough. Preset prompts skip it; suggestions and messages with no words need no model call | Unknown verdicts fall back to rules. Python writes the retry message and repeats the open question. A rejection starts no run, changes no intent, keeps the last result, and a chat holding only rejected messages stays out of the history |
| Intent (/grill-me) | fast (`gpt-6-luna`) | JSON extraction of decision, measures, dimensions, grain, filters; max 2 questions | `sanitize_intent` drops IDs not in the catalog |
| Evidence (/explore) | reasoning (`gpt-6-astra`) | Tool loop over read-only catalog tools: `search_catalog`, `get_measure`, `get_dataset`, `get_relationships`, `get_report` | `finalize`: removes unknown tables/columns, adds required ones, builds proof lines from catalog facts |
| Spec (/to-spec) | reasoning | Designs the page (visuals, name, rationale); Python assembles the rest from evidence | `validate`: 11 checks; errors go back to the model, up to 3 attempts |

## Architecture

```
frontend/  React + TypeScript + Vite
  #ask       Ask page: chat, example question chips (each sends its preset), verdict card (scores, evidence),
             "How this was decided" panel, dashboard review and build, owner hand-off; saved dashboards on the start screen
  #explorer  Estate Explorer: entity details + relationship graph ("molecular view"),
             loaded from GET /api/graph (live plant catalog, same governance scoring as the Ask flow)
  /cala-graph  Knowledge graph: full-screen 3D canvas (path route, "Knowledge Graph" in the sidebar), loaded from
             GET /api/graph and grouped by domain (workspace) using the catalog's own links
  /simulator   Conversation simulation (see Rules above)
  /briefings   Team briefings (Commercial, Supply) with the Monthly Pulse chart, meeting mode, and the BI report register tab
  /dashboards/<id>         a saved in-app dashboard (stable URL)
  /workbook-view/<a>/<b>   verified workbook view behind an employee report
  Routes other than #ask/#explorer are path routes: hosting must return index.html for unknown paths (SPA fallback).
backend/   Python 3.12+, FastAPI
  app/main.py        HTTP API, Server-Sent Events stream of pipeline events; includes the routers below
  app/briefings.py, briefing_routes.py, briefing_definitions.py   team briefings from the workbook
  app/dashboard_intake.py, dashboard_builder.py, dashboard_routes.py   dashboard questions, brief, build, saved dashboards
  app/employee_report_match.py   matches a request to an existing employee report
  app/report_register.py   BI report register (owners, revisions, reviewed changes)
  app/request_handoff.py   assignments from an Ask result to a report owner, with frozen evidence
  app/steps.py, classify.py, geo.py, decider.py, simulator.py   six analysis steps, /api/v2/classify, country check, Jev, simulator
  app/pipeline.py    orchestrates stages, emits events
  app/agents/        intent, evidence, spec agents + read-only catalog tools
  app/llm.py         OpenAI access: text, JSON and tool-calling loop; "mock" = offline
  app/graph.py       catalog → Explorer graph (entities, edges, status, flags)
  app/load_datapack.py  python -m app.load_datapack [--reset]: load catalog + presets into MongoDB
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
- `POST /api/v2/chat` – same body; returns JSON showing the input as understood (`received`, `question`, `source`, `length`, `new_conversation`). Runs no agents and saves nothing
- `POST /api/v2/classify` – body `{request}`; returns urgency (vector vote, or deadline words), domain, market, product, governed KPIs, semantic model, existing report (yes/no), plus `steps`: SinceAI's six analysis steps (`app/steps.py`), also shown in the Ask flow's first step. No chat model and nothing saved
- `POST /api/simulator/turn` – body `{speaker: "A"|"B", text, history}`; streams `gate` (label, probability, who decided, ms, tokens, Jev cost), then `searching` and either `reply` (C's answer), `needs_context` (too vague, C stays quiet) or `already_answered`. Saves nothing (`app/simulator.py`, `app/agents/gate.py`)
- `GET  /api/conversations?limit=`, `GET /api/conversations/{id}` – chat history: saved as soon as a question arrives, with messages, runs and state, so a conversation can be reopened and continued (`frontend/src/lib/conversations.ts`)
- `DELETE /api/conversations/{id}` – removes the chat, its intents, evidence, specs, agent runs and its live requests in the vector store. Accepted actions, SinceAI's data and the catalog stay
- `GET  /api/graph` – Estate Explorer entities and edges from the live catalog
- `GET  /api/specs?conversation_id=` – DashboardSpec versions with status (draft / approved / rejected / superseded)
- `GET  /api/agent-runs?conversation_id=` – audit log of agent runs
- `GET  /api/briefings/{team}` (`commercial`, `supply`) – the team briefing; `PUT …/selection` pins views; `POST …/actions`, `PATCH …/actions/{id}` – briefing actions
- `GET/POST /api/conversations/{cid}/runs/{rid}/dashboard`, `…/dashboard/answers`, `…/dashboard/build` – dashboard questions, brief and build for an Ask result
- `GET  /api/dashboards`, `GET /api/dashboards/{id}` – saved dashboards (`items`, `storage_mode`)
- `GET  /api/report-register`, `…/titles`, `…/{report_id}`; `POST …/{report_id}/changes` – BI report register and reviewed changes
- `GET  /api/conversations/{cid}/runs/{rid}/handoff`; `POST/PATCH …/handoff/actions` – owner assignments from a result
- `GET/POST /api/actions`, `GET/PATCH /api/actions/{id}` – follow-up actions
- `GET  /api/requests`, `/api/datapack`, `/api/stages` – request queue, workbook summary, flow stage names

### Models
- OpenAI GPT-6 family. `MODEL_REASONING` (default `gpt-6-astra`) for discovery reasoning and spec; `MODEL_FAST` (default `gpt-6-luna`) for grill-me and summaries. Verify exact IDs in the OpenAI dashboard.
- `LLM_PROVIDER=mock` runs fully offline with rule-based extraction. Default when no `OPENAI_API_KEY` is set.
- Jev requests go to TypeSafe, hosted in the US: no EU option is stated and zero retention is enterprise-only. Fine for this synthetic data; review before production.
- Privacy position: the model sees catalog metadata and the user's question, not raw production data. Production path: models hosted in SinceAI's own Azure tenant (EU region).

### Database
- MongoDB when `MONGODB_URI` is set, otherwise in-memory (data lost on restart). Database name: `MONGODB_DB` (default `analytics_manager`).
- The catalog lives in MongoDB. On startup an empty database is seeded from `app/data/*.json`; `python -m app.load_datapack --reset` reloads it.
- Collections: `conversations`, `intents`, `evidence`, `specs`, `agent_runs`, `catalog_measures`, `catalog_dimensions`, `catalog_datasets`, `catalog_assets`, `catalog_relationships`, `presets`.
- Registered or extended reports are written back to `catalog_assets`, so they survive restarts and are reused.
- Live: MongoDB Atlas, project **Bayer2026**, Cluster0 (M0, AWS Paris), database `analytics_manager`. The vector indexes `vector_index` on `request_vectors` (150 Business_Requests rows plus live `REQ-APP-…` requests) and `kpi_vectors` (18 KPIs) are 1536-dimension cosine indexes built from OpenAI `text-embedding-3-small`. Network access allows `0.0.0.0/0` because Container Apps has no fixed outgoing IP; keep the database password strong.
- Tests use `mongomock` through an async adapter (`tests/fakes.py`).
- The MongoDB Atlas MCP connector works (read-only queries, index and access-list inspection).

## Request triage and vector search (`app/triage.py`, `app/vectors.py`)
- Business_Requests urgency/status labels are not predictable from text (all 10 texts have mixed labels; best possible 54% vs 52% majority), so no classifier.
- Urgency: stated (grill-me "When do you need this?") / inferred (time words, quoted evidence, model claims verified) / default normal. Status is not shown while the request is being understood (Understand the request shows urgency only). When the intent is complete the request is created as `REQ-APP-…` with status new and added to the vector corpus (`request_vectors` in Atlas, or in memory); the decision step sets it to triaged and shows the tag. Later requests count it as a duplicate. `build_vectors` keeps these live requests and re-embeds them.
- Vector search: duplicate and similar requests at intake, KPI suggestion chips. OpenAI embeddings or local hashed fallback; MongoDB Atlas `$vectorSearch` (`python -m app.build_vectors`) or in-memory. Endpoints `/api/requests/similar`, `/api/requests/clusters`, `/api/requests/label-check`.

## Deployment
Every option serves frontend and API from one address (no CORS, no `VITE_API_BASE`).

**Live (free setup below):** app https://analytics-manager.lenguyenhanhoan.workers.dev (Cloudflare Worker, Free plan) → backend https://analytics-manager-api.greensea-e888302f.francecentral.azurecontainerapps.io (Azure Container App `analytics-manager-api`, resource group `analytics-manager-rg`, France Central, Azure for Students). Both run release `8545d81` (PR #4).

**Branches:** work on `main`; it is the production branch and every push to it releases. `version-2`/`version-4` are older lines kept in step with `main`.

**Free (current choice): Cloudflare Workers Free + Azure Container Apps (`docs/DEPLOY_FREE.md`)**
- Frontend: `deploy/cloudflare/wrangler.free.jsonc` + `src/proxy.js`, static assets, `/api/*` forwarded to `BACKEND_URL`. No tunnel.
- Every push to `main` starts `deploy-live.yml` (requires `AZURE_CLIENT_ID`/`AZURE_TENANT_ID`/`AZURE_SUBSCRIPTION_ID` from `containerapp.sh github` (managed identity + OIDC, works where the school blocks app registrations), `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`; missing secrets fail clearly). It calls `backend-image.yml` to test, build, switch Azure to the commit's image and verify the ready revision and commercial briefings API, then calls `frontend-deploy.yml` to run `deploy:free` and verify the live briefings page/API. `version-2`/`version-4` pushes only test and build. `deploy/push-live.sh` (`git live` alias) safely publishes committed changes to `main` without force-pushing.
- Not yet active: the five secrets are missing, so Deploy live fails at its credential check and releases are manual (below). `containerapp.sh github` created the managed identity `bayer2026-github-deploy`, but its role assignment failed ("Role assignment failed"): the signed-in account may lack permission to assign roles (needs Owner or User Access Administrator on the resource group), or the identity was not yet visible; retry, then check the account's role on the subscription.
- Manual release: in Cloud Shell or Git Bash (not PowerShell, where `IMAGE=… bash …` does not work), `IMAGE=ghcr.io/hoanlenguyen/bayer2026-backend:<commit sha> bash deploy/azure/containerapp.sh update`, check with `containerapp.sh image`, then `npm run deploy:free` in `deploy/cloudflare` (Node 22, no Docker).
- Backend: `.github/workflows/backend-image.yml` pushes `ghcr.io/<owner>/bayer2026-backend`; `deploy/azure/containerapp.sh create|update|jev|github|url|logs` (Cloud Shell) runs it on Container Apps, 0.5 vCPU / 1 GiB, 0 to 1 replica, secrets as Container Apps secrets, no Log Analytics. Atlas must allow `0.0.0.0/0`.

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
pytest                 # 249 tests, offline (mock model, mongomock): decision rules, agents, triage and vectors, briefings, dashboards, register, API flows
python -m app.load_datapack     # load catalog into MongoDB (needs MONGODB_URI)

# frontend (proxies /api to :8000)
cd frontend && npm install && npm run dev

# both in Docker (from the repository root; keys in backend/.env)
docker compose up --build        # http://localhost:5173
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
- [x] Backend: pipeline, decision formula (unit tested), mock + OpenAI provider, MongoDB/in-memory store
- [x] Ask page with department presets, grill-me questions and live processing flow
- [x] Estate Explorer on the plant catalog (`/api/graph`)
- [x] Agents for intent, evidence and spec with tool calling, verification, fallback and audit log
- [x] MongoDB persistence for catalog, conversations, intents, evidence, specs, agent runs
- [x] OpenAI provider with a real key (live: `gpt-6-astra`, `gpt-6-luna`, `text-embedding-3-small`)
- [x] MongoDB Atlas connected, with Atlas Vector Search for requests and KPIs
- [x] SinceAI synthetic workbook loaded into the catalog
- [x] Follow-up actions, team briefings, BI report register, owner hand-off, in-app dashboard builder (PR #3, PR #4)
- [x] Live deployment: Cloudflare Worker (Free) + Azure Container Apps, release `8545d81`
- [ ] Automatic releases: add the five GitHub secrets and fix the managed identity's role assignment (see Deployment)
- [ ] Validate generated PBIP in Power BI Desktop (PBIP generation is no longer in the Ask flow)
