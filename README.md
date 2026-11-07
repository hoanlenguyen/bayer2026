# Agentic Analytics Manager

SinceAI Hackathon 2026 entry for "Build Less, Build Better: AI for Governed Analytics".

An AI workspace for a pharma manufacturing plant. Before anything is built it checks what already exists, decides with a transparent formula whether to reuse, extend or create, and only then generates version-controlled Power BI (PBIP) files, with a human approval step.

- `CLAUDE.md`: scope, architecture, decision formula and conventions (source of truth)
- `backend/`: FastAPI pipeline, decision rules, PBIP generator. See `backend/README.md`
- `frontend/`: React app with the Ask page (chat + live processing flow) and the Estate Explorer. See `frontend/README.md`
- `docs/PROPOSAL.md`: earlier concept write-up
- Build plan (published page): https://claude.ai/artifact/NWgjoee8m5ZYAYoBkDmYCC

For the team briefing, employee reports, and BI register, see the [review walkthrough](docs/BRIEFINGS_REVIEW.md).

## Quick start

```bash
cd backend && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

```bash
cd frontend && npm install && npm run dev    # http://localhost:5173
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
