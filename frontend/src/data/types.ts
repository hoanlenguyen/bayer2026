export type EntityType = "metric" | "dashboard" | "dataset" | "source" | "person" | "glossary" | "domain";

export type Status =
  | "certified" | "conflict" | "stale" | "orphaned" | "draft" | "uncertified" | "active" | "left";

export type RelationType =
  | "uses" | "feeds" | "sources" | "owns" | "derived_from" | "conflicts_with"
  | "equivalent_to" | "duplicate_of" | "overlaps" | "defines" | "belongs_to";

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
  trust: number;
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
}
