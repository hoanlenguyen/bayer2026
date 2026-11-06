# Curator Estate Explorer (mock)

Single-file prototype of an entity page with two tabs:

- **Details**: summary, properties, grouped relationships, governance, AI review flags, provenance.
- **Graph**: force-directed relationship graph (d3 v7) with depth and entity-type filters, inspector panel, zoom, drag. Click a node to inspect it, double-click to make it the focus.

All data is fictional sample data defined at the top of the script (`ENTITIES`, `EDGES`).

## Run

Open `index.html` directly in Chrome. It loads d3 and fonts from public CDNs, so an internet connection is needed.

The URL hash selects the tab: `index.html#details` or `index.html#graph`.
