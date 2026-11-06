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

const DEPTHS: [number, string][] = [[1, "1 hop"], [2, "2 hops"], [99, "All"]];
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
    <div className="graph-layout">
      <aside className="graph-filters panel" aria-label="Graph filters">
        <div className="fgroup">
          <h3>Depth</h3>
          <div className="seg" role="group" aria-label="Graph depth">
            {DEPTHS.map(([v, label]) => (
              <button key={v} type="button" aria-pressed={p.depth === v} onClick={() => p.onDepth(v)}>{label}</button>
            ))}
          </div>
        </div>
        <div className="fgroup">
          <h3>Entity types</h3>
          {(Object.keys(TYPES) as EntityType[]).filter((k) => ENTITIES.some((e) => e.type === k)).map((k) => (
            <label key={k} className={`type-toggle t-${k}${counts[k] ? "" : " zero"}`}>
              <input type="checkbox" id={`type-${k}`} checked={!p.hidden.has(k)} onChange={(ev) => p.onToggleType(k, ev.target.checked)} />
              <span className="tdot" />
              {TYPES[k].plural}
              <span className="n">{counts[k] ?? 0}</span>
            </label>
          ))}
        </div>
        <div className="fgroup">
          <h3>Relationships</h3>
          <div className="edge-key">
            <EdgeKey cls="k-bad" label="Metric conflict" />
            <EdgeKey cls="k-warn" label="Duplicate or overlap" />
            <EdgeKey cls="k-accent" label="Equivalent logic" />
            <EdgeKey cls="k-base" label="Lineage, usage, ownership, joins" />
          </div>
        </div>
        <div className="fgroup">
          <h3>Node ring</h3>
          <div className="edge-key">
            <div><Pill status="certified" sm /> solid ring</div>
            <div><Pill status="conflict" sm /> dashed ring</div>
            <div><Pill status="stale" sm /> <Pill status="orphaned" sm /></div>
          </div>
        </div>
        <p className="stats">{visible.size} entities · {shownEdges} relationships</p>
      </aside>

      <GraphCanvas
        focus={p.focus}
        depth={p.depth}
        hidden={p.hidden}
        selected={p.selected}
        onSelect={p.onSelect}
        onFocus={p.onFocus}
        onLinks={setLinks}
      />

      <aside className="graph-inspector panel" aria-label="Selected entity" aria-live="polite">
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
            <h3>Flags</h3>
            <ul className="insp-flags">
              {e.flags.map((f, i) => <li key={`${i}-${f.title}`}><SeverityPill sev={f.sev} />{f.title}</li>)}
            </ul>
          </div>
        )}
        <p className="stats">{inView} relationship{inView === 1 ? "" : "s"} in this view</p>
        <div className="insp-actions">
          {id !== p.focus && <button type="button" className="btn" onClick={() => p.onFocus(id)}>Focus graph here</button>}
          <button type="button" className="btn-ghost" onClick={() => p.onOpenDetails(id)}>Open details</button>
        </div>
      </aside>
    </div>
  );
}
