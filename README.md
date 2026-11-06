# Agentic Analytics Manager

An internal dashboard request workbench for the Bayer × Since AI challenge. An employee describes what their team needs. The application checks the existing repository, explains what can be reused or changed, prepares a specification, and records the review and follow-up work.

The MVP uses the supplied **synthetic Pharmaceuticals workbook**. It combines intent, evidence and specification agents with deterministic discovery, governance, lifecycle decisions and validation. The molecular view exposes reports, models, KPI definitions, owners, lineage and original source rows.

## What works

- Dashboard request, clarification, editable requirements, reassessment and saved request recovery.
- Evidence-backed reuse, repair, consolidation, migration and new-build proposals. Conflicting source scope needs steward review.
- Signed **demo sessions**, stable owner IDs, a separate reviewer, version-bound approval and immutable audit events.
- Two generated Power BI demo packages: portfolio sales/shipments and Nubeqa sales/shipments. Both have explicit synthetic data bindings, controlled layouts, offline Microsoft-schema checks, reference totals and authenticated downloads.
- Persistent local SQLite storage, with the existing optional MongoDB adapter.

**Generated does not mean validated or published.** Power BI runtime rendering, numerical acceptance, production SSO and tenant publication are pending external integrations. Repairs are tracked as pending work; imported refresh and ownership facts are not rewritten by approval. Offline agent execution is labelled in the interface.

## Run locally

From the repository root:

```bash
python -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
npm ci --prefix frontend
npm run dev
```

The root script starts FastAPI on 8013 and Vite on its printed URL. For Windows or separate server startup, see [backend setup](backend/README.md) and [frontend setup](frontend/README.md). Runtime keys belong in ignored `backend/.env` or the host's secret store.

## Demo and validation

Use **Oliver Martin / requester** to select **Commercial demo → Portfolio sales and shipments**. Inspect coverage, evidence and specification. Switch to **Sofia Rossi / reviewer**, approve the plan, and download the validation package. It remains a draft excluded from trusted reuse. Repeat with **Nubeqa sales and shipments**.

Use **Reuse Brazil portfolio reporting** to show an existing match with no generated copy. Use **Finance dashboard** to show an approved plan blocked by missing executable bindings. Use **Review Eylea Japan scope conflict** to show why similar metadata is insufficient for reuse.

```bash
.venv/bin/python -m pytest backend/tests -q
WORKBENCH_PYTHON="$PWD/.venv/bin/python" npm test --prefix frontend
npm run build --prefix frontend
cd backend
../.venv/bin/python -m app.validate_demo
```

The last command writes two portable demo projects, repeats their generation and writes `output/acceptance/acceptance-results.json`. The packages include exact expected card and monthly/market values for a teammate to verify in Power BI Desktop. [Observed automated results](docs/validation-results.json).

## Team references

- [Implementation handover, product journey and deployment](docs/IMPLEMENTATION_HANDOVER.md)
- [Molecular view and workbook provenance](docs/BAYER_MOLECULAR.md)
- [Implementation brief and acceptance requirements](docs/Bayer_Challenge_Implementation_Prompt.md)
- [Engineering context and invariants](CLAUDE.md)
- [Power BI schema attribution](backend/app/schemas/README.md)

The workbench is a hackathon demo, not a Bayer production service. All imported numeric values and people/ownership records are challenge fixtures.
