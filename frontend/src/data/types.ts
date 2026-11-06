export type EntityType =
  | "metric"
  | "dashboard"
  | "dataset"
  | "source"
  | "person"
  | "glossary"
  | "domain"
  | "action"
  | "evidence" | "model" | "workspace" | "product" | "market" | "request";

export type Status =
  | "retired"
  | "certified"
  | "conflict"
  | "stale"
  | "orphaned"
  | "draft"
  | "uncertified"
  | "active"
  | "left" | "inactive";

export type RelationType =
  | "uses"
  | "feeds"
  | "sources"
  | "owns"
  | "derived_from"
  | "conflicts_with"
  | "equivalent_to"
  | "duplicate_of"
  | "overlaps"
  | "defines"
  | "belongs_to"
  | "joins"
  | "tracks"
  | "supports" | "variant_of" | "context" | "candidate_target";

export type Severity = "bad" | "warn" | "info";

export interface Flag {
  sev: Severity;
  title: string;
  text: string;
}

export interface Entity {
  id: string;
  uid: string;
  type: EntityType;
  name: string;
  status: Status;
  trust: number | null;
  sources?: SourceRef[];
  evidence_sources?: SourceRef[];
  usage_period?: string;
  updated: string;
  summary: string;
  props: Record<string, string>;
  flags: Flag[];
  /** Initials shown inside person nodes. */
  initials?: string;
  /** Views in the last 90 days (dashboards). */
  views?: number;
  /** AI-recommended governance action awaiting human approval. */
  action?: string;
}

export interface Edge {
  s: string;
  rel: RelationType;
  t: string;
  basis?: "lineage" | "join" | "candidate" | "runtime";
  label?: string;
  sources?: SourceRef[];
}

export interface SourceRef { sheet: string; row: number; record_id?: string; fields?: string[]; snapshot: string; }
