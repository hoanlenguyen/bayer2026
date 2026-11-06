// Live graph data from the shared, filtered analytics catalogue.
import type { Edge, Entity, EntityType, RelationType, Status } from "./types";

export const TYPES: Record<
  EntityType,
  { label: string; plural: string; r: number; glyph: string | null }
> = {
  model: { label: "Semantic model", plural: "Models", r: 18, glyph: "SM" },
  workspace: { label: "Workspace", plural: "Workspaces", r: 15, glyph: "WS" },
  product: { label: "Product", plural: "Products", r: 13, glyph: "P" },
  market: { label: "Market", plural: "Markets", r: 13, glyph: "MK" },
  request: { label: "Request", plural: "Requests", r: 13, glyph: "R" },
  action: { label: "Action", plural: "Actions", r: 13, glyph: "A" },
  evidence: { label: "Evidence", plural: "Evidence", r: 11, glyph: "E" },
  metric: { label: "Metric", plural: "Metrics", r: 15, glyph: "M" },
  dashboard: { label: "Dashboard", plural: "Dashboards", r: 14, glyph: "D" },
  dataset: { label: "Dataset", plural: "Datasets", r: 13, glyph: "DS" },
  source: {
    label: "Source system",
    plural: "Source systems",
    r: 12,
    glyph: "SS",
  },
  person: { label: "Person", plural: "People", r: 12, glyph: null },
  glossary: {
    label: "Glossary term",
    plural: "Glossary terms",
    r: 12,
    glyph: "G",
  },
  domain: {
    label: "Business domain",
    plural: "Business domains",
    r: 13,
    glyph: "BD",
  },
};

export const STATUS: Record<
  Status,
  { label: string; tone: "ok" | "warn" | "bad" | "neutral" }
> = {
  inactive: { label: "Inactive", tone: "warn" },
  retired: { label: "Retired", tone: "neutral" },
  certified: { label: "Certified", tone: "ok" },
  conflict: { label: "Conflict", tone: "bad" },
  stale: { label: "Stale", tone: "warn" },
  orphaned: { label: "Orphaned", tone: "warn" },
  draft: { label: "Draft", tone: "neutral" },
  uncertified: { label: "Uncertified", tone: "neutral" },
  active: { label: "Active", tone: "ok" },
  left: { label: "Left company", tone: "neutral" },
};

export const REL: Record<
  RelationType,
  { out: string; in: string; kind?: "bad" | "warn" | "accent" }
> = {
  variant_of: { out: "Variant of", in: "Variants" },
  context: { out: "Declared context", in: "Context for" },
  candidate_target: { out: "Candidate destination", in: "Proposed source", kind: "warn" },
  joins: { out: "Joins", in: "Joins" },
  tracks: { out: "Tracks", in: "Tracked by" },
  supports: { out: "Supports", in: "Evidence from" },
  uses: { out: "Uses", in: "Used by" },
  feeds: { out: "Feeds", in: "Fed by" },
  sources: { out: "Supplies", in: "Sourced from" },
  owns: { out: "Owns", in: "Owned by" },
  derived_from: { out: "Derived from", in: "Input to" },
  conflicts_with: { out: "Conflicts with", in: "Conflicts with", kind: "bad" },
  equivalent_to: { out: "Equivalent to", in: "Equivalent to", kind: "accent" },
  duplicate_of: { out: "Duplicate of", in: "Duplicated by", kind: "warn" },
  overlaps: {
    out: "Shares metrics with",
    in: "Shares metrics with",
    kind: "warn",
  },
  defines: { out: "Defines", in: "Defined by" },
  belongs_to: { out: "Belongs to", in: "Contains" },
};

export const SEV = { bad: "High", warn: "Medium", info: "Info" } as const;

export const ENTITIES: Entity[] = [];
export const EDGES: Edge[] = [];
export const PROV: Record<
  EntityType,
  (e: Entity) => [string, string, string][]
> = Object.fromEntries(
  Object.keys(TYPES).map((k) => [
    k,
    (e: Entity) => [
      [
        "Shared analytics record",
        e.props["Evidence scope"] ?? "Imported fictional sample metadata",
        e.updated,
      ],
    ],
  ]),
) as Record<EntityType, (e: Entity) => [string, string, string][]>;
