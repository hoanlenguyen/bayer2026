// Fictional sample estate used by the prototype. Replace with catalog API data later.
import type { Edge, Entity, EntityType, RelationType, Status } from "./types";

export const TYPES: Record<EntityType, { label: string; plural: string; r: number; glyph: string | null }> = {
  metric: { label: "Metric", plural: "Metrics", r: 15, glyph: "M" },
  dashboard: { label: "Dashboard", plural: "Dashboards", r: 14, glyph: "D" },
  dataset: { label: "Dataset", plural: "Datasets", r: 13, glyph: "DS" },
  source: { label: "Source system", plural: "Source systems", r: 12, glyph: "SS" },
  person: { label: "Person", plural: "People", r: 12, glyph: null },
  glossary: { label: "Glossary term", plural: "Glossary terms", r: 12, glyph: "G" },
  domain: { label: "Business domain", plural: "Business domains", r: 13, glyph: "BD" },
};

export const STATUS: Record<Status, { label: string; tone: "ok" | "warn" | "bad" | "neutral" }> = {
  certified: { label: "Certified", tone: "ok" },
  conflict: { label: "Conflict", tone: "bad" },
  stale: { label: "Stale", tone: "warn" },
  orphaned: { label: "Orphaned", tone: "warn" },
  draft: { label: "Draft", tone: "neutral" },
  uncertified: { label: "Uncertified", tone: "neutral" },
  active: { label: "Active", tone: "ok" },
  left: { label: "Left company", tone: "neutral" },
};

export const REL: Record<RelationType, { out: string; in: string; kind?: "bad" | "warn" | "accent" }> = {
  uses: { out: "Uses", in: "Used by" },
  feeds: { out: "Feeds", in: "Fed by" },
  sources: { out: "Supplies", in: "Sourced from" },
  owns: { out: "Owns", in: "Owned by" },
  derived_from: { out: "Derived from", in: "Input to" },
  conflicts_with: { out: "Conflicts with", in: "Conflicts with", kind: "bad" },
  equivalent_to: { out: "Equivalent to", in: "Equivalent to", kind: "accent" },
  duplicate_of: { out: "Duplicate of", in: "Duplicated by", kind: "warn" },
  overlaps: { out: "Overlaps with", in: "Overlaps with", kind: "warn" },
  defines: { out: "Defines", in: "Defined by" },
  belongs_to: { out: "Belongs to", in: "Contains" },
};

export const SEV = { bad: "High", warn: "Medium", info: "Info" } as const;

export const ENTITIES: Entity[] = [
  { id: "m_ns", uid: "met_9d41c2e7", type: "metric", name: "Net Sales", status: "certified", trust: 0.94, updated: "2026-11-05",
    summary: "Invoiced revenue after deducting customer rebates and product returns. This is the canonical revenue KPI for Crop Science commercial reporting.",
    props: { "Metric code": "NS_v3", "Formula": "SUM(invoice_amount) − SUM(rebate_amount) − SUM(return_amount)", "Unit": "EUR", "Grain": "Day × Product × Customer",
      "Additivity": "Fully additive", "Certified by": "A. Weber", "Certified on": "2026-03-14", "Next review": "2027-03-14" },
    flags: [
      { sev: "bad", title: "Conflicting definition in use", text: "“Net Sales (EMEA)” uses the same name but leaves out rebates and returns. Two dashboards with 314 views in the last 90 days rely on it." },
      { sev: "warn", title: "Used by a stale dashboard", text: "Fungicide Deep Dive has had no views in 210 days and its owner has left the company." }
    ] },
  { id: "m_ns_emea", uid: "met_51aa08f3", type: "metric", name: "Net Sales (EMEA)", status: "conflict", trust: 0.41, updated: "2026-10-02",
    summary: "Locally defined revenue measure inside the EMEA sales report. Its logic matches Gross Sales, not the certified Net Sales definition.",
    props: { "Metric code": "NS_EMEA_local", "Formula": "SUM(invoice_amount)", "Unit": "EUR", "Grain": "Month × Country", "Defined in": "EMEA Sales Q-Report (report-level measure)", "Certified by": "Not certified" },
    flags: [
      { sev: "bad", title: "Name collision with certified Net Sales", text: "Q3 2026 value is €465.2M versus €410.8M for certified Net Sales, a 13% gap caused by excluded rebates and returns." },
      { sev: "info", title: "Equivalent to Gross Sales", text: "Normalised formula is identical to GS_v1. Renaming it and relinking the dashboards removes the conflict without changing any numbers." }
    ],
    action: "Rename to Gross Sales and relink 2 dashboards to GS_v1" },
  { id: "m_gs", uid: "met_0c7e19b4", type: "metric", name: "Gross Sales", status: "certified", trust: 0.92, updated: "2026-09-21",
    summary: "Invoiced revenue before rebates and returns. Used for pricing and channel analysis.",
    props: { "Metric code": "GS_v1", "Formula": "SUM(invoice_amount)", "Unit": "EUR", "Grain": "Day × Product × Customer", "Certified by": "A. Weber", "Certified on": "2025-11-02", "Next review": "2026-11-30" },
    flags: [ { sev: "info", title: "Review due in 24 days", text: "Certification review is scheduled for 2026-11-30." } ] },
  { id: "m_ms", uid: "met_77b3d920", type: "metric", name: "Market Share", status: "certified", trust: 0.88, updated: "2026-10-15",
    summary: "Company net sales as a share of total market value reported by the external market panel.",
    props: { "Metric code": "MS_v2", "Formula": "Net Sales ÷ total_market_value", "Unit": "%", "Grain": "Quarter × Country × Crop", "Certified by": "A. Weber", "Certified on": "2026-01-20", "Next review": "2027-01-20" },
    flags: [] },
  { id: "m_rb", uid: "met_3f62aa15", type: "metric", name: "Rebate Rate", status: "draft", trust: 0.55, updated: "2026-08-30",
    summary: "Share of invoiced revenue returned to customers through rebate agreements. Still in draft.",
    props: { "Metric code": "RR_v0", "Formula": "SUM(rebate_amount) ÷ SUM(invoice_amount)", "Unit": "%", "Grain": "Month × Customer", "Certified by": "Not certified" },
    flags: [ { sev: "warn", title: "Draft metric in a production dashboard", text: "LATAM Pricing Monitor shows this metric to 186 viewers without a certified definition." } ],
    action: "Certify RR_v0 or remove it from LATAM Pricing Monitor" },
  { id: "m_vol", uid: "met_c90d4e61", type: "metric", name: "Sales Volume", status: "certified", trust: 0.9, updated: "2026-07-11",
    summary: "Quantity sold in base unit of measure. Liquids in litres, solids in kilograms.",
    props: { "Metric code": "VOL_v2", "Formula": "SUM(quantity_base_uom)", "Unit": "kg / L", "Grain": "Day × Product × Customer", "Certified by": "L. Brandt", "Certified on": "2026-02-08", "Next review": "2027-02-08" },
    flags: [] },

  { id: "db_cockpit", uid: "dsh_a1f0c3d2", type: "dashboard", name: "Crop Commercial Cockpit", status: "certified", trust: 0.93, views: 1240, updated: "2026-11-05",
    summary: "Global view of commercial performance by region, product group and channel. The certified entry point for Crop Science sales reporting.",
    props: { "Tool": "BI platform", "Workspace": "Crop Commercial · Global", "Views (90 days)": "1,240", "Last viewed": "2026-11-05", "Refresh": "Daily 05:00 UTC", "Created": "2024-02-02" },
    flags: [] },
  { id: "db_emea", uid: "dsh_6b2e9f17", type: "dashboard", name: "EMEA Sales Q-Report", status: "uncertified", trust: 0.52, views: 310, updated: "2026-10-03",
    summary: "Quarterly EMEA sales report built from a manual spreadsheet extract. Widely used in regional business reviews.",
    props: { "Tool": "BI platform", "Workspace": "EMEA Commercial", "Views (90 days)": "310", "Last viewed": "2026-11-04", "Refresh": "Manual", "Created": "2023-06-19" },
    flags: [
      { sev: "bad", title: "Uses a conflicting metric", text: "Shows “Net Sales (EMEA)”, which is gross sales under a certified KPI name." },
      { sev: "warn", title: "78% overlap with Crop Commercial Cockpit", text: "11 of 14 visuals answer questions the certified cockpit already answers for EMEA." }
    ],
    action: "Merge into Crop Commercial Cockpit as an EMEA page" },
  { id: "db_emea2", uid: "dsh_e4c71b09", type: "dashboard", name: "EMEA Sales Q-Report v2 (copy)", status: "orphaned", trust: 0.18, views: 4, updated: "2025-12-01",
    summary: "Copy of the EMEA Sales Q-Report created for a one-off review. Never maintained since.",
    props: { "Tool": "BI platform", "Workspace": "Personal workspace", "Views (90 days)": "4", "Last viewed": "2026-09-12", "Refresh": "None", "Created": "2025-11-28" },
    flags: [
      { sev: "warn", title: "Duplicate of EMEA Sales Q-Report", text: "96% of measures and visuals are identical." },
      { sev: "warn", title: "Owner left the company", text: "J. Kovac left on 2026-05-31. No backup owner is assigned." }
    ],
    action: "Retire: archive for 30 days, then delete" },
  { id: "db_fung", uid: "dsh_29d8f6ae", type: "dashboard", name: "Fungicide Deep Dive", status: "stale", trust: 0.31, views: 0, updated: "2025-10-14",
    summary: "Product-level analysis of fungicide sales built for the 2025 season planning cycle.",
    props: { "Tool": "BI platform", "Workspace": "Crop Portfolio Analytics", "Views (90 days)": "0", "Last viewed": "2026-04-10", "Refresh": "Weekly (still running)", "Created": "2025-03-03" },
    flags: [
      { sev: "warn", title: "No views in 210 days", text: "Weekly refresh still consumes about 3.1 compute hours per month." },
      { sev: "warn", title: "Owner left the company", text: "J. Kovac left on 2026-05-31." }
    ],
    action: "Ask the portfolio lead to confirm or retire" },
  { id: "db_latam", uid: "dsh_91c0b5e3", type: "dashboard", name: "LATAM Pricing Monitor", status: "uncertified", trust: 0.6, views: 186, updated: "2026-10-28",
    summary: "Price realisation and rebate tracking for Latin American distributors.",
    props: { "Tool": "BI platform", "Workspace": "LATAM Commercial", "Views (90 days)": "186", "Last viewed": "2026-11-06", "Refresh": "Daily 06:00 UTC", "Created": "2025-08-12" },
    flags: [ { sev: "warn", title: "Depends on a draft metric", text: "Rebate Rate (RR_v0) is not certified." } ] },
  { id: "db_exec", uid: "dsh_5ef2a870", type: "dashboard", name: "Executive Quarterly Review", status: "certified", trust: 0.91, views: 95, updated: "2026-10-31",
    summary: "Board-level quarterly summary of revenue, share and outlook.",
    props: { "Tool": "BI platform", "Workspace": "Finance · Leadership", "Views (90 days)": "95", "Last viewed": "2026-11-02", "Refresh": "Quarterly close", "Created": "2022-01-17" },
    flags: [] },

  { id: "ds_sales", uid: "tbl_4c19e2a0", type: "dataset", name: "sales_fact", status: "certified", trust: 0.95, updated: "2026-11-06",
    summary: "Invoice line items from ERP billing, one row per invoice line.",
    props: { "Table": "commercial.sales_fact", "Platform": "Lakehouse", "Refresh": "Daily 04:00 UTC", "Rows": "412.6M", "Quality tests": "38 / 38 passing", "Retention": "10 years" },
    flags: [] },
  { id: "ds_reb", uid: "tbl_7a0f3c58", type: "dataset", name: "rebate_agreements", status: "certified", trust: 0.9, updated: "2026-11-06",
    summary: "Accrued and settled customer rebates by agreement and period.",
    props: { "Table": "commercial.rebate_agreements", "Platform": "Lakehouse", "Refresh": "Daily 04:30 UTC", "Rows": "1.2M", "Quality tests": "12 / 12 passing", "Retention": "10 years" },
    flags: [] },
  { id: "ds_ret", uid: "tbl_b85d1e94", type: "dataset", name: "returns_fact", status: "certified", trust: 0.84, updated: "2026-11-06",
    summary: "Product returns and credit notes linked to the original invoice.",
    props: { "Table": "commercial.returns_fact", "Platform": "Lakehouse", "Refresh": "Daily 04:00 UTC", "Rows": "3.4M", "Quality tests": "9 / 10 passing", "Retention": "10 years" },
    flags: [ { sev: "warn", title: "One quality test failing", text: "return_reason is null for 2.1% of rows (threshold 1%) since 2026-11-03." } ] },
  { id: "ds_xls", uid: "fil_0e6c27bd", type: "dataset", name: "emea_sales_extract.xlsx", status: "uncertified", trust: 0.22, updated: "2026-10-02",
    summary: "Spreadsheet exported by hand from the ERP each quarter and uploaded to a team site.",
    props: { "Location": "Team site · EMEA Commercial / Reports", "Platform": "File upload", "Refresh": "Manual, last 2026-10-02", "Rows": "18,412", "Quality tests": "None", "Retention": "Not set" },
    flags: [ { sev: "bad", title: "Manual spreadsheet feeds a production report", text: "No lineage to source, no tests and no refresh schedule. sales_fact already holds the same data." } ],
    action: "Replace with certified sales_fact" },
  { id: "ds_mkt", uid: "tbl_d2a95f31", type: "dataset", name: "market_panel_data", status: "certified", trust: 0.86, updated: "2026-10-15",
    summary: "Licensed market size data by country, crop and quarter.",
    props: { "Table": "external.market_panel_data", "Platform": "Lakehouse", "Refresh": "Quarterly", "Rows": "96,300", "Quality tests": "7 / 7 passing", "Retention": "Per licence (5 years)" },
    flags: [] },

  { id: "src_erp", uid: "sys_11f4a0c2", type: "source", name: "ERP Billing", status: "active", trust: 0.97, updated: "2026-11-06",
    summary: "Order-to-cash system of record for invoices, credit notes and customers.",
    props: { "Kind": "ERP", "Connector": "CDC replication", "Last scan": "2026-11-06 02:00 UTC", "Data owner": "Finance Systems" }, flags: [] },
  { id: "src_tpm", uid: "sys_5b8e3d77", type: "source", name: "Trade Promotion Management", status: "active", trust: 0.9, updated: "2026-11-06",
    summary: "System for customer rebate agreements and promotion accruals.",
    props: { "Kind": "Commercial application", "Connector": "Nightly batch", "Last scan": "2026-11-06 02:05 UTC", "Data owner": "Commercial Excellence" }, flags: [] },
  { id: "src_panel", uid: "sys_9c2d6e18", type: "source", name: "Market Panel Provider", status: "active", trust: 0.85, updated: "2026-10-15",
    summary: "External vendor delivering quarterly market size estimates.",
    props: { "Kind": "External data feed", "Connector": "SFTP drop", "Last scan": "2026-10-15 08:00 UTC", "Data owner": "Market Intelligence" }, flags: [] },

  { id: "p_weber", uid: "usr_a.weber", type: "person", name: "A. Weber", initials: "AW", status: "active", trust: 1, updated: "2026-11-01",
    summary: "Finance data steward for commercial revenue metrics.",
    props: { "Role": "Finance Data Steward", "Team": "Finance Data Office", "Location": "Leverkusen" }, flags: [] },
  { id: "p_osei", uid: "usr_k.osei", type: "person", name: "K. Osei", initials: "KO", status: "active", trust: 1, updated: "2026-10-20",
    summary: "BI lead for the EMEA commercial organisation.",
    props: { "Role": "BI Lead EMEA", "Team": "EMEA Commercial Analytics", "Location": "Lyon" }, flags: [] },
  { id: "p_silva", uid: "usr_m.silva", type: "person", name: "M. Silva", initials: "MS", status: "active", trust: 1, updated: "2026-10-28",
    summary: "Commercial analyst for Latin American pricing.",
    props: { "Role": "Commercial Analyst", "Team": "LATAM Commercial", "Location": "São Paulo" }, flags: [] },
  { id: "p_kovac", uid: "usr_j.kovac", type: "person", name: "J. Kovac", initials: "JK", status: "left", trust: 0, updated: "2026-05-31",
    summary: "Former BI developer. Assets still list this person as the only owner.",
    props: { "Role": "BI Developer (former)", "Team": "Crop Portfolio Analytics", "Left on": "2026-05-31" },
    flags: [ { sev: "warn", title: "Owns 2 assets with no backup owner", text: "Ownership should move to the team lead before the assets can be reviewed." } ] },
  { id: "p_brandt", uid: "usr_l.brandt", type: "person", name: "L. Brandt", initials: "LB", status: "active", trust: 1, updated: "2026-10-31",
    summary: "FP&A lead responsible for executive reporting.",
    props: { "Role": "FP&A Lead", "Team": "Corporate Finance", "Location": "Berlin" }, flags: [] },

  { id: "g_ns", uid: "trm_net-sales", type: "glossary", name: "Net Sales (business term)", status: "certified", trust: 0.96, updated: "2026-03-14",
    summary: "Approved business definition: revenue from goods sold after customer rebates, discounts and returns, excluding taxes.",
    props: { "Steward": "A. Weber", "Approved by": "Finance Data Council", "Approved on": "2026-03-14", "Synonyms": "Net revenue, Net turnover" }, flags: [] },
  { id: "d_crop", uid: "dom_crop-commercial", type: "domain", name: "Crop Science Commercial", status: "active", trust: 1, updated: "2026-09-01",
    summary: "Business domain covering sales, pricing and market performance for crop protection and seeds.",
    props: { "Domain lead": "Commercial Excellence", "Certified metrics": "4", "Assets in catalog": "312" }, flags: [] }
];

export const EDGES: Edge[] = ([
  ["db_cockpit","uses","m_ns"], ["db_cockpit","uses","m_vol"], ["db_cockpit","uses","m_ms"],
  ["db_emea","uses","m_ns_emea"], ["db_emea","uses","m_vol"], ["db_emea2","uses","m_ns_emea"],
  ["db_fung","uses","m_ns"], ["db_fung","uses","m_vol"], ["db_latam","uses","m_ns"], ["db_latam","uses","m_rb"],
  ["db_exec","uses","m_ns"], ["db_exec","uses","m_ms"],
  ["ds_sales","feeds","m_ns"], ["ds_sales","feeds","m_gs"], ["ds_sales","feeds","m_vol"],
  ["ds_reb","feeds","m_ns"], ["ds_reb","feeds","m_rb"], ["ds_ret","feeds","m_ns"],
  ["ds_xls","feeds","m_ns_emea"], ["ds_mkt","feeds","m_ms"], ["m_ms","derived_from","m_ns"],
  ["src_erp","sources","ds_sales"], ["src_erp","sources","ds_ret"], ["src_erp","sources","ds_xls"],
  ["src_tpm","sources","ds_reb"], ["src_panel","sources","ds_mkt"],
  ["p_weber","owns","m_ns"], ["p_weber","owns","m_gs"], ["p_weber","owns","m_ms"], ["p_weber","owns","g_ns"], ["p_weber","owns","db_cockpit"],
  ["p_osei","owns","db_emea"], ["p_osei","owns","m_ns_emea"], ["p_osei","owns","ds_xls"],
  ["p_kovac","owns","db_emea2"], ["p_kovac","owns","db_fung"],
  ["p_silva","owns","db_latam"], ["p_silva","owns","m_rb"],
  ["p_brandt","owns","db_exec"], ["p_brandt","owns","m_vol"],
  ["m_ns_emea","conflicts_with","m_ns"], ["m_ns_emea","equivalent_to","m_gs"],
  ["db_emea2","duplicate_of","db_emea"], ["db_emea","overlaps","db_cockpit"],
  ["g_ns","defines","m_ns"],
  ["m_ns","belongs_to","d_crop"], ["m_gs","belongs_to","d_crop"], ["m_ms","belongs_to","d_crop"], ["m_vol","belongs_to","d_crop"]
] as [string, RelationType, string][]).map(([s, rel, t]) => ({ s, rel, t }));

export const PROV: Record<EntityType, (e: Entity) => [string, string, string][]> = {
  metric: (e) => [
    ["Semantic layer repository", `metrics/${e.props["Metric code"] ?? "local"}.yml @ a41f9c2`, "2026-11-06 02:10 UTC"],
    ["Usage telemetry", "BI audit log, 90-day window", "2026-11-06 03:00 UTC"],
  ],
  dashboard: () => [
    ["BI tenant scan", "Workspace scanner API", "2026-11-06 02:14 UTC"],
    ["Usage telemetry", "BI audit log, 90-day window", "2026-11-06 03:00 UTC"],
  ],
  dataset: () => [
    ["Data catalog scan", "Lakehouse metastore", "2026-11-06 02:20 UTC"],
    ["Quality test run", "Nightly test suite", "2026-11-06 04:45 UTC"],
  ],
  source: () => [["Integration registry", "Connector inventory", "2026-11-06 02:00 UTC"]],
  person: () => [["Directory sync", "Corporate HR directory", "2026-11-06 01:00 UTC"]],
  glossary: () => [["Business glossary", "Approved terms list", "2026-11-06 02:30 UTC"]],
  domain: () => [["Business glossary", "Domain model", "2026-11-06 02:30 UTC"]],
};
