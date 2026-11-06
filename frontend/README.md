# Frontend

React + TypeScript + Vite app. Pages: **Investigations** (`#ask`, a research workbench) and **Asset index** (`#explorer`, entity details and relationship graph). In development, `/api` is proxied to the backend on port 8000.

## Run

```bash
npm install
npm run dev        # http://localhost:5173
npm run build      # type-check and production build into dist/
```

Start the backend first (see `../backend/README.md`). Open `http://localhost:5173/#explorer-graph` to land on the graph.

## Structure

| Path | Purpose |
|---|---|
| `src/data/types.ts` | Entity, edge and status types |
| `src/data/estate.ts` | Fictional sample estate and display vocabularies (replace with catalog API data) |
| `src/lib/estate.ts` | Pure helpers: lookups, owner, grouped relationships, graph neighbourhood |
| `src/components/GraphCanvas.tsx` | d3-force graph. React owns props; d3 owns the SVG (layout, zoom, drag, highlight) |
| `src/components/GraphTab.tsx` | Filters panel, graph canvas and inspector |
| `src/components/DetailsTab.tsx` | Summary, properties, relationships, governance, flags, provenance |
| `src/components/EntityHeader.tsx`, `TopBar.tsx`, `ui.tsx` | Header, search and shared UI pieces |
| `src/styles.css` | Design tokens (light and dark) and component styles |

## Graph interactions

Click a node to inspect it, double-click (or press Enter) to make it the focus, drag to rearrange, scroll to zoom. Depth and entity-type filters are in the left panel.

## Research workbench

The investigation aligns backend catalog matches with the requested measures, dimensions and time grain. The left index selects an analysis; the centre compares its coverage; the right inspector shows governance checks, evidence, specification and the engine's decision. Inspecting an alternative never changes the backend recommendation. The decision dock preserves explicit approval/rejection, and the expandable processing record retains every stage and generated-file preview.

The workbench is a presentation layer over the existing SSE events. API clients, backend scoring, thresholds, agents, persistence and PBIP generation are unchanged. Investigations remain mounted when the asset index opens, preserving the active session. The existing department presets and fictional-data labels are retained; assay content from the design mockup is not inserted into the catalog.

`src/components/ask/Workbench.tsx` renders the comparison and inspector; `src/workbench.css` provides the visual layer, responsive layouts, dark mode and reduced-motion support.

### Verification

After installing the backend dependencies in `backend/.venv`, run `npm run test:workbench`. Set `WORKBENCH_PYTHON` to an alternative Python executable if needed. The test captures real offline backend SSE events and renders the workbench at each stage across all department presets, approval output and all four decision paths. It also verifies that partial governance events do not replace complete discovery candidates. These rendering checks complement the backend pytest suite; they do not exercise a live OpenAI key or Atlas database.
