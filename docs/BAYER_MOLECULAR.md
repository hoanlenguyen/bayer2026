# Bayer workbook and molecular view

This focused MVP helps Bayer internal employees find and assess existing analytics before building more. The molecular representation maps **analytics relationships**. The supplied Pharmaceuticals workbook covers commercial, market access, supply, launch and migration data; it contains no molecular chemistry or R&D assay evidence.

The implementation extends the current investigation workbench and action tracker. Existing agents, decision paths, presets, report generation and action transitions remain intact. The graph reads the same `DATAPACK_PATH` as the pipeline and overlays the live catalogue and saved actions.

## Complete source evidence

`materials/Bayer_Pharmaceuticals_SinceAI_2026_FINAL_Builder_Data_Pack.xlsx` is the core source. All 24 sheets are accessible through Workbook, including the two narrative sheets, with original Excel row numbers, blanks, dates and synthetic-record indicators. `/api/source` exposes the file hash; `/api/source/{sheet}` provides paginated rows (maximum 200 per response) or an exact row. The source layer retains formula and date-cell metadata. Restart after changing the workbook so both cached readers reload together.

The repository's workbook and Divin's uploaded copy contain matching table values. Their XLSX packaging differs; provenance hashes identify the actual file in use. This is synthetic challenge data, not a connection to a Bayer production tenant.

## Relationship semantics

The baseline has **787 entities and 3,969 relationships**, before runtime actions and newly created reports. It includes 360 assets, 75 models, 56 KPI definitions, 60 owners, 16 workspaces, seven products, 14 markets and all 150 business requests, with metric families, domains and source sheets. Large observation tables remain source evidence and aggregates instead of becoming thousands of graph nodes.

| Basis | Meaning |
| --- | --- |
| Supplied lineage | Directed `Lineage_Edges`, preserving all 438 original row references |
| ID join | Ownership, KPI mapping, workspace or declared scope; this alone does not establish dependency impact |
| Candidate | 94 migration suggestions, hidden by default and labelled unapproved |
| Runtime | A new report, changed owner or accepted action from the current application |

KPI definitions connect to their canonical family. Family membership does not prove equivalence. Duplicate owner names remain distinct because edges use owner IDs. Name-only action owners are displayed without inventing an identity match.

Upstream and downstream lenses follow **supplied directed lineage only**. All-relationships mode adds context joins. Search and refocus expose one to three hops; a 90-node rendering cap reports the full reachable count. Source references on nodes and edges open the original Excel row. Relationship evidence can also be selected from the inspector list without clicking a narrow graph edge.

## What the view does and does not establish

Asset governance scores still come from the existing decision engine and are labelled computed. Other nodes show unknown scores rather than invented confidence. Certification means imported endorsement/approval; it is not a new executed validation. Exact data age, effective access and executable model definitions are not established by a visual relationship.

Usage in this view is labelled January–October 2026. Summed views and latest monthly distinct users are separate; summing monthly distinct users is not presented as a distinct audience across the entire period. The existing decision engine retains its own usage window.

The graph proposes review of retirement candidates. It does not retire or migrate an asset. Current investigation decisions and accepted follow-up work continue to use the existing application flows.

## Demo

1. Open Molecular view to inspect Net Sales and its individual KPI variants, owners and reports.
2. Search for AST-0001. Open its source row and the upstream SM-057 lineage evidence.
3. Switch between All relationships, Upstream lineage and Downstream impact. Increase depth or refocus to trace dependencies.
4. Enable Migration candidates to inspect suggested destinations and their source rows.
5. Open Workbook and select any of the 24 sheets. The 3,600 usage records and 150 requests are fully browsable.
6. Return to Investigations. Its ongoing session stays mounted. Accepted actions appear in the existing tracker and on the next graph load.

## Checks

Run `pytest -q` in backend, and `npm run build`, `npm run test:workbench`, and `node --test tests/graph.test.mjs` in frontend. Tests cover full source retention, original lineage direction/provenance, distinct owner identity, candidate semantics, live catalogue updates, action links, pagination, graph cycles and rendering limits. Existing investigation tests cover all current decision paths. Live model, live MongoDB/Fabric and Power BI Desktop acceptance are separate from these offline checks.
