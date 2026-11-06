# Dashboard request lifecycle: implementation handover

## Delivery and reviewed state

This implementation follows the partner clarification and `Bayer_Challenge_Implementation_Prompt.md`. It was built on main `f3f379a6272cab8120363cc54fd70f45cc842906`, with the compatible workbook/molecular work from PR #2, head `b4a466c351f2e00f62eb52f2cc07b126e8c19255`, integrated into the same update. It preserves the existing React workbench, FastAPI agents, rules and optional MongoDB adapter.

The product now starts from **“What dashboard does your team need?”** The employee requests a deliverable, sees the repository assessment and reviews the proposed path. An agent does not need to prescribe a business intervention to fulfil a dashboard request.

## A real user and product journey

Oliver, a fictional commercial requester from the supplied owner registry, needs monthly sales and shipment reporting for a portfolio review. He knows the purpose and audience but does not build dashboards.

1. **Request.** Oliver enters the requirement or chooses the labelled portfolio demo. The brief shows KPIs, market/product scope, monthly grain, source period, requester and revision. Missing material scope or purpose is clarified. An unsupported requirement remains unresolved.
2. **Check the repository.** The app compares the 360 imported assets. The closest report, AST-0019, has both measures, but its Brazil scope does not satisfy a global request. The employee can see that mismatch rather than receiving another dashboard without explanation.
3. **Investigate.** The intent agent interprets the request. Discovery and governance run deterministic checks. The evidence agent checks known catalogue records. The specification agent chooses from supported layouts. Each actual run shows live-model, offline-rules or fallback mode, with details in the processing record.
4. **Inspect the molecular view.** Oliver opens a candidate and follows its model, KPI and owner relationships. Source controls show the original worksheet row and snapshot. Directed lineage, ID associations and unapproved migration candidates are distinct. Returning to the request preserves the current work.
5. **Review the proposal.** A proposed catalogue model is identified, but its workbook metadata is not executable access. The actual demo generation contract separately identifies the team-built BayerDemo model, synthetic fact columns, units, SUM formulas, ownership and acceptance criteria. Missing executable measures block generation.
6. **Independent review.** Oliver cannot approve his own request. The demonstrator switches to Sofia, the configured reviewer. This is explicitly a synthetic demo role selector, not Bayer SSO. The server records Sofia's stable ID and binds the review to the exact spec and source hashes.
7. **Generate and check.** For supported new builds, the renderer writes a PBIP, enhanced PBIR files and a self-contained synthetic model. It validates schemas, bindings and layout bounds, and produces reference totals and breakdowns. The same specification generates the same substantive artifact hashes.
8. **Deliver the pending artifact.** The package is available through an authorised ZIP download. The catalogue entry remains a draft with validation pending and no endorsement. It is excluded from trusted report reuse. A second equivalent request can discover the existing pending package without creating another copy.
9. **Complete the external handoff.** A teammate opens the project in Power BI, refreshes it, inspects visuals and reconciles results. Real publication requires an authorised destination and evidence. This app does not pretend those steps have happened.
10. **Return later.** SQLite preserves requests, agent traces, specifications, approvals, actions and output metadata. Saved requests restore the current investigation and its download link. Output files require the matching durable volume.

The Brazil version of the same request demonstrates reuse: the repository already has a metadata-compatible asset, so no new package is generated. Live access to that imported asset remains unverified.

## Implementation checklist and evidence

| Requirement | Implemented behavior | Evidence / qualification |
| --- | --- | --- |
| Request-led entry | Dashboard copy, editable full requirement, brief, saved requests | AskPage; browser checked |
| Material clarification | No question-count bypass; unknown IDs retained; unsupported period requests blocked | Intent tests; offline parsing remains deliberately limited |
| Source integrity | Full workbook rows, provenance, exact owner IDs, source scope conflicts | Workbook/graph tests; duplicate Sofia Rossi identities remain separate |
| Deterministic repository assessment | Relevance separated from hard gates; original facts preserved | Decision tests and visible candidate scores |
| Visible agents | Intent/evidence/spec traces, modes and fallback reasons | Scripted-model and offline tests; live API calls not run |
| Safe approval | Server-resolved actor, independent reviewer, spec/source hash checks | Negative permission/stale review tests |
| Safe execution | Required model/owner/spec/binding failures block generation and create a linked task | Finance and repair acceptance cases |
| Honest lifecycle | Plan approval, generation, runtime validation, publication and endorsement are distinct | No trusted status is automatically granted |
| Two real generation paths | Global portfolio and Nubeqa global monthly sales/shipments | `app.validate_demo`; both return actual files |
| Repeatability | Deterministic renderer and exact artifact hashes; repeated review is idempotent | Renderer and API tests |
| Duplicate prevention | Client submission keys replay results; equivalent requests reuse pending output | Tests confirm only two assets after repeats |
| Conflicting edits | Request revision and action version checks under a mutation lock | Stale edit/update tests; single-worker design |
| Durable demo | SQLite default; MongoDB adapter retained; configured DB failure fails startup | SQLite close/reopen test; Mongo tests use a fake database |
| Audit integrity | Append-only application audit events; stable IDs and hashes | History overwrite/update rejection tests |
| Molecular journey | Source graph plus runtime request, action and resulting draft links | Exact lineage tests and browser source-row inspection |
| Target runtime quality | Portable files, expected values and checklist ready | Power BI opening/rendering/numerical reconciliation: **not run** |
| Enterprise deployment | Concrete roles and proposed hosting/access path below | Production SSO, real tenant permissions/publication: **not configured** |

## Why some existing “successes” changed

The earlier approval path could make a repair look executed and a new report look trusted. Approval now records only a plan. Unsupported changes become linked blocked tasks and leave source assets untouched.

The Eylea Japan scenario previously recommended reuse of AST-0079. Its linked model has conflicting product scope. That now requires steward review. Xarelto Mexico's missing/inactive ownership also remains unresolved instead of being silently replaced with the requester.

The graph retains the workbook's full January–October usage period. Decision scores use the original August–October window, labelled as calendar months. Monthly distinct users are not added together and labelled period-unique users.

A catalogue KPI approval record does not provide DAX or executable model fields. The previous skeleton has been replaced by a narrow executable synthetic contract rather than invented live tenant connections.

## Reproducibility package

From `backend/`, with dependencies installed:

```bash
python -m app.validate_demo
```

This uses isolated memory state and explicit offline agents. It writes `backend/output/acceptance/acceptance-results.json`, two generated projects and repeated renderings. It does not mutate the running application's database. The committed `docs/validation-results.json` is a compact observed result, not a claim of runtime Power BI acceptance.

| Case | Expected result |
| --- | --- |
| `demo_portfolio_sales_units` | New build: portfolio scope is broader than the closest Brazil report |
| `demo_nubeqa_sales_units` | New build: no existing in-scope, sufficiently governed report satisfies this pair |
| Repeated unchanged specification | Identical hashes for PBIP/PBIR/model files |
| Repeated equivalent request | Existing pending package; no duplicate generated asset |
| `req_finance_gtn` | Reviewed plan blocked: required financial measures lack executable demo bindings |
| `scn_repair_xarelto_mx` | Reviewed repair blocked: external repair and active ownership are unresolved |
| `demo_reuse_brazil` | Existing metadata match, no generation |

Supported execution: `net_sales`, `units_shipped`; monthly grain; product, market, region and therapeutic-area filters; requested dimensions plus monthly trends. The facts are flattened using exact product/market IDs. `ValueType` retains the workbook's synthetic status. Net sales converts M EUR to EUR by multiplying by 1,000,000. These SUM formulas are **team-defined demo semantics**, not executable definitions supplied or certified by Bayer. Unsupported ratio/variance KPIs are not generated.

The model is identical across self-contained packages for portability. This duplicates the demo model payload on disk; it is not the final enterprise shared-model deployment architecture. The proposed catalogue model is recorded separately from the actual execution model.

The renderer uses cards, tables, bar charts and line charts, at most six visuals, fixed spacing, typography and number formats. It checks official PBIR JSON schemas, resolvable package paths, supported bindings and canvas bounds. The fixed grid prevents overlaps. Schema validation is not proof that Power BI accepts a model or renders a chart correctly.

Format references checked during implementation:
- [Microsoft Power BI report project documentation](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-report)
- [Microsoft semantic model project documentation](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-dataset)
- [Microsoft JSON schemas](https://github.com/microsoft/json-schemas), pinned at `eecc60d35b9ab18b884d35c50abe7d09d2753cdf`; vendored with its license.

## Power BI teammate handoff

1. Run the reproducibility command, or download a reviewed supported package from the app. Keep the folder structure intact.
2. Use Power BI Desktop with support for enhanced PBIR projects. Record the exact installed version in the review.
3. Open the root `.pbip`, refresh the embedded synthetic model and record any import, model, query or visual errors. No Bayer tenant connection is required.
4. Compare both headline KPI values to `validation.json → expected_values → totals`. Compare the market table and each monthly trend point to `breakdowns` in the same file. Test the Nubeqa filter and confirm the larger portfolio dataset is not accidentally displayed.
5. Inspect titles, number formats, period meaning, clipping, empty states, sort order and canvas layout. Check all visuals in both generated requests, not just one polished screenshot.
6. Record pass/fail per layer, screenshot evidence, reviewer ID, timestamp, the source/spec/artifact hashes and any required fix. A failed layer means return to a revised specification or renderer, then regenerate and review the new hashes.
7. Publication remains separate: identify and approve the target tenant/workspace, dataset, audiences, RLS and service permissions, then verify the actual publish result and report URL. No publication or endorsement endpoint is included in this demo.

## Ownership and permissions

The IDs below come from the synthetic registry; their application permissions are explicit **team demo policy**. Their names or source job titles do not themselves grant authority.

| Role | Demo representation | Responsibility |
| --- | --- | --- |
| Requester/business owner | Oliver Martin, `OWN-008` | Describe purpose/scope; assess usefulness; owns the request |
| Report owner for new demos | Laura Fischer, `OWN-039` | Maintain the generated demo report; next review date is recorded |
| Steward/reviewer | Sofia Rossi, `OWN-022` | Review scope/definitions/prerequisites and exact plan version |
| Publisher/platform reviewer | Julia Virtanen, `OWN-026` | Alternate demo reviewer; no actual publishing capability is connected |
| Model and KPI owners | Exact imported `owner_id` | Accountable for source definition and dependency issues |
| Platform operator | Team operating the demo | Storage, secrets, backups, access integration and service operation |

All three selectable actors may read the shared synthetic estate and action queue. Request details, specs, agent records and downloads are limited to the requester or configured reviewers. Reviewers cannot approve a request they submitted themselves. Actions may be changed by their creator, assigned actor or a reviewer. Assigning a task to an active imported owner does not grant that person app sign-in access. Duplicate names are presented with IDs.

`DEMO_MODE=false` fails closed until a production identity adapter is implemented. Demo role switching must not be represented as corporate authentication. Stable signing secrets should come from runtime secret storage; omitting the secret intentionally invalidates sessions on process restart.

## Where the product and assets live

**Demonstrated local deployment:** React/Vite frontend; one FastAPI worker; SQLite snapshot database; local generated-output directory. Browser requests use bearer sessions. Database metadata alone is insufficient for downloads: both database and output files must survive a restart.

**Proposed real deployment:** approved internal frontend and container service behind corporate SSO; organisation-managed database for requests, policy, review and audit; protected object storage for versioned artifact packages; governed Power BI workspaces for runtime-validated reports; shared enterprise semantic models. Apply user-scoped permissions to API reads, agent retrieval, generated artifacts and published reports. A product/market label is not an access grant. Add transactional outbox/jobs and per-object optimistic concurrency before multiple workers.

The existing Docker workflow builds and pushes an image when main changes. Docker Hub is image distribution, not a running deployment. Persist `/app/backend/data` and `/app/backend/output`, or use MongoDB plus durable output storage. Configure exact frontend CORS origins and keep secrets out of code. No new production environment was provisioned by this change.

## Explicit remaining limits

- Power BI Desktop/service runtime was unavailable here. Rendering, numerical acceptance and publication remain pending.
- Live model calls and real MongoDB Atlas were not exercised. The offline path and scripted agent contract were tested.
- Offline intent interpretation is keyword-based. It supports the demonstrated requests, retains recognised unsupported terms and asks for missing scope/purpose; it is not general natural-language understanding. Arbitrary KPI phrasing may need a live model or further clarification.
- Presets are curated request templates with explicit scope; they do not select one of the 150 original request rows. Conflicting free-text/structured contexts in those rows remain visible in Workbook and the graph. A future direct row-to-request import must require explicit reconciliation.
- SQLite writes atomic snapshots, but the entire generation/files/catalogue/audit sequence is not one distributed transaction. One worker and durable volumes are required. A process interruption may leave unreferenced draft files; it must never make them trusted.
- The renderer's semantic model has no Power BI runtime acceptance yet. No HTML preview is used as substitute evidence.

## Validation commands

```bash
python -m pytest backend/tests -q
WORKBENCH_PYTHON=/absolute/path/to/python npm test --prefix frontend
npm run build --prefix frontend
```

Browser checks exercised request submission, disabled requester approval, reviewer role switching, generation, authenticated package download, molecular source-row inspection, page reload and saved-request restoration. These verify the web workbench; they do not verify generated Power BI visuals.
