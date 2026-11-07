# CLAUDE.md

Project context for Claude Code and for the team. Keep this file current: it is the source of truth for scope, architecture and decisions.

## Project

**AnalytIQ Intelligence**. SinceAI Hackathon 2026, challenge "Build Less, Build Better: AI for Governed Analytics".

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

The system recommends; people act on the recommendation. It changes and retires no report and publishes nothing to Power BI. The one thing it builds is an in-app dashboard: when the recommendation is a new build and every requested KPI can be calculated from the workbook, the employee reviews a dashboard brief and builds it in AnalytIQ (`app/dashboard_builder.py`). Review, repair and migration stay with the responsible owner, as assignments in the BI report register.

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
- Conversation simulation (`/simulator`, last in the sidebar, under BI Portfolio): SinceAI and Brainrot chat (speakers `A` and `B` in the API; AnalytIQ is `C`), the gate agent labels each sentence off topic, business talk or needs a decision (Jev, then GPT, then rules; `speak` 0.70, `stay_quiet` 0.30 in `JEV_THRESHOLDS`). Its `conversation` phase is on whenever `TYPESAFE_API_KEY` is set. Only "needs a decision" runs `classify_request` on the open thread. A request too vague to check (no KPI, or a loose match with no product or market) gets no reply: AnalytIQ keeps listening, and business talk that follows is checked with it until there is enough. It never asks questions; AnalytIQ's sentence comes from Python templates, never a model, and its evidence is the same verdict and six steps as Ask (`analyse()` in `pipeline.py`, shared by both), and only a plain Reuse is called "already exists". Its accuracy on this question has not been measured yet.
- A preset's own text skips the Intent model call: its intent is already known.
- Guided dashboard examples (`app/guided_examples.py`, served by `GET /api/guided-examples`): the Ask start screen shows 2 of 5 starters, 3 more under "More example questions". Each fixes product, two countries, two governed KPIs and a by-country breakdown. A chip sends `guided_id`; the two questions (purpose, which also sets the lead KPI; period: all workbook months or the last 6, resolved from the workbook) accept only the offered options, by `choice_id` or exact label, and never go through the intent agent. Any other reply repeats the step and changes nothing. The finished intent goes through the normal analysis, then the builder's review opens by default. A fresh guided run stays reviewable even when an identical dashboard exists (`matches_saved`); Build then resolves to that immutable artifact and says so (`exact_reuse`). Guided results carry `presentation: market_comparison`, `lead_measure` and `market_order`, and the saved page shows two trend panels (one per KPI, both countries), a lead-KPI latest-month comparison and a month inspector with workbook rows. Every starter is checked against the workbook before it is offered (`verify`). Typing the same sentence in the composer is ordinary Ask.
- Token use is recorded per agent run (`usage` in `agent_runs`) and per question (`runs[].tokens`).
- Build hand-off (`frontend/src/components/ask/BuildHandoff.tsx`): Build dashboard sends the one build POST at once and replaces the brief with "Preparing your dashboard", four steps from the receipt (confirm the brief, match the workbook evidence, prepare the view, save and open). Step 4 says "Dashboard saved" only for a validated `status: "built"` response with a `dashboard_id` (or the same from the single recovery read). A new build opens at max(confirmed save, approval + 4.5 s) (`READING_WINDOW_MS`), exactly once, and only if this attempt still owns the screen: leaving Ask, Back, opening an entity, hiding the tab, switching chats or New question cancel opening by itself, and step 4 then offers Open saved dashboard. The parent verdict hears `onBuilt` only after the hand-off finishes. A 409 offers Review updated brief; a server error, unreadable answer or dropped connection is checked once against the run (never a second POST) and says the save could not be confirmed, with Try building again or Reload the brief. A POST answered with `reused` (another build saved it first) stops the workflow and shows the ordinary existing-dashboard link; a guided exact reuse stays in the workflow and says so. The saved page repeats the summary under "Dashboard brief and sources".
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
             "How this was decided" panel, dashboard review and build, owner hand-off; History for this tab (sessionStorage index)
  #explorer  Estate Explorer: entity details + relationship graph ("molecular view"),
             loaded from GET /api/graph (live plant catalog, same governance scoring as the Ask flow)
  /cala-graph  Knowledge graph: full-screen 3D canvas (path route, "Knowledge Graph" in the sidebar), loaded from
             GET /api/graph and grouped by domain (workspace) using the catalog's own links
  /introduction  Landing page, no sidebar (logo, the problems AnalytIQ solves, live knowledge graph); /index redirects here
  /simulator   Conversation simulation (see Rules above)
  /bi-estate   BI Portfolio: the BI department head's tracker of every reporting asset (see BI Portfolio below);
             /bi-estate/<id> details (?tab=governance&finding=<code>), /bi-estate/compare/<a>/<b> comparison and owner review,
             /bi-estate?view=governance (Evidence & governance index), /bi-estate/governance/{evidence|risks|documents|assessments}/<id>
  /briefings   Team briefings (Commercial, Supply) with the Monthly Pulse chart, meeting mode, and the BI report register tab
  /dashboards/<id>         a saved in-app dashboard (stable URL)
  /workbook-view/<a>/<b>   verified workbook view behind an employee report
  Routes other than #ask/#explorer are path routes: hosting must return index.html for unknown paths (SPA fallback).
backend/   Python 3.12+, FastAPI
  app/main.py        HTTP API, Server-Sent Events stream of pipeline events; includes the routers below
  app/briefings.py, briefing_routes.py, briefing_definitions.py   team briefings from the workbook
  app/dashboard_intake.py, dashboard_builder.py, dashboard_routes.py   dashboard questions, brief, build, saved dashboards
  app/employee_report_match.py   matches a request to an existing employee report
  app/bi_estate.py   BI Portfolio: inventory, findings, pairs, owner reviews, AnalytIQ opens, demo identities
  app/governance.py  Evidence & governance: evidence items, risks, rule and document applicability, registered documents,
                     mappings, exceptions, owner evidence, reviews with assessment snapshots (app/data/governance/ demo sources)
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
- `GET  /api/guided-examples` – the start screen's guided examples, in order, with their offered choices
- `POST /api/chat` – body `{conversation_id?, message, preset_id?, guided_id?, choice_id?}`; streams SSE events: `stage` (started/done with payload), `message`, `question`, `done`, `error`
- `POST /api/v2/chat` – same body; returns JSON showing the input as understood (`received`, `question`, `source`, `length`, `new_conversation`). Runs no agents and saves nothing
- `POST /api/v2/classify` – body `{request}`; returns urgency (vector vote, or deadline words), domain, market, product, governed KPIs, semantic model, existing report (yes/no), plus `steps`: SinceAI's six analysis steps (`app/steps.py`), also shown in the Ask flow's first step. No chat model and nothing saved
- `POST /api/simulator/turn` – body `{speaker: "A"|"B", text, history}`; streams `gate` (label, probability, who decided, ms, tokens, Jev cost), then `searching` and either `reply` (C's answer), `needs_context` (too vague, C stays quiet) or `already_answered`. Saves nothing (`app/simulator.py`, `app/agents/gate.py`)
- `GET  /api/conversations?limit=`, `GET /api/conversations/{id}` – conversations saved as soon as a question is accepted, with messages, runs and state. The Ask sidebar does not use the list: History is per browser tab (`frontend/src/lib/conversations.ts`, `sessionStorage` key `analytiq.ask.session.v1`, IDs, titles and update times only) and reopens a conversation by ID only if this tab started it. An accepted, saved message's outgoing `user_message` event carries `history: {_id, title, updated_at}`; rejected ones do not, and the stored transcript is unchanged. A dashboard's "Open source conversation" shows only for this tab's own conversation
- `DELETE /api/conversations/{id}` – removes the chat, its intents, evidence, specs, agent runs and its live requests in the vector store. Accepted actions, SinceAI's data and the catalog stay
- `GET  /api/graph` – Estate Explorer entities and edges from the live catalog
- `GET  /api/specs?conversation_id=` – DashboardSpec versions with status (draft / approved / rejected / superseded)
- `GET  /api/agent-runs?conversation_id=` – audit log of agent runs
- `GET  /api/briefings/{team}` (`commercial`, `supply`) – the team briefing; `PUT …/selection` pins views; `POST …/actions`, `PATCH …/actions/{id}` – briefing actions
- `GET/POST /api/conversations/{cid}/runs/{rid}/dashboard`, `…/dashboard/answers`, `…/dashboard/build` – dashboard questions, brief and build for an Ask result. Ready and built states carry an optional `receipt` (scope, period, measures with KPI IDs and units, months, rows, record classes, groups, arrangement sentence) computed from the assembled artifact by `build_receipt`; `GET /api/dashboards/{id}` returns it too. It is outside the review token and the saved artifact
- `GET  /api/dashboards`, `GET /api/dashboards/{id}` – saved dashboards (`items`, `storage_mode`)
- `GET  /api/report-register`, `…/titles`, `…/{report_id}`; `POST …/{report_id}/changes` – BI report register and reviewed changes
- `GET  /api/conversations/{cid}/runs/{rid}/handoff`; `POST/PATCH …/handoff/actions` – owner assignments from a result
- `GET/POST /api/actions`, `GET/PATCH /api/actions/{id}` – follow-up actions
- `GET  /api/bi-estate?q=&origin=&platform=&issue=&lifecycle=&owner_state=&product=&market=&sort=&direction=&page=&size=` – BI Portfolio rows, counts, facets and sources; `GET /api/bi-estate/{id}` details; `GET /api/bi-estate/pairs/{a}/{b}` comparison
- `POST /api/bi-estate/{id}/opens` – body `{view_id, source}`; one AnalytIQ open per rendered, visible view (idempotent)
- `POST /api/bi-estate/{id}/owner` (steward) – owner assignment overlay, `expected_seq` for concurrency
- `POST /api/bi-reviews` (steward), `GET /api/bi-reviews/{id}`, `POST /api/bi-reviews/{id}/events` (owner response or steward decision); `GET /api/bi-identity` – demo personas
- `GET  /api/bi-governance?tab=policies|risks|evidence&q=&<portfolio filters>&page=&size=&at=` – scoped index (one entry per document, distinct dashboards); `GET …/assets/{id}?at=`, `…/evidence/{id}?asset=`, `…/risks/{id}`, `…/documents/{id}?asset=`, `…/documents/{id}/revisions/{n}/original`, `…/assessments/{id}`
- `POST /api/bi-governance/documents` (steward; register or next revision, checked against `GET …/sources`), `…/documents/{id}/mappings` (steward), `…/mappings/{id}/decision` (reviewer, not the proposer), `…/exceptions` (steward), `…/exceptions/{id}/decision` (reviewer), `…/assets/{id}/evidence` (active owner), `…/evidence/{id}/reviews` (reviewer or steward), `…/risks/{id}/events` and `…/documents/{d}/clauses/{c}/assets/{a}/events` (assign, request evidence, assessment)
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

## BI Portfolio (`app/bi_estate.py`, `frontend/src/pages/BIPortfolioPage.tsx`)
- Inventory: the workbook's 360 assets, the 3 app employee reports (BR-*, owner = KPI steward) and every dashboard built in Ask (creator from `created_by`, captured at build; owner Unassigned until the steward assigns one). Nothing is written back to the workbook.
- Dates keep their precision (day from the workbook, timestamp from the app). Refresh last success is Unknown: the workbook has no such field. Imported usage (Asset_Usage) and AnalytIQ opens are always shown apart.
- Findings: needs an owner, refresh issue, definition conflict (`definition_conflict` KPIs only; duplicate candidates and local variants are weaker context), scope mismatch (SCOPE-1, report scope vs its model via Markets), consolidation candidate (PAIR-1 v1: same product and market, at least 2 shared canonical approved KPI IDs; 2 pairs in this workbook), marked for retirement, source date anomaly.
- Owner reviews: one case per pair (A/B and B/A are the same case), each owner responds only for the report they actively own (one person owning both answers once), the steward decides keep both / remediate / consolidation plan / dismiss with a reason. Changed evidence must be acknowledged. Closed cases stay as history; a new review on the pair is the next generation. Decisions are recorded only, never executed.
- Identity: demo personas resolved on the server from the `X-AnalytIQ-Actor` header (`DEMO-BI-STEWARD`, `DEMO-EMPLOYEE`, `DEMO-GOV-REVIEWER`, `DEMO-AUDITOR` (read only), active owner IDs). Not a sign-in; production needs the company's identity provider.
- Tracker finding "Open source signal" (open Governance_Signals rows, imported). Finding chips link to the dashboard's Evidence & governance tab with that finding focused.
- Collections: `bi_open_events`, `bi_owner_events`, `bi_cases`, `bi_case_events` (append-only, unique `_id`).

## Evidence & governance (`app/governance.py`, `frontend/src/pages/BIGovernance.tsx`)
- Scope: one BI estate per installation, so every inventory asset is in the portfolio (`scoped_assets`). Every read and write checks the asset and the document's access; hidden documents leave no title, count or URL (404 for both missing and hidden).
- Evidence: workbook rows with sheet, row, record ID and workbook SHA (asset, workspace, owner, model, bindings, KPI definitions, lineage, signals, quality, last usage month); AnalytIQ checks DEF-1 and SCOPE-1 as derived items linking the rows they join; saved dashboards (approved brief, creator, cited source rows, marked if the row changed); app reports (KPI definition, report register events); owner submissions (owner statement until a reviewer verifies; superseding keeps the old item). Reading evidence never counts as an open.
- Authority labels: Company document, Demo document, Challenge workbook (Governance_Rules RULE-001..008, no version or dates), AnalytIQ check, Source observation, AnalytIQ record, Owner statement.
- Applicability per rule is Python over recorded facts (applies / undetermined / not applicable), with results finding, assessed clear, evidence missing, exception, expired exception, cannot be checked. RULE-006 needs Tableau plus legacy or a migration signal; RULE-005 needs a high-reach signal (no reach threshold exists). Registered documents apply only through an explicit mapping a reviewer accepted, and only from the revision effective on the requested date (`at`).
- Risks: derived (definition, scope, owner, consolidation, refresh, chronology) or one per imported signal. Source severity, rule priority and AnalytIQ's action priority are separate. Closing a review needs a reason and cited evidence and keeps the imported status. Assessments snapshot cited evidence values, clause revision text, facts, checks, owner and workbook SHA; reopening shows what changed since.
- Demo document `DEMO-POL-001` (synthetic, two revisions, `app/data/governance/`); `DEMO-HR-001` is the unrelated fixture. No company policy was supplied.
- Collections: `gov_documents`, `gov_doc_revisions`, `gov_mappings`, `gov_exceptions`, `gov_evidence`, `gov_events` (unique `_id`, expected-sequence checks, retries return the first record). In memory mode they are lost on restart.

## Request triage and vector search (`app/triage.py`, `app/vectors.py`)
- Business_Requests urgency/status labels are not predictable from text (all 10 texts have mixed labels; best possible 54% vs 52% majority), so no classifier.
- Urgency: stated (grill-me "When do you need this?") / inferred (time words, quoted evidence, model claims verified) / default normal. Status is not shown while the request is being understood (Understand the request shows urgency only). When the intent is complete the request is created as `REQ-APP-…` with status new and added to the vector corpus (`request_vectors` in Atlas, or in memory); the decision step sets it to triaged and shows the tag. Later requests count it as a duplicate. `build_vectors` keeps these live requests and re-embeds them.
- Vector search: duplicate and similar requests at intake, KPI suggestion chips. OpenAI embeddings or local hashed fallback; MongoDB Atlas `$vectorSearch` (`python -m app.build_vectors`) or in-memory. Endpoints `/api/requests/similar`, `/api/requests/clusters`, `/api/requests/label-check`.

## Deployment
Every option serves frontend and API from one address (no CORS, no `VITE_API_BASE`).

**Live (free setup below):** app https://analytics-manager.lenguyenhanhoan.workers.dev (Cloudflare Worker, Free plan) → backend https://analytics-manager-api.greensea-e888302f.francecentral.azurecontainerapps.io (Azure Container App `analytics-manager-api`, resource group `analytics-manager-rg`, France Central, Azure for Students). Both run release `eece863` (deployed and checked on 7 November 2026).

**Branches:** work on `main`; it is the production branch. A push to `main` does not reach the live site until it is deployed by hand (see below). `version-2`/`version-4` are older lines kept in step with `main`.

**Free (current choice): Cloudflare Workers Free + Azure Container Apps (`docs/DEPLOY_FREE.md`)**
- Frontend: `deploy/cloudflare/wrangler.free.jsonc` + `src/proxy.js`, static assets, `/api/*` forwarded to `BACKEND_URL`. No tunnel.
- Every push to `main` starts `deploy-live.yml` (requires `AZURE_CLIENT_ID`/`AZURE_TENANT_ID`/`AZURE_SUBSCRIPTION_ID` from `containerapp.sh github` (managed identity + OIDC, works where the school blocks app registrations), `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`; missing secrets fail clearly). It calls `backend-image.yml` to test, build, switch Azure to the commit's image and verify the ready revision and commercial briefings API, then calls `frontend-deploy.yml` to run `deploy:free` and verify the live briefings page/API. `version-2`/`version-4` pushes only test and build. `deploy/push-live.sh` (`git live` alias) safely publishes committed changes to `main` without force-pushing.
- Not yet active, by team decision: releases stay manual for now. With the secrets missing, Deploy live tests and builds the image, deploys nothing, and its `reminder` job writes the exact manual commands for the commit to the run summary; `git live` prints them too.
- **Rule for anyone pushing to `main` (Claude included): after the push, remind the user to deploy by hand, backend first, then frontend, with the commands below and the commit's image tag.** `containerapp.sh github` created the managed identity `bayer2026-github-deploy`, but its role assignment failed ("Role assignment failed"): the signed-in account may lack permission to assign roles (needs Owner or User Access Administrator on the resource group), or the identity was not yet visible; retry, then check the account's role on the subscription.
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
pytest                 # 302 tests, offline (mock model, mongomock): decision rules, agents, triage and vectors, briefings, dashboards, register, API flows
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
- [x] Live deployment: Cloudflare Worker (Free) + Azure Container Apps, release `eece863`
- [x] BI Portfolio for the BI department head (`/bi-estate`), app renamed to AnalytIQ intelligence
- [x] Evidence & governance in the BI Portfolio
- [ ] Automatic releases: add the five GitHub secrets and fix the managed identity's role assignment (see Deployment)
- [ ] Validate generated PBIP in Power BI Desktop (PBIP generation is no longer in the Ask flow)
