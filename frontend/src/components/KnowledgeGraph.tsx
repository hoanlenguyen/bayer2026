import { useEffect, useMemo, useRef, useState } from "react";
import { REL, STATUS, TYPES } from "../data/estate";
import { EntitySearch } from "./EntitySearch";
import { Icon } from "./Icon";
import type { Edge, Entity, RelationType } from "../data/types";

/** Small unnamed dots that give the graph its density. They are not catalog items. Set to false to show only real items. */
const ILLUSTRATIVE_DOTS: boolean = false;

type Dot = { x: number; y: number; z: number; r: number; entity?: Entity; domain?: string };
type Vec = [number, number, number];

function seeded(start: number) {
  let seed = start;
  return () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
}

/** Even points on a sphere, used to start the layout and to shape the round clusters. */
const spherePoint = (i: number, n: number): Vec => {
  const y = n === 1 ? 0 : 1 - (2 * i) / (n - 1);
  const ring = Math.sqrt(Math.max(0, 1 - y * y));
  const a = i * Math.PI * (3 - Math.sqrt(5));
  return [ring * Math.cos(a), y, ring * Math.sin(a)];
};

/**
 * How hard each kind of link pulls in the layout. Report → model → workspace is the estate's
 * structure, so it forms the clusters. Reports use many KPIs and owners span workspaces, so
 * those links pull weakly; at full strength they collapse everything into one ball.
 */
const LINK_PULL: Partial<Record<RelationType, number>> = {
  sources: 1, belongs_to: 1, derived_from: 0.6, duplicate_of: 0.6, conflicts_with: 0.6, uses: 0.05, owns: 0.03,
};

/**
 * Which domain each item belongs to, from real links only: model → domain, model → report,
 * and owners go where they own the most. KPIs are shared across domains, so they get none.
 */
function assignDomains(entities: Entity[], edges: Edge[]): Map<string, string> {
  const domainOf = new Map(entities.filter((e) => e.type === "domain").map((e) => [e.id, e.id]));
  for (const l of edges) if (l.rel === "belongs_to" && domainOf.has(l.t)) domainOf.set(l.s, l.t);
  for (const l of edges) if (l.rel === "sources" && domainOf.has(l.s)) domainOf.set(l.t, domainOf.get(l.s)!);
  const owned = new Map<string, Map<string, number>>();
  for (const l of edges) {
    const d = l.rel === "owns" ? domainOf.get(l.t) : undefined;
    if (!d) continue;
    const counts = owned.get(l.s) ?? new Map<string, number>();
    owned.set(l.s, counts.set(d, (counts.get(d) ?? 0) + 1));
  }
  owned.forEach((counts, person) => {
    domainOf.set(person, [...counts].reduce((best, c) => (c[1] > best[1] ? c : best))[0]);
  });
  return domainOf;
}

/**
 * 3D force layout for the real items: each domain gets its own spot and pulls its items there,
 * linked items pull together, all items push apart. Items with no domain gather in the middle.
 * Each link's pull is shared by weighted degree, so hubs with dozens of links stay stable.
 * Typed arrays keep this fast enough for hundreds of items.
 */
function layoutItems(entities: Entity[], links: [number, number][], weights: number[], domainOf: Map<string, string>): Vec[] {
  const n = entities.length;
  const pos = new Float64Array(n * 3);
  const vel = new Float64Array(n * 3);
  const degree = new Float64Array(n);
  const home = new Float64Array(n * 3);
  const homePull = new Float64Array(n);
  const domains = entities.filter((e) => e.type === "domain");
  const spots = new Map(domains.map((d, i) => [d.id, spherePoint(i, domains.length).map((v) => v * 210)]));
  entities.forEach((e, i) => {
    const spot = spots.get(domainOf.get(e.id) ?? "");
    if (spot) home.set(spot, i * 3);
    homePull[i] = 0.1;
    pos.set(spherePoint(i, n).map((v, k) => (spot?.[k] ?? 0) + v * 30), i * 3);
  });
  links.forEach(([a, b], i) => { degree[a]! += weights[i]!; degree[b]! += weights[i]!; });

  const STEPS = 300, PUSH = 400, REST = 18, PULL = 0.35, DAMPING = 0.6;
  for (let step = 0; step < STEPS; step++) {
    const alpha = 1 - step / STEPS;
    for (let a = 0; a < n; a++) {
      const ax = a * 3;
      for (let b = a + 1; b < n; b++) {
        const bx = b * 3;
        const dx = pos[ax]! - pos[bx]!, dy = pos[ax + 1]! - pos[bx + 1]!, dz = pos[ax + 2]! - pos[bx + 2]!;
        const f = (PUSH * alpha) / Math.max(25, dx * dx + dy * dy + dz * dz);
        vel[ax]! += dx * f; vel[ax + 1]! += dy * f; vel[ax + 2]! += dz * f;
        vel[bx]! -= dx * f; vel[bx + 1]! -= dy * f; vel[bx + 2]! -= dz * f;
      }
    }
    for (let l = 0; l < links.length; l++) {
      const [a, b] = links[l]!;
      const ax = a * 3, bx = b * 3;
      const dx = pos[bx]! - pos[ax]!, dy = pos[bx + 1]! - pos[ax + 1]!, dz = pos[bx + 2]! - pos[ax + 2]!;
      const dist = Math.max(1, Math.hypot(dx, dy, dz));
      const da = degree[a]!, db = degree[b]!;
      const f = (((dist - REST) / dist) * PULL * alpha * weights[l]!) / Math.min(da, db);
      const shareA = db / (da + db), shareB = da / (da + db); // the busier item moves less
      vel[ax]! += dx * f * shareA; vel[ax + 1]! += dy * f * shareA; vel[ax + 2]! += dz * f * shareA;
      vel[bx]! -= dx * f * shareB; vel[bx + 1]! -= dy * f * shareB; vel[bx + 2]! -= dz * f * shareB;
    }
    for (let i = 0; i < n * 3; i++) {
      vel[i] = (vel[i]! - (pos[i]! - home[i]!) * homePull[Math.floor(i / 3)]!) * DAMPING;
      pos[i]! += vel[i]!;
    }
  }

  let far = 1;
  for (let i = 0; i < n; i++) far = Math.max(far, Math.hypot(pos[i * 3]!, pos[i * 3 + 1]!, pos[i * 3 + 2]!));
  const radius = Math.min(290, 125 * Math.cbrt(Math.max(1, n / 47))); // bigger estates get more room
  return entities.map((_, i) => [pos[i * 3]!, pos[i * 3 + 1]!, pos[i * 3 + 2]!].map((v) => (v / far) * radius) as Vec);
}

function buildGraph(entities: Entity[], catalogEdges: Edge[]) {
  const rand = seeded(7);
  const index = new Map(entities.map((e, i) => [e.id, i]));
  const known = catalogEdges.filter((l) => index.has(l.s) && index.has(l.t));
  const links = known.map((l): [number, number] => [index.get(l.s)!, index.get(l.t)!]);
  const degree = entities.map(() => 0);
  links.forEach(([a, b]) => { degree[a]!++; degree[b]!++; });

  const domainOf = assignDomains(entities, known);
  // Links between domains don't shape the layout, so each domain stays a separate group.
  const crossing = known.map((l) => domainOf.get(l.s) !== domainOf.get(l.t));
  const weights = known.map((l, i) => (crossing[i] ? 0.001 : LINK_PULL[l.rel] ?? 0.5));
  const nameOf = new Map(entities.map((e) => [e.id, e.name]));
  const positions = layoutItems(entities, links, weights, domainOf);
  const dots: Dot[] = entities.map((entity, i) => {
    const [x, y, z] = positions[i]!;
    const r = entity.type === "domain" ? 2.6 : Math.min(1.8, 0.8 + Math.sqrt(degree[i]!) * 0.14);
    return { x, y, z, r, entity, domain: nameOf.get(domainOf.get(entity.id) ?? "") };
  });
  const edges = [...links];
  if (!ILLUSTRATIVE_DOTS) return { dots, edges, crossing };

  const add = (x: number, y: number, z: number, r: number, parent: number) => {
    dots.push({ x, y, z, r });
    edges.push([parent, dots.length - 1]);
    return dots.length - 1;
  };
  const direction = (): Vec => {
    const t = Math.acos(2 * rand() - 1), p = rand() * Math.PI * 2;
    return [Math.sin(t) * Math.cos(p), Math.sin(t) * Math.sin(p), Math.cos(t)];
  };
  /** A round cluster of small dots on a shell around a centre. */
  const ball = (c: Vec, radius: number, count: number, r: number, parent: number) => {
    for (let i = 0; i < count; i++) {
      const [x, y, z] = spherePoint(i, count);
      const shell = radius * (0.72 + rand() * 0.28);
      add(c[0] + x * shell, c[1] + y * shell, c[2] + z * shell, r * (0.8 + rand() * 0.4), parent);
    }
  };

  // Dense middle: small tufts around the real items.
  entities.forEach((_, i) => {
    const count = 1 + Math.floor(rand() * rand() * 22);
    const [dx, dy, dz] = direction();
    const [x, y, z] = positions[i]!;
    const off = 6 + rand() * 18;
    ball([x + dx * off, y + dy * off, z + dz * off], 7 + count * 0.75, count, 1.25, i);
  });

  // Outer clusters, each joined to the middle by a short chain of dots.
  for (let c = 0; c < 15; c++) {
    const from = Math.floor(rand() * entities.length);
    const [dx, dy, dz] = direction();
    const dist = 175 + rand() * 170;
    const centre: Vec = [dx * dist, dy * dist, dz * dist];
    const [sx, sy, sz] = positions[from]!;
    let parent = from;
    for (const part of [0.45, 0.72, 0.9]) {
      if (rand() < 0.25) continue;
      parent = add(sx + (centre[0] - sx) * part, sy + (centre[1] - sy) * part, sz + (centre[2] - sz) * part, 1.5, parent);
    }
    const hub = add(centre[0], centre[1], centre[2], 1.4, parent);
    // A few clusters are open with bigger dots; most are tight small balls.
    if (c % 5 === 0) ball(centre, 34 + rand() * 12, 20 + Math.floor(rand() * 10), 2.3, hub);
    else ball(centre, 15 + rand() * 11, 14 + Math.floor(rand() * 26), 1.15, hub);
  }

  // Loose single dots between the middle and the outer clusters.
  for (let i = 0; i < 45; i++) {
    const from = Math.floor(rand() * entities.length);
    const [dx, dy, dz] = direction();
    const dist = 130 + rand() * 120;
    add(dx * dist, dy * dist, dz * dist, 1.3 + rand() * 1.3, from);
  }
  return { dots, edges, crossing };
}

interface Props {
  entities: Entity[];
  edges: Edge[];
  /** Draw each domain's name above its group. Off on the landing page, where only the dots show. */
  groupLabels?: boolean;
  /** Click to pin an item, and right-drag to pan. Off on the landing page: hover still works, clicks do nothing. */
  selectable?: boolean;
  /** Random items keep lighting up, a few at a time, each fading in, spreading its links, then fading out. */
  autoHighlight?: boolean;
  /** Show the highlighted item's name in a tooltip. Off on the landing page: only its links light up. */
  nameTips?: boolean;
  /** Links grow out of the highlighted item, with a pulse running along each and a ring around it. */
  animateLinks?: boolean;
  /** Size the graph so its widest extent fills this share of the panel (0 to 1). Unset: the fixed default scale. */
  fill?: number;
  /** Scroll to zoom. Off on the landing page, where the size stays fixed and the wheel is left to the page. */
  zoomable?: boolean;
  /** Domain groups take turns: a few at a time fade and shrink away, then come back. Shared KPIs stay put. */
  clusterCycle?: boolean;
  /** Multiplies every dot's size. 1 is the full graph page's size. */
  dotScale?: number;
}

/** Rotating 3D cloud of the catalog on a canvas. Hover or tap a named dot to see what it is. */
export function KnowledgeGraph({ entities, edges: catalogEdges, groupLabels = true, selectable = true, autoHighlight = false, nameTips = true, animateLinks = false, fill, zoomable = true, clusterCycle = false, dotScale = 1 }: Props) {
  const ref = useRef<HTMLCanvasElement>(null);
  const [hover, setHover] = useState<Dot | null>(null);
  const [selected, setSelected] = useState<Dot | null>(null);
  const [linkQuery, setLinkQuery] = useState("");
  useEffect(() => setLinkQuery(""), [selected]); // each item starts with its full list
  const pinRef = useRef<(id: string | null) => void>(() => undefined);

  /** Each item's linked items, grouped by how they relate to it, for the side panel. */
  const linksOf = useMemo(() => {
    const byId = new Map(entities.map((e) => [e.id, e]));
    const all = new Map<string, Map<string, Entity[]>>();
    const add = (id: string, label: string, other: Entity) => {
      const groups = all.get(id) ?? new Map<string, Entity[]>();
      groups.set(label, [...(groups.get(label) ?? []), other]);
      all.set(id, groups);
    };
    for (const l of catalogEdges) {
      const s = byId.get(l.s), t = byId.get(l.t);
      if (!s || !t) continue;
      add(s.id, REL[l.rel].out, t);
      add(t.id, REL[l.rel].in, s);
    }
    return all;
  }, [entities, catalogEdges]);
  const selectedLinks = [...(selected?.entity ? linksOf.get(selected.entity.id) ?? [] : [])];
  const linkCount = selectedLinks.reduce((sum, [, items]) => sum + items.length, 0);
  const query = linkQuery.trim().toLowerCase();
  const shownLinks = selectedLinks
    .map(([label, items]) => [label, items.filter((i) => `${i.name} ${TYPES[i.type].label}`.toLowerCase().includes(query))] as const)
    .filter(([, items]) => items.length > 0);
  const shownCount = shownLinks.reduce((sum, [, items]) => sum + items.length, 0);

  useEffect(() => {
    const canvas = ref.current!;
    const ctx = canvas.getContext("2d")!;
    const built = buildGraph(entities, catalogEdges);
    const { edges, crossing } = built;
    const dots = dotScale === 1 ? built.dots : built.dots.map((d) => ({ ...d, r: d.r * dotScale }));
    const css = getComputedStyle(canvas);
    const dotColor = css.getPropertyValue("--kg-dot").trim();
    const lineColor = css.getPropertyValue("--kg-line").trim();
    const lineFar = css.getPropertyValue("--kg-line-far").trim();
    const lineHover = css.getPropertyValue("--kg-line-hover").trim();
    const labelColor = css.getPropertyValue("--fg").trim();
    const labelHalo = css.getPropertyValue("--bg").trim();
    // Each group's label sits just above it, so it needs the group's centre and size.
    const members = new Map<string, Dot[]>();
    for (const d of dots) {
      if (!d.entity) continue;
      const name = d.domain ?? "Shared KPIs";
      members.set(name, [...(members.get(name) ?? []), d]);
    }
    const groups = [...members].map(([name, list]) => {
      const mean = (k: "x" | "y" | "z") => list.reduce((sum, d) => sum + d[k], 0) / list.length;
      const x = mean("x"), y = mean("y"), z = mean("z");
      return { name, x, y, z, radius: Math.max(...list.map((d) => Math.hypot(d.x - x, d.y - y, d.z - z))) };
    });
    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    let rx = -0.3, ry = 0, zoom = 1, panX = 0, panY = 0;
    let dragging: null | "rotate" | "pan" = null, lx = 0, ly = 0, raf = 0;
    let mx = -1e4, my = -1e4, held = false;
    let pinned = -1, downX = 0, downY = 0, clickable = false; // the clicked item stays highlighted
    let shift = 0; // moves the graph aside while the side panel is open
    const pin = (i: number) => { pinned = i; setSelected(i >= 0 ? dots[i]! : null); };
    pinRef.current = (id) => pin(id === null ? -1 : dots.findIndex((d) => d.entity?.id === id));
    const neighbours = dots.map((): number[] => []);
    for (const [a, b] of edges) { neighbours[a]!.push(b); neighbours[b]!.push(a); }
    // Items with a name and at least one link, for the random highlight.
    const named = dots.flatMap((d, i) => (d.entity && neighbours[i]!.length ? [i] : []));
    // Cluster cycle: each dot and each link inside a domain belongs to that domain's group.
    const groupNames = groups.map((g) => g.name);
    const groupOf = (d: Dot) => Math.max(0, groupNames.indexOf(d.domain ?? "Shared KPIs"));
    const dotGroup = dots.map(groupOf);
    const dotsByGroup = groupNames.map((): number[] => []);
    dotGroup.forEach((g, i) => dotsByGroup[g]!.push(i));
    const edgesByGroup = groupNames.map((): [number, number][] => []);
    const crossEdges: [number, number][] = [];
    edges.forEach((e, i) => (crossing[i] ? crossEdges.push(e) : edgesByGroup[dotGroup[e[0]]!]!.push(e)));
    // Groups that take part, in a fixed shuffled order so neighbouring groups don't fade one after another.
    const cycling = groupNames.map((_, g) => g).filter((g) => groupNames[g] !== "Shared KPIs");
    for (let k = cycling.length - 1; k > 0; k--) { const j = (k * 7 + 3) % (k + 1); [cycling[k], cycling[j]] = [cycling[j]!, cycling[k]!]; }
    const slot = new Map(cycling.map((g, k) => [g, k]));
    const CYCLE_STEP_MS = 1600; // a new group starts fading every 1.6 s
    const gAlpha = new Float32Array(groupNames.length).fill(1);
    const smooth = (t: number) => t * t * (3 - 2 * t);
    /** 1 most of the time; fades to 0.06 and back once per cycle, at this group's own moment. */
    const cycleAlpha = (g: number, now: number) => {
      const k = slot.get(g);
      if (k === undefined) return 1;
      const phase = (now / (CYCLE_STEP_MS * cycling.length) + k / cycling.length) % 1;
      if (phase < 0.72) return 1;
      if (phase < 0.8) return 1 - 0.94 * smooth((phase - 0.72) / 0.08);
      if (phase < 0.92) return 0.06;
      return 0.06 + 0.94 * smooth((phase - 0.92) / 0.08);
    };
    // Random highlights ("sparks"): a few live at once, each for SPARK_LIFE ms, started a little apart.
    const SPARK_LIFE = 6000, SPARK_MAX = 2;
    // Distance of the farthest dot from the centre: with `fill`, the graph is scaled so this reaches the panel's edge share.
    // Perspective adds at most about 4% while it turns, so a fill up to 0.9 stays inside the panel.
    const extent = Math.max(1, ...dots.map((d) => Math.hypot(d.x, d.y, d.z)));
    // Link animation timing (ms): links grow out, pulses run along them, the ring spreads, sparks fade in and out.
    const GROW_MS = 1500, PULSE_MS = 2800, RING_MS = 2600, FADE_IN_MS = 600, FADE_OUT_MS = 1400;
    let sparks: { i: number; at: number; speed: number }[] = [], nextSpark = performance.now() + 300; // as the graph grows in
    // The first sparks are the items nearest the centre, so the animation opens in the middle of the graph.
    const opening = [...named].sort((a, b) => Math.hypot(dots[a]!.x, dots[a]!.y, dots[a]!.z) - Math.hypot(dots[b]!.x, dots[b]!.y, dots[b]!.z)).slice(0, SPARK_MAX);
    let lit = -1, litAt = 0; // the highlighted item, and when it lit up: the link animation starts there
    const dotLinked = css.getPropertyValue("--kg-dot-linked").trim();
    const dotHover = css.getPropertyValue("--kg-dot-hover").trim();
    const tipBg = css.getPropertyValue("--kg-tip-bg").trim();
    const px = new Float32Array(dots.length), py = new Float32Array(dots.length), ps = new Float32Array(dots.length);

    /** One lit item at `age` ms: links grow out to its linked items, pulses run along them, a ring spreads from it. */
    const drawLit = (i: number, age: number, alpha: number) => {
      const grow = 1 - Math.pow(1 - Math.min(1, age / GROW_MS), 3);
      const hx = px[i]!, hy = py[i]!;
      const links = neighbours[i]!;
      ctx.save();
      ctx.globalAlpha = alpha;
      ctx.strokeStyle = lineHover;
      ctx.lineWidth = 1;
      ctx.beginPath();
      for (const j of links) { ctx.moveTo(hx, hy); ctx.lineTo(hx + (px[j]! - hx) * grow, hy + (py[j]! - hy) * grow); }
      ctx.stroke();
      ctx.fillStyle = dotHover;
      ctx.beginPath();
      links.forEach((j, k) => {
        const t = ((age / PULSE_MS + k * 0.17) % 1) * grow;
        const x = hx + (px[j]! - hx) * t, y = hy + (py[j]! - hy) * t;
        ctx.moveTo(x + 2.2, y);
        ctx.arc(x, y, 2.2, 0, Math.PI * 2);
      });
      ctx.fill();
      ctx.fillStyle = dotLinked;
      ctx.beginPath();
      for (const j of links) {
        const nr = Math.max(4, dots[j]!.r * ps[j]! * 1.5) * grow;
        ctx.moveTo(px[j]! + nr, py[j]!);
        ctx.arc(px[j]!, py[j]!, nr, 0, Math.PI * 2);
      }
      ctx.fill();
      const r = Math.max(7, dots[i]!.r * ps[i]! * 1.7) * Math.min(1, age / 500);
      ctx.fillStyle = dotHover;
      ctx.beginPath();
      ctx.arc(hx, hy, r, 0, Math.PI * 2);
      ctx.fill();
      const ring = (age % RING_MS) / RING_MS;
      ctx.globalAlpha = alpha * (1 - ring);
      ctx.strokeStyle = dotHover;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(hx, hy, r + ring * 18, 0, Math.PI * 2);
      ctx.stroke();
      ctx.restore();
    };

    const resize = () => {
      const dpr = window.devicePixelRatio || 1;
      canvas.width = canvas.clientWidth * dpr;
      canvas.height = canvas.clientHeight * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();

    const draw = () => {
      if (!dragging && !held && !motion.matches) ry += 0.0012; // hold still while an item is hovered
      const w = canvas.clientWidth, h = canvas.clientHeight;
      ctx.clearRect(0, 0, w, h);
      const cy = Math.cos(ry), sy = Math.sin(ry), cx = Math.cos(rx), sx = Math.sin(rx);
      const f = 1100; // a long lens keeps near groups from ballooning
      const base = zoom * (fill ? (fill * Math.min(w, h)) / (2 * extent) : Math.min(w, h) / 720);
      shift += ((pinned >= 0 && w > 768 ? 160 : 0) - shift) * 0.15;
      const viewX = w / 2 + panX - shift;
      let hovered = -1, nearest = 10;
      dots.forEach((d, i) => {
        const x1 = d.x * cy - d.z * sy, z1 = d.x * sy + d.z * cy;
        const y2 = d.y * cx - z1 * sx, z2 = d.y * sx + z1 * cx;
        const s = (f / Math.max(60, f + z2)) * base;
        px[i] = viewX + x1 * s; py[i] = h / 2 + panY + y2 * s; ps[i] = s;
        if (d.entity) {
          const dist = Math.hypot(px[i]! - mx, py[i]! - my);
          if (dist < nearest) { nearest = dist; hovered = i; }
        }
      });

      if (!dragging) canvas.style.cursor = hovered >= 0 && selectable ? "pointer" : "grab";
      const pointed = hovered >= 0;
      if (hovered < 0) hovered = pinned; // hovering another item previews it; otherwise the pinned one shows
      const now = performance.now();
      if (hovered !== lit) { lit = hovered; litAt = now; }
      const moving = animateLinks && !motion.matches;
      const age = now - litAt;
      const grow = moving ? 1 - Math.pow(1 - Math.min(1, age / GROW_MS), 3) : 1; // ease-out: 0 → 1 over GROW_MS

      const cycleOn = clusterCycle && !motion.matches;
      for (let g = 0; g < gAlpha.length; g++) gAlpha[g] = cycleOn ? cycleAlpha(g, now) : 1;
      ctx.lineWidth = 0.2;
      ctx.strokeStyle = lineFar;
      ctx.beginPath();
      for (const [a, b] of crossEdges) { ctx.moveTo(px[a]!, py[a]!); ctx.lineTo(px[b]!, py[b]!); }
      ctx.stroke();
      ctx.strokeStyle = lineColor;
      edgesByGroup.forEach((list, g) => {
        ctx.globalAlpha = gAlpha[g]!;
        ctx.beginPath();
        for (const [a, b] of list) { ctx.moveTo(px[a]!, py[a]!); ctx.lineTo(px[b]!, py[b]!); }
        ctx.stroke();
      });
      ctx.globalAlpha = 1;

      if (hovered >= 0) {
        ctx.strokeStyle = lineHover;
        ctx.lineWidth = 1;
        ctx.beginPath();
        // Drawn from the highlighted item outwards, so the links can grow out of it.
        const hx0 = px[hovered]!, hy0 = py[hovered]!;
        for (const j of neighbours[hovered]!) {
          ctx.moveTo(hx0, hy0);
          ctx.lineTo(hx0 + (px[j]! - hx0) * grow, hy0 + (py[j]! - hy0) * grow);
        }
        ctx.stroke();
        if (moving) {
          // A small pulse runs out along each link, each a little out of step with the others.
          ctx.fillStyle = dotHover;
          ctx.beginPath();
          neighbours[hovered]!.forEach((j, k) => {
            const t = ((age / PULSE_MS + k * 0.17) % 1) * grow;
            const x = hx0 + (px[j]! - hx0) * t, y = hy0 + (py[j]! - hy0) * t;
            ctx.moveTo(x + 2.2, y);
            ctx.arc(x, y, 2.2, 0, Math.PI * 2);
          });
          ctx.fill();
        }
      }

      ctx.fillStyle = dotColor;
      dotsByGroup.forEach((list, g) => {
        const a = gAlpha[g]!;
        ctx.globalAlpha = a;
        ctx.beginPath();
        for (const i of list) {
          if (i === hovered) continue; // drawn on top below
          const r = dots[i]!.r * ps[i]! * (0.4 + 0.6 * a); // a fading group also shrinks
          ctx.moveTo(px[i]! + r, py[i]!);
          ctx.arc(px[i]!, py[i]!, r, 0, Math.PI * 2);
        }
        ctx.fill();
      });
      ctx.globalAlpha = 1;

      // Domain names, so each group can be read at a glance.
      ctx.font = `600 ${w < 560 ? 10 : 12}px ${css.fontFamily}`;
      ctx.textAlign = "center";
      ctx.textBaseline = "alphabetic";
      ctx.lineWidth = 3;
      ctx.lineJoin = "round";
      ctx.strokeStyle = labelHalo;
      ctx.fillStyle = labelColor;
      const label = (name: string, x: number, y: number) => {
        const half = ctx.measureText(name).width / 2 + 4;
        const inside = half * 2 < w ? Math.min(w - half, Math.max(half, x)) : x; // stay on screen
        ctx.strokeText(name, inside, y);
        ctx.fillText(name, inside, y);
      };
      if (groupLabels) for (const g of groups) {
        const x1 = g.x * cy - g.z * sy, z1 = g.x * sy + g.z * cy;
        const y2 = g.y * cx - z1 * sx, z2 = g.y * sx + z1 * cx;
        const s = (f / Math.max(60, f + z2)) * base;
        label(g.name, viewX + x1 * s, h / 2 + panY + y2 * s - g.radius * s - 7);
      }

      // Sparks: drawn under the hovered item. They skip reduced motion, where nothing should move on its own.
      if (autoHighlight && named.length && !motion.matches) {
        sparks = sparks.filter((sp) => now - sp.at < SPARK_LIFE);
        if (now >= nextSpark && sparks.length < SPARK_MAX) {
          const first = opening.length > 0; // the opening pair plays faster, so the page comes alive quickly
          const i = first ? opening.shift()! : named[Math.floor(Math.random() * named.length)]!;
          if (i !== hovered && gAlpha[dotGroup[i]!] === 1 && !sparks.some((sp) => sp.i === i)) sparks.push({ i, at: now, speed: first ? 2.2 : 1 });
          nextSpark = now + (opening.length ? 250 : 900 + Math.random() * 1100); // the opening pair starts close together
        }
        for (const sp of sparks) {
          const a = now - sp.at;
          const fade = Math.min(1, a / FADE_IN_MS, (SPARK_LIFE - a) / FADE_OUT_MS);
          drawLit(sp.i, a * sp.speed, Math.max(0, fade));
        }
      }

      // The hovered item: a coral dot with its name in a tooltip just below, and its linked items in amber.
      if (hovered >= 0) {
        ctx.fillStyle = dotLinked;
        ctx.beginPath();
        for (const i of neighbours[hovered]!) {
          const nr = Math.max(4, dots[i]!.r * ps[i]! * 1.5) * grow; // linked items appear as their link reaches them
          ctx.moveTo(px[i]! + nr, py[i]!);
          ctx.arc(px[i]!, py[i]!, nr, 0, Math.PI * 2);
        }
        ctx.fill();

        const name = dots[hovered]!.entity!.name;
        const hx = px[hovered]!, hy = py[hovered]!;
        const r = Math.max(7, dots[hovered]!.r * ps[hovered]! * 1.7);
        ctx.fillStyle = dotHover;
        ctx.beginPath();
        ctx.arc(hx, hy, r, 0, Math.PI * 2);
        ctx.fill();
        if (moving) {
          // A ring spreads out from the item and fades, once every 1.3 s.
          const ring = (age % RING_MS) / RING_MS;
          ctx.save();
          ctx.globalAlpha = 1 - ring;
          ctx.strokeStyle = dotHover;
          ctx.lineWidth = 1.5;
          ctx.beginPath();
          ctx.arc(hx, hy, r + ring * 18, 0, Math.PI * 2);
          ctx.stroke();
          ctx.restore();
        }

        if (nameTips) {
        ctx.font = `400 14px ${css.fontFamily}`;
        const tipW = ctx.measureText(name).width + 20, tipH = 30, gap = 12;
        const tipX = Math.max(4, Math.min(w - tipW - 4, hx - tipW / 2));
        const below = hy + r + gap + tipH <= h - 4;
        const tipY = below ? hy + r + gap : hy - r - gap - tipH;
        ctx.fillStyle = tipBg;
        ctx.beginPath();
        ctx.roundRect(tipX, tipY, tipW, tipH, 4);
        ctx.fill();
        ctx.fillStyle = "#ffffff";
        ctx.textBaseline = "middle";
        ctx.fillText(name, tipX + tipW / 2, tipY + tipH / 2 + 1);
        }
      }

      held = pointed || pinned >= 0; // a random highlight never stops the rotation
      setHover(hovered >= 0 ? dots[hovered]! : null);
      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);

    const track = (e: PointerEvent) => {
      const r = canvas.getBoundingClientRect(); mx = e.clientX - r.left; my = e.clientY - r.top;
    };
    const down = (e: PointerEvent) => {
      track(e);
      dragging = e.button === 2 && selectable ? "pan" : "rotate"; // not selectable: no panning, so the centre stays put
      lx = e.clientX; ly = e.clientY; canvas.setPointerCapture(e.pointerId);
      downX = e.clientX; downY = e.clientY; clickable = e.button === 0;
      canvas.style.cursor = "grabbing";
    };
    const move = (e: PointerEvent) => {
      track(e);
      if (!dragging) return;
      const dx = e.clientX - lx, dy = e.clientY - ly; lx = e.clientX; ly = e.clientY;
      if (dragging === "rotate") { ry += dx * 0.005; rx += dy * 0.005; } else { panX += dx; panY += dy; }
    };
    const up = () => { dragging = null; canvas.style.cursor = "grab"; };
    /** A press that barely moved is a click: pin the item under it, or clear the pin. Otherwise it was a drag. */
    const release = (e: PointerEvent) => {
      up();
      if (!selectable || !clickable || Math.hypot(e.clientX - downX, e.clientY - downY) > 5) return;
      track(e);
      let under = -1, nearest = 10;
      dots.forEach((d, i) => {
        const dist = Math.hypot(px[i]! - mx, py[i]! - my);
        if (d.entity && dist < nearest) { nearest = dist; under = i; }
      });
      pin(under === pinned ? -1 : under);
    };
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") pin(-1); };
    const leave = () => { mx = my = -1e4; };
    const wheel = (e: WheelEvent) => {
      if (!zoomable) return;
      e.preventDefault();
      zoom = Math.min(4, Math.max(0.4, zoom * (e.deltaY > 0 ? 0.92 : 1.08)));
    };
    const ctxMenu = (e: Event) => e.preventDefault();

    const listeners = new AbortController();
    const { signal } = listeners;
    window.addEventListener("resize", resize, { signal });
    canvas.addEventListener("pointerdown", down, { signal });
    canvas.addEventListener("pointermove", move, { signal });
    window.addEventListener("keydown", key, { signal });
    canvas.addEventListener("pointerup", release, { signal });
    canvas.addEventListener("pointercancel", up, { signal });
    canvas.addEventListener("pointerleave", leave, { signal });
    canvas.addEventListener("wheel", wheel, { passive: false, signal });
    canvas.addEventListener("contextmenu", ctxMenu, { signal });
    return () => {
      cancelAnimationFrame(raf);
      listeners.abort();
    };
  }, [entities, catalogEdges, groupLabels, selectable, autoHighlight, nameTips, animateLinks, fill, zoomable, clusterCycle, dotScale]);

  return (
    <div className={`kg${selected ? " kg-open" : ""}`}>
      <canvas ref={ref} className="kg-canvas" role="img" aria-label={`Graph of ${entities.length} catalog items and ${catalogEdges.length} links.`} />
      <div className="kg-search"><EntitySearch onPick={(id) => pinRef.current(id)} /></div>
      <div className="kg-card" hidden={!!selected && hover === selected}>
        {hover?.entity ? (
          <>
            <p className="kg-card-title">{hover.entity.name}</p>
            <p>{TYPES[hover.entity.type].label} · {STATUS[hover.entity.status].label}</p>
            {hover.entity.type !== "domain" && <p>{hover.domain ?? "Shared across domains"}</p>}
          </>
        ) : (
          <>
            <p>Live catalog: {entities.length} items, {catalogEdges.length} links.</p>
            <p>Grouped by domain. Shared KPIs sit in the middle.</p>
            <p>Click a dot to see what links to it.</p>
            {ILLUSTRATIVE_DOTS && <p>Small unnamed dots are illustrative only.</p>}
          </>
        )}
      </div>
      {selected?.entity && (
        <aside className="kg-panel" aria-label={`Items linked to ${selected.entity.name}`}>
          <header className="kg-panel-head">
            <div>
              <h2>{selected.entity.name}</h2>
              <p>{TYPES[selected.entity.type].label} · {STATUS[selected.entity.status].label}</p>
              {selected.entity.type !== "domain" && <p>{selected.domain ?? "Shared across domains"}</p>}
            </div>
            <button type="button" className="kg-panel-close" aria-label="Close" onClick={() => pinRef.current(null)}><Icon name="close" /></button>
          </header>
          <div className="kg-panel-tools">
            <p className="kg-panel-count">{query ? `${shownCount} of ` : ""}{linkCount} linked {linkCount === 1 ? "item" : "items"}</p>
            {linkCount > 0 && (
              <div className="search">
                <label htmlFor="kg-link-search" className="sr-only">Search linked items</label>
                <Icon name="search" />
                <input
                  id="kg-link-search"
                  type="search"
                  placeholder="Search linked items"
                  autoComplete="off"
                  value={linkQuery}
                  onChange={(e) => setLinkQuery(e.target.value)}
                  // Esc clears the search first; only an empty box lets it close the panel.
                  onKeyDown={(e) => { if (e.key === "Escape" && linkQuery) { e.stopPropagation(); setLinkQuery(""); } }}
                />
              </div>
            )}
          </div>
          <div className="kg-panel-body">
            {query && shownCount === 0 && <p className="kg-panel-empty">Nothing matches “{linkQuery.trim()}”.</p>}
            {shownLinks.map(([label, items]) => (
              <section key={label}>
                <h3>{label} <span>{items.length}</span></h3>
                <ul>
                  {[...items].sort((a, b) => a.name.localeCompare(b.name)).map((item) => (
                    <li key={item.id}>
                      <button type="button" onClick={() => pinRef.current(item.id)}>
                        <span className="kg-row-name">{item.name}</span>
                        <span className="kg-row-type">{TYPES[item.type].label}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            ))}
          </div>
        </aside>
      )}
    </div>
  );
}
