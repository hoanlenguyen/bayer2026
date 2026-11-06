# Backend

FastAPI service that runs the processing flow over the Bayer data pack and streams each stage to the UI.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # optional: OPENAI_API_KEY, MONGODB_URI
uvicorn app.main:app --reload --port 8000
pytest
```

- The catalog is built from `../materials/Bayer_Pharmaceuticals_SinceAI_2026_FINAL_Builder_Data_Pack.xlsx` (override with `DATAPACK_PATH`).
- Without keys it runs with the **mock** model (agents use their rule-based path) and **in-memory** storage.
- With `MONGODB_URI` set, an empty database is seeded on first start. To load or reload explicitly:

```bash
python -m app.load_datapack --reset
```

This writes every sheet to `datapack_<sheet>`, the derived catalog to `catalog_*`, and the presets. Conversations, specs and actions are kept.

Generated PBIP projects are written to `backend/output/<conversation>/` (git-ignored).

See `../CLAUDE.md` for the decision rules and API.
