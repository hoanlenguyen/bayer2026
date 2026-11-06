# Curator: An AI Steward for Governed Analytics

> Bayer Hackathon 2026: "Build Less, Build Better: AI for Governed Analytics"

## 1. Problem Framing

Generative AI has reduced the marginal cost of producing a dashboard to near zero. The organisational cost of owning one has not changed. Each new analytics product introduces a metric definition to reconcile, an owner to track, a data pipeline to maintain and a source of potential contradiction in executive decisions. Large enterprises consequently accumulate an "analytics estate" characterised by:

| Symptom | Consequence |
|---|---|
| Overlapping dashboards answering the same question | Wasted build and maintenance effort |
| The same KPI name computed with different logic | Conflicting numbers in decision forums |
| Assets with departed or unknown owners | No accountability, silent decay |
| Low-usage assets that are never retired | Rising run cost and search noise |

**Thesis.** The highest-value intervention point is *before* an asset is created. An AI system should act as a gatekeeper and steward that answers "does this need to exist?" before it answers "how do I build it?".

## 2. Concept

**Curator** is an agentic "front door" for business intelligence. A user brings a business question, not a build request. Curator then:

1. **Understands** the question as a structured analytical intent (metric, dimensions, grain, filters, time window, audience, decision supported).
2. **Discovers** what already exists across dashboards, reports, semantic models, datasets and certified metric definitions.
3. **Recommends** one of four outcomes with transparent evidence: **Answer**, **Reuse**, **Extend** or **Build**.
4. **Builds governed** only when justified, exclusively from certified metrics, and attaches an *Analytics Product Passport* (owner, purpose, lineage, consumers, review date).
5. **Stewards the lifecycle** continuously: detects duplicates, metric conflicts, orphaned assets and decay, and proposes consolidation or retirement for human approval.

### Decision ladder (cheapest outcome first)

```
 Question
   |
   v
 [ANSWER]  An existing certified asset already answers it -> return the number + link
   |  no
   v
 [REUSE]   An existing asset covers >= 80% of the intent -> point to it, show the gap
   |  no
   v
 [EXTEND]  A certified asset can be extended (add a dimension/filter) -> propose change to its owner
   |  no
   v
 [BUILD]   Genuinely new need -> generate from certified semantic layer, with passport + TTL
```

The ladder is the core product idea: AI is used to *prevent* clutter by default and to *generate* only as the last resort.

## 3. Key Features

| # | Feature | What it does | Why judges should care |
|---|---|---|---|
| F1 | Intent Parser | Converts natural language into a typed intent object; asks clarifying questions when ambiguous (e.g. "sales" = gross or net?) | Understands the business question |
| F2 | Estate Search | Hybrid retrieval over asset metadata: semantic embeddings + metric/dimension graph + usage and trust signals; permission-aware | Enterprise search + metadata intelligence |
| F3 | Reuse Score and Coverage Matrix | Scores each candidate and shows, per requested metric and dimension, whether it is covered | Meaningful, explainable reuse |
| F4 | Metric Conflict Radar | Finds KPIs with the same name and different logic (or different names and the same logic) by comparing normalised formulas | Consistency |
| F5 | Governed Builder | Generates new views only from certified metrics; runs policy checks; attaches passport | Trustworthy, maintainable creation |
| F6 | Analytics Product Passport | Owner, purpose, decision supported, certified metrics, lineage, consumers, review/expiry date | Accountability |
| F7 | Estate Health and Sunset Queue | Clusters duplicates, flags orphans and decay, proposes retire/merge actions | Lifecycle thinking |
| F8 | Human-in-the-loop Gates and Audit Trail | Every Extend/Build/Retire/Certify action requires a named human approval; every AI recommendation stores its evidence | Transparent oversight |

## 4. Scoring Model (explainable, not a black box)

For a user intent *q* and candidate asset *a*:

```
ReuseScore(q, a) = 0.30 * SemanticSim(q, a)        # embedding similarity of question vs asset purpose/description
                 + 0.30 * MetricCoverage(q, a)     # share of requested canonical metrics present (by metric ID, not name)
                 + 0.15 * DimensionCoverage(q, a)  # share of requested dimensions/filters/grain supported
                 + 0.15 * Trust(a)                 # certified, fresh data, active owner, passing tests
                 + 0.10 * Adoption(a)              # normalised recent usage
```

- Thresholds: `>= 0.80` Reuse, `0.55 to 0.80` Extend, `< 0.55` Build (tunable; shown to the user).
- Each component is displayed in the UI so a reviewer can see *why* an asset was recommended.
- **Metric equivalence** (F4): parse SQL/DAX expressions into a normalised form (aggregation, base column, filters, exclusions), compare deterministically, then use an LLM judge only for residual ambiguity, with its rationale logged.

## 5. Architecture

```
                 +-------------------------------------------------------------+
  User (Web /    |                       Curator Orchestrator                  |
  Teams bot) --->|  Intent Agent -> Discovery Agent -> Reuse Advisor ---------+ |
                 |                          |                    |            | |
                 |                 Metric Reconciliation     Governed Builder | |
                 |                          |                    |            | |
                 |                  Policy / Governance Agent <--+            | |
                 |                          |                                 | |
                 |               Human Approval Gate + Audit Log <------------+ |
                 +-----------------------------|-------------------------------+
                                               |
          +--------------------+---------------+---------------+-------------------+
          |                    |                               |                   |
   Metadata Catalog      Semantic Layer                 Usage Telemetry     Lineage Graph
   (assets, owners,      (certified metrics as         (views, users,       (source -> model
    descriptions)         code, YAML)                    last access)         -> report)
          |
   Connectors (MCP): Power BI / Tableau, dbt, data catalog (e.g. Purview, Collibra), warehouse
```

Background job: **Estate Janitor** runs nightly over the full catalog to populate F4 and F7.

### Suggested hackathon stack

| Layer | Choice | Rationale |
|---|---|---|
| LLM | Claude (`claude-sonnet-5-5` for agents, `claude-opus-5-5` for metric reconciliation and build planning) | Strong tool use and reasoning; cite evidence |
| Agent framework | Claude Agent SDK or LangGraph | Explicit state machine maps to the decision ladder |
| Backend | Python + FastAPI | Fast iteration |
| Search | Postgres + pgvector (or DuckDB + embeddings) with BM25 hybrid | Hybrid lexical/semantic retrieval |
| Graph | NetworkX (demo) / Neo4j (stretch) | Lineage and metric relationships |
| Semantic layer | dbt-style metric YAML | "Metrics as code", certifiable and diffable |
| Frontend | React + TypeScript + Vite, d3 for the graph | Simple SPA next to a Python API; d3-force for the estate graph |
| Connectors | MCP servers wrapping catalog/BI APIs | Shows a realistic enterprise integration path |

### Demo data

A synthetic but realistic estate for a fictional life-science company (Crop Science, Pharma, Consumer Health):
- ~300 dashboards/reports with titles, descriptions, owners, measures (DAX/SQL), data sources, view counts.
- ~40 metric definitions with *deliberately planted* conflicts (e.g. 6 variants of "Net Sales", 3 of "Market Share").
- Seeded duplicates (near-identical regional sales dashboards), orphans (owner left), and stale assets (no views in 180 days).

Generate it with a script so the dataset is reproducible and the "ground truth" is known, which also lets you report precision/recall for duplicate and conflict detection.

## 6. UX Design

Visual tone: calm, enterprise, evidence-first. Neutral palette with a single accent; status colours used only for coverage and health. Every AI statement is paired with a source chip that links to the underlying asset or definition.

### Screen 1: Ask (the front door)

```
+------------------------------------------------------------------------------------+
| Curator                                              Estate | Conflicts | Approvals |
+-------------------------------+----------------------------------------------------+
| You: Quarterly net sales of   |  Intent                                            |
| fungicides by region vs LY    |  Metric: Net Sales [certified: NS_v3]  Grain: Qtr  |
|                               |  Dims: Region, Product Group  Filter: Fungicides   |
| Curator: By "net sales" do    |  Compare: Prior year                               |
| you mean after rebates        |----------------------------------------------------|
| (certified NS_v3)? [Yes] [No] |  Recommendation:  EXTEND   (confidence 0.74)       |
|                               |                                                    |
| Curator: 4 assets found.      |  1. Crop Commercial Cockpit   Score 0.78  CERTIFIED|
| One certified asset covers    |     Net Sales  [x]  Region [x]  Product Grp [x]    |
| 3 of 4 needs. Missing: prior- |     Prior-year compare [ ]   Owner: A. Weber       |
| year comparison.              |     [Open] [Request extension]                     |
|                               |  2. EMEA Sales Q-Report       Score 0.61  !CONFLICT|
| [Ask follow-up...]            |     Uses gross sales labelled "Net Sales"          |
|                               |  3. Fungicide Deep Dive       Score 0.52  STALE    |
|                               |     No views in 210 days, owner inactive           |
|                               |  Score breakdown v                                 |
+-------------------------------+----------------------------------------------------+
```

Design notes:
- The **Coverage Matrix** (checkbox row) is the signature interaction: users instantly see the gap.
- The primary call to action changes with the decision (Open / Request extension / Start governed build). "Build new" is always available but placed last and requires a justification field.
- Warnings (CONFLICT, STALE) educate users about estate quality during normal work.

### Screen 2: Estate Health (for data/BI leaders)

```
+------------------------------------------------------------------------------------+
|  312 assets | 38% certified | 41 duplicate clusters | 27 orphaned | 9 KPI conflicts|
+---------------------------------------------+--------------------------------------+
|  Duplicate cluster map (bubbles = clusters, |  Sunset queue                        |
|  size = #assets, colour = trust)            |  [ ] Fungicide Deep Dive   0 views   |
|                                             |  [ ] EMEA Sales v2 (copy)  dup of #12|
|        (o)   (O)      (o)                   |  [ ] Old Pricing Monitor   orphan    |
|     (O)    (o)   (OO)                       |  Est. saving: 140 maintenance h/yr   |
|                                             |  [Send to owners for approval]       |
+---------------------------------------------+--------------------------------------+
|  Trend: assets created vs retired, reuse rate per month                            |
+------------------------------------------------------------------------------------+
```

### Screen 3: Metric Conflict Resolver (for data stewards)

```
  "Net Sales": 6 definitions across 47 assets
  +-----------+----------------------+-----------+-----------+----------+
  | Variant   | Logic (normalised)   | Rebates   | Returns   | Assets   |
  | NS_v3 *   | SUM(inv) - reb - ret | deducted  | deducted  | 21       |
  | NS_emea   | SUM(inv)             | no        | no        | 9        |
  | ...                                                                 |
  +---------------------------------------------------------------------+
  AI rationale: NS_emea omits rebates; it is gross sales mislabelled.
  [Approve NS_v3 as canonical] [Rename NS_emea -> Gross Sales] [Notify 9 owners]
```

### Screen 4: Analytics Product Passport

A one-page card attached to every asset: purpose, decision supported, owner and backup owner, certified metrics used, upstream lineage, consumers, last review, next review date (default TTL 6 months), test status, and the full audit trail of AI recommendations and human approvals.

## 7. Human Oversight and Trust Principles

1. **AI recommends, humans decide.** Extend, Build, Certify, Merge and Retire are approval-gated with named approvers.
2. **Evidence over eloquence.** Every recommendation cites the assets, definitions and scores it relied on.
3. **No uncertified metrics in new builds.** The builder can only compose from the semantic layer.
4. **Permission-aware.** Search results respect the user's existing access rights; Curator never reveals assets the user cannot see.
5. **Sunset by default.** New assets get a review date; expiry triggers an owner confirmation, not silent deletion.
6. **Full audit log.** Prompt, retrieved evidence, recommendation, human decision and timestamp are stored.

## 8. Success Metrics (to show on the final slide)

| Metric | Definition |
|---|---|
| Reuse rate | Share of questions resolved via Answer/Reuse/Extend instead of Build |
| Assets avoided | Count of new builds prevented, with estimated hours saved |
| Certified metric adoption | Share of asset measures mapped to certified definitions |
| Estate shrinkage | Net assets retired or merged per quarter |
| Time to trusted answer | Median time from question to certified answer |
| Detection quality | Precision/recall of duplicate and conflict detection on the seeded dataset |

## 9. Hackathon Execution Plan (assumes ~48 hours, 4 people)

| Phase | Hours | Deliverables | Owner |
|---|---|---|---|
| 0. Setup | 0 to 3 | Repo, stack, synthetic data generator spec, UI skeleton | All |
| 1. Data and catalog | 3 to 10 | Synthetic estate (~300 assets, 40 metrics, planted conflicts), embeddings, lineage graph | Data engineer |
| 2. Core agents | 3 to 20 | Intent Agent, Discovery (hybrid search), Reuse Score, decision ladder | AI engineer |
| 3. Metric Conflict Radar | 10 to 24 | Formula normalisation, clustering, LLM judge with rationale | AI engineer + data engineer |
| 4. Frontend | 3 to 30 | Ask screen with coverage matrix, Estate Health, Conflict Resolver, Passport | Frontend/UX |
| 5. Governance | 20 to 32 | Approval gates, audit log, passport generation, policy checks | Backend |
| 6. Integration and evaluation | 30 to 40 | End-to-end flow, precision/recall numbers, edge cases | All |
| 7. Pitch | 40 to 48 | 3-minute demo script, slides, backup video | Product lead |

**Minimum viable demo (cut line):** Ask screen with decision ladder + coverage matrix, Metric Conflict view for one KPI, Estate Health summary. Everything else is stretch.

**Stretch goals:** Teams/Slack bot front door; MCP connector to a real Power BI or dbt project; "Estate diff" showing projected state after approving the sunset queue; cost estimate per asset from warehouse query logs.

## 10. Demo Storyline (3 minutes)

1. **Hook (20 s).** "This company has 312 dashboards and six definitions of Net Sales. AI would happily build the 313th." Show the Estate Health counters.
2. **Ask (60 s).** A commercial analyst asks for quarterly fungicide net sales by region versus last year. Curator clarifies "net sales", finds four assets, flags one conflict and one stale asset, and recommends *Extend* the certified cockpit, showing the coverage gap.
3. **Govern (40 s).** The asset owner receives the extension request, approves it; the passport updates; the audit log shows the AI evidence and the human decision.
4. **Steward (40 s).** Open the Net Sales conflict; AI explains that one variant is gross sales mislabelled; the steward approves the canonical definition and renames the variant, notifying nine owners.
5. **Impact (20 s).** Sunset queue: retiring 58 assets saves an estimated 140 maintenance hours per year. Close with reuse rate and detection precision.

**Pitch line:** *"Curator turns AI from a generator of more dashboards into a steward that decides which ones deserve to exist."*

## 11. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| LLM hallucinates an asset or metric | Recommendations restricted to retrieved catalog items; citations mandatory; deterministic formula comparison first |
| Poor metadata quality in real catalogs | Curator enriches metadata (auto-descriptions from measures and usage) and asks owners to confirm |
| Users bypass the front door | Integrate where they already work (Teams, BI tool plugin); make the reuse path faster than building |
| Over-aggressive retirement | Retire only with owner approval; archive before delete; reversible actions |
| Access control leakage | Permission-filtered retrieval at query time |
