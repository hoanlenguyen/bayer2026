# Frontend

React + TypeScript + Vite app. Pages: **Ask** (`#ask`, chat with a live processing-flow panel) and **Estate Explorer** (`#explorer`, entity details and relationship graph). In development, `/api` is proxied to the backend on port 8000.

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
