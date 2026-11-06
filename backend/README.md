# Backend

FastAPI service for the Agentic Analytics Manager. It reads Bayer's synthetic data pack, decides for each business request whether to **reuse, repair, consolidate, migrate or build** analytics, and streams every step to the frontend as Server-Sent Events.

All data is synthetic (Bayer Pharmaceuticals × Since AI 2026 Builder Data Pack). There is no patient or HCP data, and figures are not Bayer performance.

## Quick start

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### Windows (PowerShell)

These commands call the virtual environment's own Python, so they work even when PowerShell blocks activation scripts:

```powershell
python -m venv .venv                                            # once; use "py -m venv .venv" if python is not found
.venv\Scripts\python.exe -m pip install -r requirements.txt     # once, and again after pulling new requirements
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

To use plain `uvicorn` and `pip` instead, activate the environment first. If PowerShell says "running scripts is disabled", allow it for the current window only:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.venv\Scripts\Activate.ps1
```

Other commands follow the same pattern on Windows, for example `.venv\Scripts\python.exe -m app.load_datapack` and `.venv\Scripts\python.exe -m pytest`.

### Check it runs

Wait for `Application startup complete.`, then open http://localhost:8000/api/health. It should report `"provider": "mock"` and `"store": "memory"` until you add keys.

Then start the frontend (`../frontend`, `npm run dev`) and open http://localhost:5173.

## Configuration (`.env`)

Copy `.env.example` to `.env`. Every setting is optional; without any, the app runs fully offline.

| Variable | Default | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | empty | Enables the OpenAI agents. Without it, agents use their rule-based path |
| `LLM_PROVIDER` | `auto` | `auto` (OpenAI if a key is set), `openai` or `mock` |
| `OPENAI_BASE_URL` | empty | OpenAI-compatible endpoint, for example an Azure-hosted deployment |
| `MODEL_REASONING` | `gpt-6-astra` | Evidence and spec agents. Check the exact ID in your OpenAI dashboard |
| `MODEL_FAST` | `gpt-6-luna` | Intent agent and explanations |
| `MONGODB_URI` | empty | MongoDB connection string. Empty = in-memory storage (lost on restart) |
| `MONGODB_DB` | `analytics_manager` | Database name |
| `DATAPACK_PATH` | `../materials/…Builder_Data_Pack.xlsx` | Workbook to load |
| `OUTPUT_DIR` | `output` | Where generated PBIP projects are written (git-ignored) |
| `STAGE_DELAY` | `0.35` | Pause between stages so the flow is visible in the UI (seconds) |
| `CORS_ORIGINS` | `http://localhost:5173,…` | Allowed frontend origins |

Never commit `.env` and never paste keys into chat.

## MongoDB

With `MONGODB_URI` set, an empty database is seeded from the workbook on first start. To load or reload it explicitly:

```bash
python -m app.load_datapack            # load if the database is empty
python -m app.load_datapack --reset    # replace data pack, catalog and presets
```

Conversations, specs and actions are kept on reset. For MongoDB Atlas, add your computer's IP address under **Network Access** first.

| Collections | Contents |
|---|---|
| `datapack_<sheet>` | Every table sheet of the workbook, row for row (22 sheets) |
| `catalog_measures`, `catalog_models`, `catalog_assets`, `catalog_owners`, `catalog_workspaces`, `catalog_products`, `catalog_markets`, `catalog_lineage`, `catalog_rules`, `catalog_dimensions`, `catalog_meta` | The catalog the pipeline reasons over. Approved and repaired reports are written back to `catalog_assets` |
| `presets` | 10 Bayer business requests + 4 estate scenarios |
| `conversations` | Messages, intent and every streamed event per run |
| `intents`, `evidence`, `specs` | Pipeline outputs; specs carry status draft / approved / rejected / superseded |
| `agent_runs` | Audit log: agent, mode, model, steps, duration |
| `actions` | Follow-up actions with history and verification |

## How a request is processed

```
request ─▶ intent agent ─▶ discovery ─▶ governance ─▶ decision ─▶ proposed actions
                                                          │
          reuse ◀───────────────────────────────────────────┤
          not feasible ◀────────────────────────────────────┤
          repair / consolidate / migrate / new build ◀──────┘
               ─▶ evidence agent ─▶ spec agent ─▶ human approval ─▶ PBIP ─▶ register
```

- **The AI extracts, Python decides.** Agents turn words into a structured intent, gather evidence and design the page. Scores, gates and the decision are plain functions in `app/decision.py`, so the same input always gives the same decision.
- **Agents propose, Python verifies.** Unknown KPIs, products, markets and models are removed; proof lines come from catalog facts, never from the model.
- Each decision cites the Bayer rules it applies (RULE-001 to RULE-008). The full rules and thresholds are in `../CLAUDE.md`.
- New reports are **thin reports** that connect to an existing shared semantic model (RULE-001), so a PBIP has a `.pbip` file and a `.Report` folder only. A repair is a maintenance change with no files.

## Code map

| Path | What it does |
|---|---|
| `app/main.py` | HTTP API and SSE streaming |
| `app/settings.py` | Reads `.env` |
| `app/datapack.py` | Workbook → catalog; the 10 request presets and 4 scenarios |
| `app/catalog.py` | Live catalog in memory; loads from or seeds the store |
| `app/decision.py` | Coverage, freshness, governance, gates and the lifecycle decision. Thresholds in `THRESHOLDS` |
| `app/pipeline.py` | Runs the stages, emits events, saves artifacts, registers approved changes |
| `app/agents/` | `intent.py`, `evidence.py`, `spec.py` agents; `tools.py` read-only catalog tools; `base.py` tracing and fallback |
| `app/llm.py` | OpenAI calls: text, JSON and the tool-calling loop |
| `app/facts.py` | Preview numbers from `Product_Market_Monthly` (synthetic) |
| `app/pbip.py` | Approved spec → thin-report PBIP folder (plain Python) |
| `app/actions.py` | Follow-up action proposals, status rules, sample actions |
| `app/graph.py` | Catalog → asset index graph for the frontend |
| `app/store.py` | MongoDB or in-memory storage |
| `app/load_datapack.py` | CLI to load the workbook into MongoDB |

## API

| Method and path | Purpose |
|---|---|
| `GET /api/health` | Model provider and store in use |
| `GET /api/presets` | Request presets and estate scenarios |
| `GET /api/datapack` | Sheet row counts, Bayer rules, usage window |
| `GET /api/requests` | The 150 business requests from the workbook |
| `GET /api/catalog` | Full catalog (measures, models, assets, …) |
| `GET /api/graph` | Entities and edges for the asset index |
| `POST /api/chat` | `{conversation_id?, message, preset_id?}` → SSE stream of `stage`, `message`, `done`, `error` events |
| `POST /api/approve` | `{conversation_id, approved, approver}` → SSE stream of approval, PBIP and register stages |
| `GET /api/conversations`, `GET /api/conversations/{id}` | Stored conversations |
| `GET /api/specs`, `GET /api/agent-runs` | Specs with status; agent audit log (`?conversation_id=` to filter) |
| `GET/POST /api/actions`, `GET/PATCH /api/actions/{id}` | Action tracker. POST returns 409 if an open action already covers the finding; PATCH returns 400 with a plain message for an invalid move |

Try it without the frontend:

```bash
curl -N -X POST localhost:8000/api/chat -H "Content-Type: application/json" -d '{"preset_id":"scn_reuse_eylea_jp"}'
```

## Tests

```bash
pytest                 # 41 tests
```

They cover the data pack mapping, every decision outcome, the migration rules, all three agents (including tool calls against a scripted fake OpenAI client), MongoDB storage (through mongomock), the graph, the action tracker and the full API flows including approval. The frontend's `npm run test:workbench` also replays real backend events through the UI.

Not covered: a live OpenAI key, a real Atlas cluster, and opening the generated PBIP in Power BI Desktop.

## Troubleshooting

- **Windows: "uvicorn is not recognized":** the virtual environment is not active, or the requirements are not installed in it. Use `.venv\Scripts\python.exe -m uvicorn …` as shown in Quick start.
- **"localhost refused to connect" (ERR_CONNECTION_REFUSED):** the backend is not running. Start it again and read the terminal output; if it exits on startup, run the requirements install again (new packages are added over time, for example `openpyxl`).

- **`/api/health` shows `memory` although `MONGODB_URI` is set:** the connection failed; the log says why. Check the Atlas IP access list and the password.
- **Agents show "rules, offline":** no `OPENAI_API_KEY`, or the model call failed. The trace in the processing record shows the reason.
- **Asset index says "/api/graph returned 500", or requests fail after updating the code:** MongoDB still holds an older catalog. The backend now reloads an outdated catalog automatically on start; to force it, run `python -m app.load_datapack --reset` and restart.
- **Changes to the workbook are not picked up:** with MongoDB, run `python -m app.load_datapack --reset`; in-memory storage reloads on restart.
