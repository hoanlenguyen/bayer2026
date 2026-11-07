# Agentic Analytics Manager

SinceAI Hackathon 2026 entry for "Build Less, Build Better: AI for Governed Analytics".

An AI workspace for a pharma manufacturing plant. An employee describes the decision they need to make. Before anything new is built,
Analytics Manager checks the existing BI estate in six steps (metric definitions, existing reports and their usage, data lineage,
trust and ownership, Tableau migration) and recommends what to do: reuse, consolidate, migrate, retire, human review or a new build.
Python makes the decision with a transparent formula; the AI only reads the request and asks at most two clarifying questions.
Every number shown as evidence comes from the workbook, never from a model.

All data is synthetic (the SinceAI builder data pack in `materials/`).

## Live site

**https://analytics-manager.lenguyenhanhoan.workers.dev**

| Page | What it does |
|---|---|
| **Ask** (`/`) | Ask in your own words or pick an example. See the recommendation with its scores and evidence. For an eligible new build, review a dashboard brief and build it in the app; a review, repair or migration goes to the report owner as an assignment |
| **Briefings** (`/briefings`) | Commercial and Supply team briefings with the Monthly Pulse chart and meeting mode; **BI report register** tab |
| **Saved dashboards** (`/dashboards/<id>`) | Dashboards built from Ask, with metric switching, month filters and the source rows behind each figure |
| **Conversation Simulation** (`/simulator`) | Two people talk; Analytics Manager speaks up only when a decision needs evidence |
| **Estate Explorer**, **Knowledge Graph** | The report estate as a relationship graph, and as a 3D map by domain |

Try it: in **Ask**, choose *Build a monthly dashboard for Nubeqa net sales and units shipped in France*, answer *Decide where to
allocate stock* and *All available workbook months*, then **Review and build dashboard → Build dashboard**. October 2026 shows
€37.58m net sales and 33,941 units shipped, both from `Product_Market_Monthly` row 21. The full walkthrough is in
[docs/BRIEFINGS_REVIEW.md](docs/BRIEFINGS_REVIEW.md).

Hosting: Cloudflare Workers (Free plan) serves the app and forwards `/api/*` to the FastAPI backend on Azure Container Apps,
with MongoDB Atlas (data and vector search) and OpenAI models.

## Repository

| Path | Contents |
|---|---|
| `CLAUDE.md` | Scope, flow, decision formula, architecture, API, deployment and conventions. **Source of truth** |
| `backend/` | FastAPI app: agents, decision rules, briefings, dashboards, report register. See `backend/README.md` |
| `frontend/` | React + TypeScript app. See `frontend/README.md` |
| `materials/` | The synthetic builder data pack (workbook) |
| `deploy/`, `docs/DEPLOY_FREE.md` | Live deployment (Cloudflare Worker + Azure Container Apps), plus the VM and paid Cloudflare alternatives |
| `docs/` | Walkthroughs and earlier write-ups (`PROPOSAL.md` is the earlier concept) |
| `DESIGN.md` | UI decisions |

Build plan (published page): https://claude.ai/artifact/NWgjoee8m5ZYAYoBkDmYCC

## Working on the code

`main` is the production branch: every push to `main` starts **Actions → Deploy live**, which tests, deploys the backend to Azure,
checks it, then deploys the frontend to Cloudflare and checks the live pages. Start from the latest `main`, commit, then publish:

```bash
git switch main && git pull --ff-only origin main
```

```bash
git live
```

`git live` (`deploy/push-live.sh`) publishes your commits to `main` without force-pushing; install it once with
`git config alias.live '!bash deploy/push-live.sh'`. Until the one-time GitHub secrets are added, Deploy live stops at its
credential check and releases are manual. Both are described in [docs/DEPLOY_FREE.md](docs/DEPLOY_FREE.md).

Never commit keys or `node_modules`. Keys live in `backend/.env` (git-ignored); `backend/.env.example` lists the names.

## Quick start

```bash
cd backend && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

```bash
cd frontend && npm install && npm run dev    # http://localhost:5173
```

```bash
cd backend && pytest    # 249 tests, offline
```

## Run with Docker

Starts the backend and the frontend together. You need Docker with Compose v2 (`docker compose version`).

1. Create the settings file once. Fill in the keys you have. Leaving every key empty also works: the app then runs offline, with rules instead of models and in-memory storage.

   ```bash
   cp backend/.env.example backend/.env
   ```

2. Start both services from the repository root:

   ```bash
   docker compose up --build
   ```

3. Open http://localhost:5173. The API is also on http://localhost:8000/api/health.

Stop with `Ctrl+C`, or `docker compose down` if you started with `-d`.

How it fits together: the frontend container (nginx) serves the built app and forwards `/api` to the backend container. Keys are read from `backend/.env` when the container starts. They are never copied into an image (`.dockerignore` leaves out every `.env`).

### Avoiding common errors

| Error | Cause | Fix |
|---|---|---|
| `env file backend/.env not found` | No settings file | Step 1 above |
| `failed to read backend/.env: line N: key cannot contain a space` | A comment line in `.env` without `#` in front. Python accepts it, Docker does not | Start every comment line with `#`. Each other line must be `KEY=value` |
| `port is already allocated` / `address already in use` | The local dev servers (uvicorn on 8000, Vite on 5173) are still running | Stop them, or pick other ports: `BACKEND_PORT=8001 FRONTEND_PORT=5174 docker compose up --build` |
| Frontend waits and never starts | The backend health check fails | `docker compose logs backend` shows why, usually a wrong `MONGODB_URI` |
| MongoDB connection refused with `MONGODB_URI=mongodb://localhost:...` | Inside a container, `localhost` is the container itself | Use `mongodb://host.docker.internal:27017` for a database on your machine, or an Atlas URI |
| Old code after a change | Images were not rebuilt | Run with `--build` |

Don't set `DATAPACK_PATH` or `OUTPUT_DIR` for Docker: `docker-compose.yml` sets the paths inside the container. Generated PBIP files are kept in the `pbip-output` volume.
