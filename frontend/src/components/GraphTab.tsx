import { useMemo, useState } from "react";
import { TYPES } from "../data/estate";
import type { Edge, EntityType } from "../data/types";
import { byId, neighborhood, graphEdges, type Direction } from "../lib/estate";
import { SourceEvidence } from "./SourceEvidence";
import { CODE_KEYS } from "./DetailsTab";
import { GraphCanvas, type GLink } from "./GraphCanvas";
import { Meter, Pill, SeverityPill, TypeChip } from "./ui";

interface Props {
  focus: string;
  selected: string | null;
  depth: number;
  hidden: Set<EntityType>;
  onSelect: (id: string | null) => void;
  onFocus: (id: string) => void;
  onOpenDetails: (id: string) => void;
  onDepth: (d: number) => void;
  onToggleType: (t: EntityType, visible: boolean) => void;
}

const DEPTHS: [number, string][] = [
  [1, "1 hop"],
  [2, "2 hops"],
  [3, "3 hops"],
];
const EMPTY = new Set<EntityType>();

function EdgeKey({ cls, label }: { cls: string; label: string }) {
  return (
    <div>
      <svg width="34" height="8" aria-hidden="true">
        <line x1="1" y1="4" x2="33" y2="4" className={`link ${cls}`} />
      </svg>
      {label}
    </div>
  );
}

export function GraphTab(p: Props) {
  const [links, setLinks] = useState<GLink[]>([]);
  const [direction, setDirection] = useState<Direction>("all");
  const [candidates, setCandidates] = useState(false);
  const [selectedEdge, setSelectedEdge] = useState<Edge | null>(null);
  const eligible = graphEdges(direction, candidates);
  const full = neighborhood(p.focus, p.depth, p.hidden, direction, candidates, Infinity);

  const visible = useMemo(
    () => neighborhood(p.focus, p.depth, p.hidden, direction, candidates),
    [p.focus, p.depth, p.hidden, direction, candidates],
  );
  // Counts ignore type filters so a hidden type still shows how many would return.
  const counts = useMemo(() => {
    const c: Partial<Record<EntityType, number>> = {};
    neighborhood(p.focus, p.depth, EMPTY, direction, candidates, Infinity).forEach((_, id) => {
      const t = byId[id].type;
      c[t] = (c[t] ?? 0) + 1;
    });
    return c;
  }, [p.focus, p.depth, direction, candidates]);
  const shownEdges = eligible.filter(
    (l) => visible.has(l.s) && visible.has(l.t),
  ).length;

  const id = p.selected ?? p.focus;
  const e = byId[id];
  const inView = links.filter(
    (l) => l.source.id === id || l.target.id === id,
  ).length;

  return (
    <div className="graph-layout">
      <aside className="graph-filters panel" aria-label="Graph filters">
        <div className="fgroup">
          <h3>Relationship lens</h3>
          <select aria-label="Relationship direction" value={direction} onChange={ev => { setDirection(ev.target.value as Direction); setSelectedEdge(null); }}>
            <option value="all">All relationships</option>
            <option value="upstream">Upstream lineage</option>
            <option value="downstream">Downstream impact</option>
          </select>
          <p className="small muted">Impact follows supplied directed lineage only.</p>
          <label className="candidate-toggle"><input type="checkbox" checked={candidates} onChange={ev => setCandidates(ev.target.checked)} />Migration candidates</label>
          <h3>Depth</h3>
          <div className="seg" role="group" aria-label="Graph depth">
            {DEPTHS.map(([v, label]) => (
              <button
                key={v}
                type="button"
                aria-pressed={p.depth === v}
                onClick={() => p.onDepth(v)}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        <div className="fgroup">
          <h3>Entity types</h3>
          {(Object.keys(TYPES) as EntityType[]).map((k) => (
            <label
              key={k}
              className={`type-toggle t-${k}${counts[k] ? "" : " zero"}`}
            >
              <input
                type="checkbox"
                id={`type-${k}`}
                checked={!p.hidden.has(k)}
                onChange={(ev) => p.onToggleType(k, ev.target.checked)}
              />
              <span className="tdot" />
              {TYPES[k].plural}
              <span className="n">{counts[k] ?? 0}</span>
            </label>
          ))}
        </div>
        <div className="fgroup">
          <h3>Relationships</h3>
          <div className="edge-key">
            <EdgeKey cls="k-accent" label="Supplied lineage" />
            <EdgeKey cls="k-base basis-join" label="ID joins: ownership, scope, KPIs" />
            <EdgeKey cls="k-warn basis-candidate" label="Migration candidate (unapproved)" />
          </div>
        </div>
        <div className="fgroup">
          <h3>Node ring</h3>
          <div className="edge-key">
            <div>
              <Pill status="certified" sm /> solid ring
            </div>
            <div>
              <Pill status="conflict" sm /> dashed ring
            </div>
            <div>
              <Pill status="stale" sm /> <Pill status="orphaned" sm />
            </div>
          </div>
        </div>
        <p className="stats">
          {visible.size} of {full.size} reachable entities · {shownEdges} relationships
          {full.size > visible.size && <span> · Limited to 90 nodes. Narrow depth, types or focus to inspect the rest.</span>}
        </p>
      </aside>

      <GraphCanvas
        direction={direction}
        candidates={candidates}
        onEdgeSelect={setSelectedEdge}
        focus={p.focus}
        depth={p.depth}
        hidden={p.hidden}
        selected={p.selected}
        onSelect={(id) => { setSelectedEdge(null); p.onSelect(id); }}
        onFocus={p.onFocus}
        onLinks={setLinks}
      />

      <aside
        className="graph-inspector panel"
        aria-label="Selected entity"
        aria-live="polite"
      >
        <div className="insp-head">
          <div className="head-kicker">
            <TypeChip type={e.type} />
            <Pill status={e.status} sm />
          </div>
          <h3>{e.name}</h3>
          {e.type !== "person" && <Meter value={e.trust} />}
        </div>
        <p className="empty">{e.summary}</p>
        <SourceEvidence sources={e.sources ?? []} />
        {selectedEdge && <section className="relationship-proof">
          <h3>{byId[selectedEdge.s].name} → {byId[selectedEdge.t].name}</h3>
          <p>{selectedEdge.label ?? selectedEdge.rel}</p>
          <strong>{selectedEdge.basis === "lineage" ? "Supplied lineage" : selectedEdge.basis === "candidate" ? "Unapproved migration candidate" : "Derived from matching record IDs"}</strong>
          <SourceEvidence sources={selectedEdge.sources ?? []} />
        </section>}
        <details className="relationship-list"><summary>Inspect relationship evidence</summary>
          {eligible.filter(x => x.s === id || x.t === id).map((x,i) => <button key={i} onClick={() => setSelectedEdge(x)}>{x.s === id ? "→" : "←"} {byId[x.s === id ? x.t : x.s].name}<small>{x.basis ?? "runtime"} · {x.label ?? x.rel}</small></button>)}
        </details>
        <dl className="insp-props">
          {Object.entries(e.props)
            .slice(0, 4)
            .map(([k, v]) => (
              <div key={k}>
                <dt>{k}</dt>
                <dd className={CODE_KEYS.has(k) ? "mono" : undefined}>{v}</dd>
              </div>
            ))}
        </dl>
        {e.flags.length > 0 && (
          <div className="fgroup">
            <h3>Flags</h3>
            <ul className="insp-flags">
              {e.flags.map((f, i) => (
                <li key={`${f.title}:${i}`} title={f.text}>
                  <SeverityPill sev={f.sev} />
                  {f.title}
                </li>
              ))}
            </ul>
          </div>
        )}
        <p className="stats">
          {inView} relationship{inView === 1 ? "" : "s"} in this view
        </p>
        <div className="insp-actions">
          {id !== p.focus && (
            <button type="button" className="btn" onClick={() => p.onFocus(id)}>
              Focus graph here
            </button>
          )}
          <button
            type="button"
            className="btn-ghost"
            onClick={() => p.onOpenDetails(id)}
          >
            Open details
          </button>
        </div>
      </aside>
    </div>
  );
}
