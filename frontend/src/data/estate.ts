// Display vocabulary for the Estate Explorer. Entity data comes from the backend catalog.
import type { Edge, Entity, EntityType, RelationType, Status } from "./types";

export const TYPES: Record<EntityType, { label: string; plural: string; r: number; glyph: string | null }> = {
  metric: { label: "Measure", plural: "Measures", r: 15, glyph: "M" },
  dashboard: { label: "Report", plural: "Reports", r: 14, glyph: "R" },
  dataset: { label: "Dataset", plural: "Datasets", r: 13, glyph: "DS" },
  source: { label: "Source system", plural: "Source systems", r: 12, glyph: "SS" },
  person: { label: "Owner", plural: "Owners", r: 12, glyph: null },
  glossary: { label: "Glossary term", plural: "Glossary terms", r: 12, glyph: "G" },
  domain: { label: "Department", plural: "Departments", r: 13, glyph: "DP" },
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
  joins: { out: "Joins", in: "Joined by" },
};

export const SEV = { bad: "High", warn: "Medium", info: "Info" } as const;

/** Live estate, filled from GET /api/graph by `loadEstate()` in lib/estate.ts. Mutated in place. */
export const ENTITIES: Entity[] = [];
export const EDGES: Edge[] = [];

export const PROV: Record<EntityType, (e: Entity) => [string, string, string][]> = {
  metric: (e) => [["Semantic layer", `catalog_measures / ${e.id}`, `Loaded ${e.updated}`]],
  dashboard: (e) => [
    ["BI tenant scan", "Workspace scanner (sample catalog)", `Reviewed ${e.updated}`],
    ["Governance score", "decision.py, same rules as the Ask flow", "Computed on load"],
  ],
  dataset: () => [["Data catalog", "catalog_datasets: rows, refresh age, quality tests", "Computed on load"]],
  source: () => [["Integration registry", "Connector inventory", "Computed on load"]],
  person: () => [["Catalog owners", "Report and dataset owner fields", "Computed on load"]],
  glossary: () => [["Business glossary", "Approved terms list", "Computed on load"]],
  domain: () => [["Department map", "Dataset to department mapping", "Computed on load"]],
};
