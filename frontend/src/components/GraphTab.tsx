import { useMemo, useState } from "react";
import { EDGES, ENTITIES, TYPES } from "../data/estate";
import type { EntityType } from "../data/types";
import { byId, neighborhood } from "../lib/estate";
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

const DEPTHS: [number, string][] = [[1, "Direct"], [2, "2 steps"], [99, "All"]];
const EMPTY = new Set<EntityType>();

function EdgeKey({ cls, label }: { cls: string; label: string }) {
  return (
    <div>
      <svg width="34" height="8" aria-hidden="true"><line x1="1" y1="4" x2="33" y2="4" className={`link ${cls}`} /></svg>
      {label}
    </div>
  );
}

export function GraphTab(p: Props) {
  const [links, setLinks] = useState<GLink[]>([]);

  const visible = useMemo(() => neighborhood(p.focus, p.depth, p.hidden), [p.focus, p.depth, p.hidden]);
  // Counts ignore type filters so a hidden type still shows how many would return.
  const counts = useMemo(() => {
    const c: Partial<Record<EntityType, number>> = {};
    neighborhood(p.focus, p.depth, EMPTY).forEach((_, id) => { const t = byId[id].type; c[t] = (c[t] ?? 0) + 1; });
    return c;
  }, [p.focus, p.depth]);
  const shownEdges = EDGES.filter((l) => visible.has(l.s) && visible.has(l.t)).length;

  const id = p.selected ?? p.focus;
  const e = byId[id];
  const inView = links.filter((l) => l.source.id === id || l.target.id === id).length;

  return (
    <div className="graph-wrap">
      <div className="graph-controls" aria-label="Graph filters">
        <div className="seg" role="group" aria-label="How far to follow connections">
          {DEPTHS.map(([v, label]) => (
            <button key={v} type="button" aria-pressed={p.depth === v} onClick={() => p.onDepth(v)}>{label}</button>
          ))}
        </div>
        <div className="type-chips" role="group" aria-label="Show or hide item types">
          {(Object.keys(TYPES) as EntityType[]).filter((k) => ENTITIES.some((en) => en.type === k)).map((k) => {
            const on = !p.hidden.has(k);
            return (
              <button key={k} type="button" className={`type-chip-btn t-${k}`} aria-pressed={on} disabled={!counts[k]} onClick={() => p.onToggleType(k, !on)}>
                <span className="tdot" />
                {TYPES[k].plural}
                <span className="n">{counts[k] ?? 0}</span>
              </button>
            );
          })}
        </div>
        <p className="stats">{visible.size} items · {shownEdges} links</p>
      </div>

      <div className="graph-layout">
        <div className="graph-main">
          <GraphCanvas
            focus={p.focus}
            depth={p.depth}
            hidden={p.hidden}
            selected={p.selected}
            onSelect={p.onSelect}
            onFocus={p.onFocus}
            onLinks={setLinks}
          />
          <div className="graph-key" aria-label="Graph key">
            <EdgeKey cls="k-bad" label="Metric conflict" />
            <EdgeKey cls="k-warn" label="Duplicate or overlap" />
            <EdgeKey cls="k-accent" label="Equivalent logic" />
            <EdgeKey cls="k-base" label="Lineage, usage, ownership, joins" />
          </div>
        </div>

        <aside className="graph-inspector panel" aria-label="Selected item" aria-live="polite">
          <div className="insp-head">
            <div className="head-kicker"><TypeChip type={e.type} /><Pill status={e.status} sm /></div>
            <h3>{e.name}</h3>
            {e.type !== "person" && <Meter value={e.trust} />}
          </div>
          <p className="empty">{e.summary}</p>
          <dl className="insp-props">
            {Object.entries(e.props).slice(0, 4).map(([k, v]) => (
              <div key={k}><dt>{k}</dt><dd className={CODE_KEYS.has(k) ? "mono" : undefined}>{v}</dd></div>
            ))}
          </dl>
          {e.flags.length > 0 && (
            <div className="fgroup">
              <h4>Flags</h4>
              <ul className="insp-flags">
                {e.flags.map((f, i) => <li key={`${i}-${f.title}`}><SeverityPill sev={f.sev} />{f.title}</li>)}
              </ul>
            </div>
          )}
          <p className="stats">{inView} link{inView === 1 ? "" : "s"} in this view</p>
          <div className="insp-actions">
            {id !== p.focus && <button type="button" className="btn" onClick={() => p.onFocus(id)}>Focus graph here</button>}
            <button type="button" className="btn-outline" onClick={() => p.onOpenDetails(id)}>Open details</button>
          </div>
        </aside>
      </div>
    </div>
  );
}
