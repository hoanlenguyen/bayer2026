import { EDGES, ENTITIES, REL, TYPES } from "../data/estate";
import type { Entity, EntityType } from "../data/types";

export const byId: Record<string, Entity> = Object.fromEntries(ENTITIES.map((e) => [e.id, e]));

const adjacency = new Map<string, string[]>(ENTITIES.map((e) => [e.id, []]));
EDGES.forEach((l) => {
  adjacency.get(l.s)!.push(l.t);
  adjacency.get(l.t)!.push(l.s);
});

export const toneOf = (v: number) => (v >= 0.8 ? "ok" : v >= 0.5 ? "warn" : "bad");
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

/** Breadth-first neighbourhood of `focus` up to `depth` hops, skipping hidden types. */
export function neighborhood(focus: string, depth: number, hidden: Set<EntityType>) {
  const dist = new Map<string, number>([[focus, 0]]);
  const queue = [focus];
  while (queue.length) {
    const id = queue.shift()!;
    const d = dist.get(id)!;
    if (d >= depth) continue;
    for (const n of adjacency.get(id)!) {
      if (dist.has(n) || hidden.has(byId[n].type)) continue;
      dist.set(n, d + 1);
      queue.push(n);
    }
  }
  return dist;
}
