# Bayer challenge: implementation prompt to finish the product credibly

Use this entire document as an implementation brief for the existing project. It supersedes earlier product descriptions that framed the application primarily as an assistant answering questions about business performance.

Repository: https://github.com/hoanlenguyen/bayer2026  
Context: Since AI / Bayer challenge, partner clarification supplied on 6 November 2026.

## 1. Your assignment

Act as the engineer responsible for bringing the current product into alignment with the clarified challenge. Inspect the latest repository, implement the necessary changes, validate them, and leave a clear handover. Do not stop at a new concept, static mockup, revised copy, or implementation plan.

This is a focused hackathon MVP. Complete a small, convincing, technically honest workflow rather than expanding into every Bayer department or building a complete enterprise platform.

Preserve useful existing work: workbook import, catalogue, intent/evidence/specification agents, deterministic decision logic, research workbench, relationship graph, action tracking, persistence and report generation. Make targeted changes where correctness or this brief requires them. Coordinate with the current branch state and preserve teammates' changes.

Before editing:
- Read the applicable project instructions and current documentation.
- Inspect the latest branch, working changes, recent commits and relevant pull requests. Record the reviewed commit.
- Recheck the findings below; they describe an earlier inspection and may already have changed.
- Create a short requirement-to-code checklist. Use it to implement and verify the work, not as a substitute for implementation.
- Resolve routine choices yourself. If a dependency is unavailable, continue independent work and report the specific remaining handoff.

## 2. What the challenge partners actually want

Their latest clarification emphasises three things:

1. The BI problem is broader than manufacturing. Business demand exceeds available builders; work is slow and error-prone; the resulting assets are hard to manage.
2. A credible solution explains its real-world lifecycle: where the application and generated assets live, how people access them, how access is governed, who owns them, and what those responsibilities mean.
3. Attractive examples alone are insufficient. Demonstrate how the pipeline reliably produces artifacts of consistent quality across multiple requests.

Translate these points into working behavior and visible evidence. The polished appearance of our application is separate from the quality of dashboards it generates.

The wider challenge permits multiple departments and divisions. Our MVP should remain grounded in the supplied Pharmaceuticals workbook. Do not invent R&D, patient, manufacturing or other departmental records to make the demonstration broader.

## 3. Product definition that must remain consistent

The product is an internal workspace for requesting and managing dashboards.

An employee requests a dashboard or a change to one. The system clarifies the request, checks the existing repository, evaluates coverage and governance, explains whether to reuse or change existing analytics or build something new, prepares the necessary proposal, and tracks the approved work and resulting asset.

Primary employee:
- Needs analytics for their team.
- Can describe the business purpose and information required.
- Does not need to design dashboards or understand data models.

Supporting users:
- Report owner or BI developer.
- KPI/data steward and model owner.
- Reviewer/publisher and platform administrator.

Example request:
"Build a dashboard showing Eylea net sales and digital engagement in Japan, with monthly trends."

The objective is to assess and fulfil that dashboard request. Do not redirect the main experience into answering "How are sales doing?" or automatically prescribing business interventions.

Keep business-purpose questions as requirement clarification: who will use this, what decision it supports, and what it must show.

## 4. Existing implementation: inspect before changing

Relevant paths observed during the previous review:
- backend/app/datapack.py
- backend/app/decision.py
- backend/app/agents/intent.py
- backend/app/agents/evidence.py
- backend/app/agents/spec.py
- backend/app/pipeline.py
- backend/app/pbip.py
- backend/app/main.py
- backend/app/actions.py
- backend/app/graph.py
- backend/app/store.py
- frontend/src/pages/AskPage.tsx
- frontend/src/components/ask/Workbench.tsx
- frontend/src/pages/ActionsPage.tsx

Previously observed findings to confirm:
- The opening UI is still framed around asking questions rather than requesting dashboards.
- pbip.py describes the output as an unvalidated skeleton.
- The specification validator can report a missing model capability without treating it as an execution blocker.
- The approval path can proceed despite failed validation and register new assets as promoted/certified.
- Approval attribution comes from a client-supplied name.
- Repairs can mark catalogue health as resolved without a real external repair.
- New ownership can be a display string such as "You (requester)" without a stable owner ID.
- Live model calls, actual Atlas storage and Power BI Desktop acceptance were documented as unverified.
- The richer workbook-backed molecular view was in draft PR #2 on branch codex/bayer-workbook-molecular:
  https://github.com/hoanlenguyen/bayer2026/pull/2

Do not duplicate or overwrite improvements already merged. Inspect and integrate relevant pending work through the team's normal workflow. Do not claim a draft PR is part of main.

## 5. Priorities and scope control

P0: Correct the approval, validation and catalogue lifecycle so incomplete work cannot look trusted or finished.

P0: Prove a narrow, usable report-generation path with explicit field bindings and repeatable quality checks.

P1: Connect the dashboard request, evidence, molecular view, review, actions and resulting asset.

P1: Make identity, ownership, persistence and the deployment path concrete.

P2: Improve labels, visual polish and demonstration materials after the critical workflow works.

Do not spend the remaining time on unrelated modules, a general-purpose agent platform, a new technology stack, or supporting every possible visual and KPI.

## 6. Required user journey

### A. Submit and clarify a request

Opening:
"What dashboard does your team need?"

Supporting copy:
"Describe what you need to track. We will check existing dashboards and prepare any necessary changes."

Support requests for a new dashboard and requests to change an identified asset. Existing presets may be reframed as dashboard requests while preserving their intended filters and measures.

Create an editable request brief containing:
- Purpose and audience.
- Requested KPIs and comparisons.
- Product, market and other scope.
- Reporting period, granularity and required breakdowns.
- Existing source asset, if this is a change or migration.
- Requester and requirement version.
- Missing or conflicting information.

Ask only about material gaps. A question-count limit must not discard unresolved requirements. Unsupported terms must be retained as unresolved rather than silently removed and presented as satisfied.

### B. Assess existing assets

Use the imported repository to compare existing dashboards, reports, semantic models and KPIs.

For each candidate, show:
- Requirements covered.
- Requirements missing.
- Scope compatibility.
- Governance blockers.
- Ownership and refresh information.
- Relevant usage and dependencies.
- Supporting source records.

Separate relevance from eligibility for reuse. A similar report with a conflicting definition or unknown access is not automatically usable.

Keep deterministic checks and decision rules. Document team-defined thresholds as team policy, not rules explicitly supplied by Bayer.

### C. Make the investigation visible

Display meaningful stages from actual backend events: interpret request, discover candidates, compare requirements, check governance, collect evidence, prepare proposal.

Use the existing agents where applicable:
- Intent agent: request interpretation and clarification.
- Evidence agent: investigation of known records and dependencies.
- Specification agent: preparation of the supported change/report specification.

Explain that discovery, governance, decision rules and validation also use deterministic code. Do not label every function as an autonomous agent.

Distinguish live model execution, offline rules and fallback. Capture the mode and reason for fallback in the run record. Use concise user-facing status and expandable technical detail.

### D. Explain the recommendation

Use supported outcomes: reuse, repair, consolidate, migrate, new build, clarification/review, or unsupported request.

If extension/adaptation is exposed as a separate outcome, define its behavior and acceptance criteria. Do not add a label that maps ambiguously to an existing branch.

New builds must include evidence of the unmet need. Reuse must not generate a duplicate. Migration and retirement require an identified source, dependencies, usage and ownership review; candidate labels are not approvals.

### E. Review and follow through

Show the request, alternatives, chosen plan, affected assets, owner, reviewer, dependencies, evidence and acceptance criteria together.

Create linked actions for unresolved prerequisites and approved work. A dashboard request should not automatically create a business action that assumes a KPI must increase or decrease.

Use one connected set of IDs across request, recommendation, specification, review, artifact, catalogue entry and actions.

## 7. Repair the approval and execution lifecycle

Use explicit state transitions. Separate dimensions where appropriate rather than forcing every event into one status field.

Suggested distinctions:
- Request: draft, clarifying, assessed, awaiting review, in progress, completed, blocked or cancelled.
- Specification: draft, reviewed/approved, rejected, superseded.
- Artifact: generated, validation pending, validation failed, validated, published, retired.
- Action: open, in progress, blocked, done, verified or dismissed.
- Endorsement: separate from artifact generation and validation.

Requirements:
- Approval authorises a defined plan. It does not prove execution or validation.
- Bind approval to the exact specification version/hash and relevant source/model version.
- Relevant changes invalidate stale approval; generation and execution must recheck prerequisites.
- Reject invalid transitions and conflicting concurrent updates.
- Make duplicate submissions, retries and repeated approvals idempotent.
- A failed required check or missing measure binding blocks execution/publication, while a remediation plan can still be reviewed.
- Register draft artifacts if useful, but exclude them from trusted reuse and clearly display their state.
- Promotion/certification requires the separately defined authorised review; do not set it automatically on approval.
- Do not claim publication without a verified destination and successful publication result.
- A repair requires execution evidence and a follow-up check before being marked resolved.
- When external execution is unavailable, record an explicit demo simulation or pending external task. Do not silently overwrite imported health facts.
- No report should become reusable merely because an earlier request created a catalogue entry.

Record attributable audit events with actor ID, object ID, version, previous/new state, timestamp, evidence and reason. Prevent ordinary application updates from rewriting event history.

## 8. Demonstrate repeatable artifact generation

This is a central delivery requirement.

### A. Establish a supported execution contract

Inspect the workbook's actual contents. Catalogue metadata, model table counts and KPI approval labels do not supply executable schemas or formulas.

For each supported generated measure and visual, resolve:
- Actual table/field/measure identity.
- Units, aggregation and formatting.
- Time/date meaning and supported grain.
- Required relationships and filters.
- Model target and connection details.
- Evidence supporting the mapping.

Do not invent DAX, connection IDs, model fields or conversions and claim they came from Bayer.

Choose a narrow supported subset. Where real model access is unavailable, build an explicitly documented synthetic demo model from available workbook facts, with reviewed demo definitions and mappings. Keep it distinct from Bayer-provided approved definitions and from any actual Bayer service.

A fixture must not artificially change the repository to force a new-build recommendation. Preserve existing source facts and explain why the assessed request has an unmet need.

If no executable model can be established, produce a blocked specification and precise prerequisites. That is an honest partial result, not completion of the generated-dashboard requirement.

### B. Use a controlled visual system

Define a small set of reusable layouts for the supported requests:
- Consistent typography, spacing, colours and number formatting.
- A limited supported set of cards, trends, breakdowns and tables.
- Layout bounds and overlap checks.
- Appropriate units, titles, legends and period labels.
- Clear empty, missing-data and error states.
- No chart that implies a comparison or granularity the data cannot support.

The agent may choose among supported components and layouts. The renderer must validate its choices. Verify the current official Power BI format documentation before repairing generation; do not assume plausible JSON is sufficient.

### C. Validate at separate layers

1. Specification: required fields, scope, coverage, owners and model support.
2. Artifact structure: required files, accepted schemas and resolvable references.
3. Data binding: fields, measures, relationships, filters and units.
4. Numerical correctness: selected rendered results reconcile to independently calculated expected values from the demo source.
5. Rendering: open the output in the target runtime; inspect actual visuals, labels, clipping and empty/error states.
6. Publication: verify the configured destination and permissions before recording published status.

Record pass, fail or not run for each layer, with evidence. Valid JSON, a screenshot of our web app, or successful unit tests are not proof of Power BI acceptance.

If Power BI Desktop or an appropriate service runtime is unavailable, complete the automated checks and prepare a reproducible validation package for the teammate with access. Include exact artifacts, prerequisites and expected checks. Mark target-runtime acceptance as pending; never substitute a custom HTML preview for that proof.

### D. Prove consistency

Select at least two distinct, evidence-justified requests that exercise actual generation, using executable demo bindings. Run them through the same pipeline and validation standard.

Repeat at least one unchanged request/specification:
- The same specification should produce equivalent substantive artifacts.
- Equivalent requests should consistently meet the same quality criteria; LLM wording need not be byte-identical.
- Separate volatile timestamps from deterministic artifact comparisons.
- A repeated approved request should find the existing eligible output rather than create another report.
- Modify a requirement or source dependency and demonstrate reassessment.

Record model mode, source version, specification version, renderer/template version, artifact hashes and validation results. Include one request deliberately blocked by a missing binding or other material prerequisite.

## 9. Establish meaningful identity and ownership

Use stable owner/actor IDs. Names may repeat; titles do not grant universal authority.

Separate:
- Requester: submits and clarifies needs.
- Business owner: accountable for usefulness and business acceptance.
- Report owner: accountable for report maintenance, changes, review and retirement.
- Model/KPI owner or steward: accountable for definitions, data quality and shared dependencies.
- Reviewer/publisher: authorised to approve specified changes and/or publish to specified destinations.
- Platform operator: accountable for application operation and access administration.

A single person may hold multiple roles under an explicit policy. Do not assume every requester becomes the report owner or may approve every asset.

Implement a coherent demo identity and permission policy:
- Resolve mutation actors server-side.
- Reject a client merely supplying another person's name, ID or role as authority.
- If production SSO is unavailable, use a clearly labelled, server-configured demo authentication/session mechanism.
- Any demo actor selector must be restricted to explicit demo mode and mapped server-side to configured actors and permissions.
- Document production authentication and authorisation as a separate integration; do not imply demo selection is Bayer sign-in.
- Check permission for requests, evidence, source metadata, approvals, artifact downloads and actions where applicable.
- Model/API/agent retrieval must respect the same scope; hiding a UI control is insufficient.

Use exact imported ownership IDs where established. Inactive or missing ownership must produce a resolution task, not an invented interim owner that immediately passes governance.

For new assets, record accountable owners, acceptance, review date, destination, classification and access policy. Geographic scope and classification metadata alone are not access grants.

## 10. Make the molecular view operational

Inspect PR #2 and integrate compatible improvements without breaking current functionality.

Use workbook-backed entities and relationships, preserve source IDs, and provide evidence links to sheet/row/record/field and snapshot where available. Do not invent missing provenance.

Distinguish:
- Supplied directional lineage.
- Derived joins/context.
- KPI family membership and definition conflict.
- Unapproved migration candidates.
- Runtime requests, assets and accepted actions.

A family relationship does not establish KPI equivalence. A proposed migration edge does not establish an executed dependency.

Start with the selected candidate and a small relevant neighbourhood. Offer upstream/downstream inspection with cycle protection. Show scope and filter limits so an omitted edge is not interpreted as proof of no dependency.

Support this journey:
request -> candidate -> model/KPI/owner -> evidence -> proposal -> action -> resulting asset.

Keep the investigation active while navigating. Make the graph useful for explaining overlap, blockers and the impact of change; it must not be a decorative network animation.

## 11. Data integrity and persistence

Treat the workbook as a dated synthetic source. Preserve original facts and store interpretations, simulations and runtime changes separately.

Verify:
- Import counts and joins against the actual workbook.
- Owner identity by ID, including duplicate names and inactive owners.
- Request text versus structured fields; conflicts require clarification.
- KPI units and definitions before combining measures.
- Asset/model scope compatibility.
- Usage period labels; do not add monthly unique-user counts and call them unique users across the period.
- Refresh status versus exact freshness; last-modified is not last-refresh.
- Governance and migration candidate flags as inputs for review, not ground-truth decisions.
- Explicit unknown states for unestablished access, definitions and dependencies.

Persist requests, revisions, evidence, approvals, artifact metadata, actions and audit history using the existing supported store where practical. Verify persistence across a restart. If running in memory, expose that limitation clearly.

Use unique versioned artifact identities. Avoid overwriting unrelated reports because their display names produce the same slug.

## 12. Explain and implement the deployment path proportionately

Provide a concrete proposed architecture without claiming unbuilt integrations.

Answer:
- Where does the frontend run?
- Where do the API, agents and report generator run?
- Where are secrets held?
- Where do catalogue metadata, requests, evidence and audit history persist?
- Where are generated source files and report versions stored?
- Where do users access published BI assets?
- Which identity, application permissions and BI/model permissions apply?
- Who can approve, publish, change access, transfer ownership and retire assets?
- How are refresh failures, owner departure and rollback handled?

Reuse existing container and configuration work where suitable. Container-image packaging alone is not a running deployment.

Implement and demonstrate the available local/demo deployment. Document the production mapping to Bayer-approved hosting, identity, storage and BI services. Do not create or claim real tenant access, publish to production or alter external permissions without the relevant established authorisation.

Separate evidence for "implemented locally", "tested in deployed demo" and "proposed for production".

## 13. Acceptance scenarios and required evidence

Select exact records after checking the current workbook and catalogue. The following scenarios guide testing; do not force outcomes that the evidence does not support.

| Scenario | Required result | Evidence |
| --- | --- | --- |
| Eylea Japan reuse request | Correct existing asset is assessed; no duplicate is built | Requirement comparison, governance checks, selected ID and catalogue count |
| Existing repair scenario, such as Canada refresh | Repair plan is traceable; unresolved execution stays pending | Source defect, owner, action and verification state |
| Two distinct supported new-build cases | Both use the same controlled generation pipeline and quality checks | Specifications, bindings, output files and validation results |
| Missing model measure or unknown binding | Execution/publication blocked; remediation recorded | Failed check and unchanged trusted catalogue |
| Repeated request | Reuse or explicit reassessment rather than duplicate generation | Stable request/asset linkage and idempotency result |
| Modified approved specification or relevant source | Old approval rejected as stale | Version/hash mismatch and audit event |
| Actor without required permission | Mutation rejected server-side | Negative API test and unchanged object |
| Duplicate owner names or inactive owner | Correct identity resolution or ownership task | Stable IDs and permission result |
| Graph explanation | Selected candidate's source evidence and dependencies can be inspected | Resolved source links and traversal checks |
| Restart | Persisted request, review, artifact state and action remain consistent | Before/after IDs and states |

Use meaningful tests for these requirements. Preserve and run the relevant existing backend, frontend build and workbench checks. Fix tests that incorrectly assumed approval equals certification; explain why those expectations changed.

Run actual free-text requests as well as presets. A preset-only demonstration does not validate the intent agent. If live AI is available, exercise and record it; if unavailable, explicitly demonstrate offline mode without claiming live-agent validation.

## 14. Definition of done and honest partial completion

The core demo is complete only when:
- Dashboard requests are the unmistakable primary entry point.
- Existing assets are assessed with evidence before a build is proposed.
- Unknowns and blockers cannot be bypassed into trusted outputs.
- Reviewers and owners have explicit identities and responsibilities.
- The molecular view explains actual relevant relationships.
- At least two justified generated reports pass the defined available validation layers.
- Target-runtime acceptance is evidenced before a report is described as usable in that runtime.
- Actions, approvals and catalogue state remain coherent.
- The deployment/ownership story names concrete components and responsibilities.
- The final demonstration distinguishes real operations, simulations and pending integrations.

If an external dependency prevents a criterion, mark that criterion incomplete. Deliver all independent work and the smallest specific handoff needed to finish it. Do not relabel missing Power BI validation, SSO or live connectors as completed.

## 15. Required final handover

Return:
1. Implemented changes, grouped by the requirements they satisfy.
2. Branch/commit and review link or reviewable diff through the existing team workflow.
3. A concise acceptance matrix: passed, failed, not run, with evidence locations.
4. Reproducible setup and validation commands.
5. Generated artifacts, specifications, mappings and validation manifests.
6. A short deployment and responsibility document distinguishing demo from production.
7. A five-minute demo script: request, repository check, evidence/graph, justified decision, controlled generation, validation and ownership.
8. Remaining blockers, their impact and the exact next action for each.

Update stale project documentation to match the implemented behavior. Do not claim that unmerged work, expected test results, simulated repairs or unvalidated artifacts are live capabilities.

Begin by inspecting the current repository, then implement the highest-priority corrections. Keep the work focused on a convincing demonstration that Bayer can assess, govern and repeatedly fulfil dashboard requests.

