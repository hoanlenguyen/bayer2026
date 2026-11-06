import { EDGES, ENTITIES, REL, TYPES } from "../data/estate";
import type { Edge, Entity, EntityType } from "../data/types";

export const byId: Record<string, Entity> = {};
const adjacency = new Map<string, string[]>();

/** Replace the estate with data from the backend and rebuild the lookups. */
export function setEstate(entities: Entity[], edges: Edge[]) {
  ENTITIES.splice(0, ENTITIES.length, ...entities);
  EDGES.splice(0, EDGES.length, ...edges);
  Object.keys(byId).forEach((k) => delete byId[k]);
  adjacency.clear();
  ENTITIES.forEach((e) => { byId[e.id] = e; adjacency.set(e.id, []); });
  EDGES.forEach((l) => {
    adjacency.get(l.s)?.push(l.t);
    adjacency.get(l.t)?.push(l.s);
  });
}

export interface GraphPayload {
  entities: Entity[];
  edges: Edge[];
  focus: string;
  counts: { reports: number; measures: number; datasets: number };
}

/** Fetch the plant catalog graph from the backend. */
export async function loadEstate(): Promise<GraphPayload> {
  const res = await fetch("/api/graph");
  if (!res.ok) throw new Error(`/api/graph returned ${res.status}`);
  const data = (await res.json()) as GraphPayload;
  setEstate(data.entities, data.edges);
  return data;
}

export const toneOf = (v: number | null) => (v === null ? "muted" : v >= 0.8 ? "ok" : v >= 0.5 ? "warn" : "bad");
export const glyphOf = (e: Entity) => (e.type === "person" ? e.initials ?? "" : TYPES[e.type].glyph ?? "");
export const trunc = (s: string, n: number) => (s.length > n ? s.slice(0, n - 1) + "…" : s);

export function ownerOf(id: string): Entity | null {
  const l = EDGES.find((x) => x.t === id && x.rel === "owns");
  return l ? byId[l.s] : null;
}

export function relationCount(id: string) {
  return EDGES.filter((l) => l.s === id || l.t === id).length;
}

export interface RelGroup {
  label: string;
  kind?: "bad" | "warn" | "accent";
  items: Entity[];
}

/** Relationships of an entity grouped by direction-aware label, issues first. */
export function relGroups(id: string): RelGroup[] {
  const groups = new Map<string, RelGroup>();
  EDGES.forEach((l) => {
    let label: string, other: string;
    if (l.s === id) { label = REL[l.rel].out; other = l.t; }
    else if (l.t === id) { label = REL[l.rel].in; other = l.s; }
    else return;
    if (!groups.has(label)) groups.set(label, { label, kind: REL[l.rel].kind, items: [] });
    groups.get(label)!.items.push(byId[other]);
  });
  const order = (g: RelGroup) => (g.kind === "bad" ? 0 : g.kind === "warn" ? 1 : g.kind === "accent" ? 2 : 3);
  return [...groups.values()].sort((a, b) => order(a) - order(b) || b.items.length - a.items.length);
}

export type Direction = "all" | "upstream" | "downstream";
export function graphEdges(direction: Direction, candidates: boolean): Edge[] {
  return EDGES.filter(e => (candidates || e.basis !== "candidate") && (direction === "all" || e.basis === "lineage"));
}
/** Cycle-safe directed traversal. Context joins never imply dependency impact. */
export function neighborhood(focus: string, depth: number, hidden: Set<EntityType>, direction: Direction = "all", candidates = false, limit = 90) {
  const dist = new Map<string, number>();
  if (!byId[focus]) return dist;
  dist.set(focus, 0);
  const adj = new Map<string, string[]>();
  const add = (s: string, t: string) => { if (byId[s] && byId[t]) { const a = adj.get(s) ?? []; a.push(t); adj.set(s,a); } };
  graphEdges(direction, candidates).sort((a,b) => Number(b.basis === "lineage") - Number(a.basis === "lineage")).forEach(e => {
    if (direction !== "upstream") add(e.s, e.t);
    if (direction !== "downstream") add(e.t, e.s);
  });
  const queue = [focus];
  for (let i = 0; i < queue.length; i++) {
    const id = queue[i], d = dist.get(id)!;
    if (d >= depth) continue;
    for (const next of adj.get(id) ?? []) {
      if (dist.has(next) || hidden.has(byId[next].type)) continue;
      if (dist.size >= limit) return dist;
      dist.set(next,d+1); queue.push(next);
    }
  }
  return dist;
}
