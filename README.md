# Agentic Analytics Manager

Bayer Hackathon 2026 entry for "Build Less, Build Better: AI for Governed Analytics".

An AI workspace for Bayer Pharmaceuticals' analytics estate. A business user asks for a report or a number; the system finds what already exists across 360 Power BI and Tableau assets, checks KPI definitions, usage, ownership, lineage and governance, and recommends with evidence whether to **reuse, repair, consolidate, migrate or build**. New reports are thin Power BI (PBIP) reports on shared semantic models, generated only after a person approves. Follow-up work goes into an action tracker.

- `CLAUDE.md`: scope, data mapping, decision rules, architecture (source of truth)
- `materials/`: Bayer Pharmaceuticals × Since AI 2026 Builder Data Pack (synthetic)
- `backend/`: FastAPI pipeline, agents, decision rules, PBIP generator. See `backend/README.md`
- `frontend/`: React app: Ask, Estate Explorer, Actions. See `frontend/README.md`
- `docs/PROPOSAL.md`: early concept write-up (partly outdated)

## Quick start

```bash
cd backend && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

```bash
cd frontend && npm install && npm run dev    # http://localhost:5173
```

All data is synthetic. No patient or HCP data is used.

## Workbook-backed molecular view

The molecular explorer now includes source-row evidence, upstream/downstream lineage, explicit migration candidates and live action links. The **Workbook** page exposes every row of all 24 supplied sheets. [Data contract and demo walkthrough](docs/BAYER_MOLECULAR.md). Existing investigation and action flows are preserved.
