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
  → Intent extraction (/grill-me)          AI, asks at most 2 questions
  → Analytics discovery (/explore)         AI + catalog search
  → Governance check (per candidate)       deterministic Python
  → Decision formula                       deterministic Python
       ├─ Reuse        → link to existing report (no new PBIP)
       ├─ Extend       → Evidence → Spec (change) → updated PBIP
       ├─ Create       → Evidence → Spec (new)    → new PBIP → governance check
       └─ Not feasible → ask the user to adjust the intent
```

Rules:
- The AI extracts facts (intent fields, matching measures). **Python decides.** Same inputs, same decision.
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

## Architecture

```
frontend/  React + TypeScript + Vite
  #ask       Ask page: chat, department presets, live processing-flow panel
  #explorer  Estate Explorer: entity details + relationship graph ("molecular view")
             (still uses the older sales sample data; to be switched to the plant catalog)
backend/   Python 3.12+, FastAPI
  app/main.py        HTTP API, Server-Sent Events stream of pipeline events
  app/pipeline.py    orchestrates stages, emits events
  app/llm.py         model access: "openai" or "mock" provider
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

### Models
- OpenAI GPT-6 family. `MODEL_REASONING` (default `gpt-6-astra`) for discovery reasoning and spec; `MODEL_FAST` (default `gpt-6-luna`) for grill-me and summaries. Verify exact IDs in the OpenAI dashboard.
- `LLM_PROVIDER=mock` runs fully offline with rule-based extraction. Default when no `OPENAI_API_KEY` is set.
- Privacy position: the model sees catalog metadata and the user's question, not raw production data. Production path: models hosted in Bayer's own Azure tenant (EU region).

### Database
- MongoDB when `MONGODB_URI` is set, otherwise in-memory (data lost on restart).
- Collections: `conversations` (messages, intent, runs with events).

## Secrets
- Never commit keys. `backend/.env` is git-ignored; `backend/.env.example` lists variable names only.
- Never paste keys into chat.

## Commands

```bash
# backend
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
pytest                 # 16 tests: decision rules and full API flows

# frontend (proxies /api to :8000)
cd frontend && npm install && npm run dev
```

## Conventions
- Python: type hints, Pydantic models for API payloads, pure functions for scoring.
- TypeScript: strict mode; shared API types in `frontend/src/api/types.ts`.
- UI copy: plain language for non-technical plant staff. No em-dashes.
- All sample data is fictional and labelled as sample data in the UI.
- Commit messages: imperative mood, explain why.

## Status
- [x] Build plan page: https://claude.ai/artifact/NWgjoee8m5ZYAYoBkDmYCC
- [x] Proposal draft (`docs/PROPOSAL.md`, earlier "Curator" concept, partly superseded by this file)
- [x] Estate Explorer prototype (frontend)
- [x] Backend: pipeline, decision formula (unit tested), mock + OpenAI provider, MongoDB/in-memory store, PBIP skeleton
- [x] Ask page with department presets, grill-me questions, approval step and live processing flow
- [ ] Test the OpenAI provider with a real key (only the mock provider has been run so far)
- [ ] Switch Estate Explorer to the plant catalog
- [ ] Load Bayer synthetic dataset into the catalog
- [ ] Action tracker (follow-up actions with owners)
- [ ] Validate generated PBIP in Power BI Desktop
