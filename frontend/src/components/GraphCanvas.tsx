import { useEffect, useRef } from "react";
import * as d3 from "d3";
import { REL, STATUS, TYPES } from "../data/estate";
import type { Edge, Entity, EntityType, RelationType } from "../data/types";
import { byId, glyphOf, neighborhood, trunc, graphEdges, type Direction } from "../lib/estate";

type Kind = "base" | "bad" | "warn" | "accent";

export interface GNode extends d3.SimulationNodeDatum {
  id: string;
  e: Entity;
  r: number;
}

export interface GLink extends d3.SimulationLinkDatum<GNode> {
  source: GNode;
  target: GNode;
  rel: RelationType;
  kind: Kind;
  edge: Edge;
}

interface Props {
  revision?: number;
  direction?: Direction;
  candidates?: boolean;
  onEdgeSelect?: (edge: Edge) => void;
  focus: string;
  depth: number;
  hidden: Set<EntityType>;
  selected: string | null;
  onSelect: (id: string | null) => void;
  onFocus: (id: string) => void;
  /** Called after each rebuild with the links currently drawn. */
  onLinks?: (links: GLink[]) => void;
}

const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/**
 * Force-directed relationship graph. React owns the container and props;
 * d3 owns everything inside the <svg> (layout, zoom, drag, highlighting).
 */
export function GraphCanvas({ revision, direction = "all", candidates = false, onEdgeSelect, focus, depth, hidden, selected, onSelect, onFocus, onLinks }: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const posCache = useRef(new Map<string, { x: number; y: number }>());
  const lastFocus = useRef<string | null>(null);
  const zoomRef = useRef<d3.ZoomBehavior<SVGSVGElement, unknown> | null>(null);
  const graphRef = useRef<{ nodes: GNode[]; links: GLink[]; sim: d3.Simulation<GNode, GLink> | null }>({ nodes: [], links: [], sim: null });
  // Keep callbacks fresh without rebuilding the graph when parents re-render.
  const cb = useRef({ onSelect, onFocus, onLinks, onEdgeSelect });
  cb.current = { onSelect, onFocus, onLinks, onEdgeSelect };

  const fit = (animate: boolean) => {
    const wrap = wrapRef.current, svg = svgRef.current, zoom = zoomRef.current;
    const { nodes } = graphRef.current;
    if (!wrap || !svg || !zoom || !nodes.length) return;
    const W = wrap.clientWidth, H = wrap.clientHeight;
    if (!W || !H) return;
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    nodes.forEach((n) => {
      x0 = Math.min(x0, n.x! - n.r - 70); x1 = Math.max(x1, n.x! + n.r + 70);
      y0 = Math.min(y0, n.y! - n.r - 20); y1 = Math.max(y1, n.y! + n.r + 34);
    });
    const k = Math.min(1.6, 0.92 * Math.min(W / (x1 - x0), H / (y1 - y0)));
    const t = d3.zoomIdentity.translate(W / 2 - (k * (x0 + x1)) / 2, H / 2 - (k * (y0 + y1)) / 2).scale(k);
    const sel = d3.select(svg);
    if (animate && !reducedMotion()) sel.transition().duration(350).call(zoom.transform, t);
    else sel.call(zoom.transform, t);
  };

  // One-time setup: defs, layers, zoom.
  useEffect(() => {
    const svg = d3.select(svgRef.current!);
    const defs = svg.append("defs");
    (["base", "bad", "warn", "accent"] as Kind[]).forEach((k) => {
      defs.append("marker").attr("id", "arrow-" + k).attr("viewBox", "0 -5 10 10").attr("refX", 9).attr("refY", 0)
        .attr("markerWidth", 6).attr("markerHeight", 6).attr("orient", "auto")
        .append("path").attr("d", "M0,-4L10,0L0,4Z").attr("class", "arrow-" + k);
    });
    const root = svg.append("g").attr("class", "root");
    root.append("g").attr("class", "links");
    root.append("g").attr("class", "link-labels");
    root.append("g").attr("class", "nodes");
    const zoom = d3.zoom<SVGSVGElement, unknown>().scaleExtent([0.25, 3]).on("zoom", (ev) => root.attr("transform", ev.transform));
    svg.call(zoom).on("dblclick.zoom", null);
    svg.on("click", (ev) => { if (ev.target === svgRef.current) cb.current.onSelect(null); });
    zoomRef.current = zoom;

    const onResize = () => fit(false);
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      graphRef.current.sim?.stop();
      svg.selectAll("*").remove();
      svg.on(".zoom", null).on("click", null);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Rebuild whenever the visible neighbourhood changes.
  useEffect(() => {
    const wrap = wrapRef.current!, W = wrap.clientWidth, H = wrap.clientHeight;
    const root = d3.select(svgRef.current!).select<SVGGElement>("g.root");
    const reduced = reducedMotion();
    let seed = 7;
    const rand = () => (seed = (seed * 16807) % 2147483647) / 2147483647;

    // Keep positions when only depth or filters change; lay out afresh on a new focus.
    if (lastFocus.current !== focus) posCache.current.clear();
    lastFocus.current = focus;

    const dist = neighborhood(focus, depth, hidden, direction, candidates);
    const nodes: GNode[] = [...dist.keys()].map((id) => {
      const e = byId[id], p = posCache.current.get(id);
      return { id, e, r: id === focus ? 22 : TYPES[e.type].r,
        x: p ? p.x : W / 2 + (rand() - 0.5) * 160, y: p ? p.y : H / 2 + (rand() - 0.5) * 160 };
    });
    const nodeById = new Map(nodes.map((n) => [n.id, n]));
    const links: GLink[] = graphEdges(direction, candidates).filter((l) => dist.has(l.s) && dist.has(l.t)).map((l) => ({
      source: nodeById.get(l.s)!, target: nodeById.get(l.t)!, rel: l.rel, kind: l.basis === "lineage" ? "accent" : REL[l.rel].kind ?? "base", edge: l,
    }));

    const linkSel = root.select(".links").selectAll<SVGLineElement, GLink>("line").data(links).join("line")
      .attr("class", (d) => "link k-" + d.kind + " basis-" + (d.edge.basis ?? "runtime")).attr("marker-end", (d) => `url(#arrow-${d.kind})`)
      .style("cursor", "pointer").on("click", (ev, d) => { ev.stopPropagation(); cb.current.onEdgeSelect?.(d.edge); });
    linkSel.selectAll("title").remove();
    linkSel.append("title").text(d => `${d.edge.label ?? d.rel} · ${d.edge.basis ?? "runtime"}`);
    const labelSel = root.select(".link-labels").selectAll<SVGTextElement, GLink>("text").data(links).join("text")
      .attr("class", (d) => `link-label k-${d.kind}${d.kind !== "base" ? " always" : ""}`)
      .text((d) => REL[d.rel].out.toLowerCase());
    const nodeSel = root.select(".nodes").selectAll<SVGGElement, GNode>("g.node").data(nodes, (d) => d.id).join((enter) => {
      const g = enter.append("g");
      g.append("circle").attr("class", "halo");
      g.append("circle").attr("class", "ring");
      g.append("circle").attr("class", "dot");
      g.append("text").attr("class", "glyph");
      g.append("text").attr("class", "label");
      return g;
    });
    nodeSel
      .attr("class", (d) => `node t-${d.e.type} s-${d.e.status}${d.id === focus ? " is-focus" : ""}`)
      .attr("tabindex", 0).attr("role", "button")
      .attr("aria-label", (d) => `${TYPES[d.e.type].label}: ${d.e.name}, ${STATUS[d.e.status].label}`);
    nodeSel.select(".halo").attr("r", (d) => d.r + 14);
    nodeSel.select(".ring").attr("r", (d) => d.r + 4);
    nodeSel.select(".dot").attr("r", (d) => d.r);
    nodeSel.select(".glyph").text((d) => glyphOf(d.e));
    nodeSel.select(".label").attr("y", (d) => d.r + 17).text((d) => trunc(d.e.name, 26));

    const ticked = () => {
      linkSel.each(function (d) {
        const dx = d.target.x! - d.source.x!, dy = d.target.y! - d.source.y!, len = Math.hypot(dx, dy) || 1;
        const ux = dx / len, uy = dy / len, sr = d.source.r + 5, tr = d.target.r + 7;
        this.setAttribute("x1", String(d.source.x! + ux * sr)); this.setAttribute("y1", String(d.source.y! + uy * sr));
        this.setAttribute("x2", String(d.target.x! - ux * tr)); this.setAttribute("y2", String(d.target.y! - uy * tr));
      });
      labelSel.attr("x", (d) => (d.source.x! + d.target.x!) / 2).attr("y", (d) => (d.source.y! + d.target.y!) / 2 - 5);
      nodeSel.attr("transform", (d) => `translate(${d.x},${d.y})`);
      nodes.forEach((n) => posCache.current.set(n.id, { x: n.x!, y: n.y! }));
    };

    graphRef.current.sim?.stop();
    const sim = d3.forceSimulation<GNode, GLink>(nodes)
      .force("link", d3.forceLink<GNode, GLink>(links).id((d) => d.id)
        .distance((l) => (l.source.id === focus || l.target.id === focus ? 150 : 115)).strength(0.4))
      .force("charge", d3.forceManyBody().strength(-760))
      .force("center", d3.forceCenter(W / 2, H / 2))
      .force("collide", d3.forceCollide<GNode>((d) => d.r + 42))
      .force("x", d3.forceX(W / 2).strength(0.04))
      .force("y", d3.forceY(H / 2).strength(0.06))
      .on("tick", ticked)
      .stop();
    graphRef.current = { nodes, links, sim };

    nodeSel
      .on("click", (ev, d) => { ev.stopPropagation(); cb.current.onSelect(d.id); })
      .on("dblclick", (ev, d) => { ev.stopPropagation(); cb.current.onFocus(d.id); })
      .on("keydown", (ev: KeyboardEvent, d) => {
        if (ev.key === "Enter") { ev.preventDefault(); cb.current.onFocus(d.id); }
        else if (ev.key === " ") { ev.preventDefault(); cb.current.onSelect(d.id); }
      })
      .call(d3.drag<SVGGElement, GNode>()
        .on("start", (ev, d) => { if (!ev.active && !reduced) sim.alphaTarget(0.2).restart(); d.fx = d.x; d.fy = d.y; })
        .on("drag", (ev, d) => { d.fx = ev.x; d.fy = ev.y; if (reduced) { d.x = ev.x; d.y = ev.y; ticked(); } })
        .on("end", (ev, d) => { if (!ev.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }));

    for (let i = 0; i < 300; i++) sim.tick();
    ticked();
    fit(false);
    if (!reduced) sim.alpha(0.05).restart();
    cb.current.onLinks?.(links);
    return () => { sim.stop(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focus, depth, hidden, direction, candidates, revision]);

  // Highlight the selected node and its direct neighbours.
  useEffect(() => {
    const root = d3.select(svgRef.current!).select("g.root");
    const { links } = graphRef.current;
    const id = selected;
    const nb = new Set<string>(id ? [id] : []);
    if (id) links.forEach((l) => { if (l.source.id === id) nb.add(l.target.id); if (l.target.id === id) nb.add(l.source.id); });
    const touches = (l: GLink) => l.source.id === id || l.target.id === id;
    root.selectAll<SVGGElement, GNode>("g.node").classed("dim", (d) => !!id && !nb.has(d.id)).classed("selected", (d) => d.id === id);
    root.selectAll<SVGLineElement, GLink>("line.link").classed("dim", (l) => !!id && !touches(l)).classed("hot", (l) => !!id && touches(l));
    root.selectAll<SVGTextElement, GLink>("text.link-label").classed("dim", (l) => !!id && !touches(l)).classed("hot", (l) => !!id && touches(l));
  }, [selected, focus, depth, hidden]);

  const zoomBy = (k: number) => {
    const svg = svgRef.current, zoom = zoomRef.current;
    if (!svg || !zoom) return;
    d3.select(svg).transition().duration(reducedMotion() ? 0 : 200).call(zoom.scaleBy, k);
  };

  return (
    <div className="graph-stage panel">
      <div ref={wrapRef} className="graph-canvas">
        <svg ref={svgRef} role="img" aria-label="Relationship graph of the selected entity" />
      </div>
      <div className="graph-toolbar">
        <button type="button" title="Zoom in" aria-label="Zoom in" onClick={() => zoomBy(1.3)}>+</button>
        <button type="button" title="Zoom out" aria-label="Zoom out" onClick={() => zoomBy(1 / 1.3)}>−</button>
        <button type="button" title="Fit to view" aria-label="Fit graph to view" onClick={() => fit(true)}>⤢</button>
      </div>
      <div className="graph-hint">Click to inspect · Double-click to refocus · Drag to rearrange</div>
    </div>
  );
}
