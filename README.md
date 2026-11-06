# Agentic Analytics Manager

Bayer Hackathon 2026 entry for "Build Less, Build Better: AI for Governed Analytics".

An AI workspace for a pharma manufacturing plant. Before anything is built it checks what already exists, decides with a transparent formula whether to reuse, extend or create, and only then generates version-controlled Power BI (PBIP) files, with a human approval step.

- `CLAUDE.md`: scope, architecture, decision formula and conventions (source of truth)
- `backend/`: FastAPI pipeline, decision rules, PBIP generator. See `backend/README.md`
- `frontend/`: React app with the Ask page (chat + live processing flow) and the Estate Explorer. See `frontend/README.md`
- `docs/PROPOSAL.md`: earlier concept write-up
- Build plan (published page): https://claude.ai/artifact/NWgjoee8m5ZYAYoBkDmYCC

## Quick start

```bash
cd backend && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

```bash
cd frontend && npm install && npm run dev    # http://localhost:5173
```
