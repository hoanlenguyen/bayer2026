# Backend

FastAPI service that runs the processing flow and streams each stage to the UI.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # optional: add OPENAI_API_KEY and MONGODB_URI
uvicorn app.main:app --reload --port 8000
pytest
```

Without keys it runs with the **mock** model (rule-based) and **in-memory** storage, so the full flow works offline.
`GET /api/health` shows which provider and store are active.

Generated PBIP projects are written to `backend/output/<conversation>/` (git-ignored).

See `../CLAUDE.md` for the flow, the decision formula and the API.
