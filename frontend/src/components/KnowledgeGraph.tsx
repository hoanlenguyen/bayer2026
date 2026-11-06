import { useEffect, useRef, useState } from "react";
import { STATUS, TYPES } from "../data/estate";
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
}

/** Rotating 3D cloud of the catalog on a canvas. Hover or tap a named dot to see what it is. */
export function KnowledgeGraph({ entities, edges: catalogEdges }: Props) {
  const ref = useRef<HTMLCanvasElement>(null);
  const [hover, setHover] = useState<Dot | null>(null);

  useEffect(() => {
    const canvas = ref.current!;
    const ctx = canvas.getContext("2d")!;
    const { dots, edges, crossing } = buildGraph(entities, catalogEdges);
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
    const neighbours = dots.map((): number[] => []);
    for (const [a, b] of edges) { neighbours[a]!.push(b); neighbours[b]!.push(a); }
    const dotLinked = css.getPropertyValue("--kg-dot-linked").trim();
    const dotHover = css.getPropertyValue("--kg-dot-hover").trim();
    const tipBg = css.getPropertyValue("--kg-tip-bg").trim();
    const px = new Float32Array(dots.length), py = new Float32Array(dots.length), ps = new Float32Array(dots.length);

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
      const f = 1100, base = zoom * Math.min(w, h) / 720; // a long lens keeps near groups from ballooning
      let hovered = -1, nearest = 10;
      dots.forEach((d, i) => {
        const x1 = d.x * cy - d.z * sy, z1 = d.x * sy + d.z * cy;
        const y2 = d.y * cx - z1 * sx, z2 = d.y * sx + z1 * cx;
        const s = (f / Math.max(60, f + z2)) * base;
        px[i] = w / 2 + panX + x1 * s; py[i] = h / 2 + panY + y2 * s; ps[i] = s;
        if (d.entity) {
          const dist = Math.hypot(px[i]! - mx, py[i]! - my);
          if (dist < nearest) { nearest = dist; hovered = i; }
        }
      });

      ctx.lineWidth = 0.2;
      for (const far of [true, false]) {
        ctx.strokeStyle = far ? lineFar : lineColor;
        ctx.beginPath();
        edges.forEach(([a, b], i) => {
          if (!!crossing[i] === far) { ctx.moveTo(px[a]!, py[a]!); ctx.lineTo(px[b]!, py[b]!); }
        });
        ctx.stroke();
      }

      if (hovered >= 0) {
        ctx.strokeStyle = lineHover;
        ctx.lineWidth = 1;
        ctx.beginPath();
        for (const [a, b] of edges) {
          if (a === hovered || b === hovered) { ctx.moveTo(px[a]!, py[a]!); ctx.lineTo(px[b]!, py[b]!); }
        }
        ctx.stroke();
      }

      ctx.fillStyle = dotColor;
      ctx.beginPath();
      dots.forEach((d, i) => {
        if (i === hovered) return; // drawn on top below
        const r = d.r * ps[i]!;
        ctx.moveTo(px[i]! + r, py[i]!);
        ctx.arc(px[i]!, py[i]!, r, 0, Math.PI * 2);
      });
      ctx.fill();

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
      for (const g of groups) {
        const x1 = g.x * cy - g.z * sy, z1 = g.x * sy + g.z * cy;
        const y2 = g.y * cx - z1 * sx, z2 = g.y * sx + z1 * cx;
        const s = (f / Math.max(60, f + z2)) * base;
        label(g.name, w / 2 + panX + x1 * s, h / 2 + panY + y2 * s - g.radius * s - 7);
      }

      // The hovered item: a coral dot with its name in a tooltip just below, and its linked items in amber.
      if (hovered >= 0) {
        ctx.fillStyle = dotLinked;
        ctx.beginPath();
        for (const i of neighbours[hovered]!) {
          const nr = Math.max(4, dots[i]!.r * ps[i]! * 1.5);
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

      held = hovered >= 0;
      setHover(hovered >= 0 ? dots[hovered]! : null);
      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);

    const track = (e: PointerEvent) => {
      const r = canvas.getBoundingClientRect(); mx = e.clientX - r.left; my = e.clientY - r.top;
    };
    const down = (e: PointerEvent) => {
      track(e);
      dragging = e.button === 2 ? "pan" : "rotate";
      lx = e.clientX; ly = e.clientY; canvas.setPointerCapture(e.pointerId);
      canvas.style.cursor = "grabbing";
    };
    const move = (e: PointerEvent) => {
      track(e);
      if (!dragging) return;
      const dx = e.clientX - lx, dy = e.clientY - ly; lx = e.clientX; ly = e.clientY;
      if (dragging === "rotate") { ry += dx * 0.005; rx += dy * 0.005; } else { panX += dx; panY += dy; }
    };
    const up = () => { dragging = null; canvas.style.cursor = "grab"; };
    const leave = () => { mx = my = -1e4; };
    const wheel = (e: WheelEvent) => {
      e.preventDefault();
      zoom = Math.min(4, Math.max(0.4, zoom * (e.deltaY > 0 ? 0.92 : 1.08)));
    };
    const ctxMenu = (e: Event) => e.preventDefault();

    const listeners = new AbortController();
    const { signal } = listeners;
    window.addEventListener("resize", resize, { signal });
    canvas.addEventListener("pointerdown", down, { signal });
    canvas.addEventListener("pointermove", move, { signal });
    canvas.addEventListener("pointerup", up, { signal });
    canvas.addEventListener("pointercancel", up, { signal });
    canvas.addEventListener("pointerleave", leave, { signal });
    canvas.addEventListener("wheel", wheel, { passive: false, signal });
    canvas.addEventListener("contextmenu", ctxMenu, { signal });
    return () => {
      cancelAnimationFrame(raf);
      listeners.abort();
    };
  }, [entities, catalogEdges]);

  return (
    <div className="kg">
      <canvas ref={ref} className="kg-canvas" role="img" aria-label={`Graph of ${entities.length} catalog items and ${catalogEdges.length} links.`} />
      <div className="kg-card">
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
            {ILLUSTRATIVE_DOTS && <p>Small unnamed dots are illustrative only.</p>}
          </>
        )}
      </div>
    </div>
  );
}
