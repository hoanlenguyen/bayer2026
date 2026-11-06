import type { ReactNode } from "react";
import { EDGES, PROV, TYPES } from "../data/estate";
import type { Entity } from "../data/types";
import { byId, ownerOf, relGroups } from "../lib/estate";
import { Meter, Pill, SeverityPill } from "./ui";

const WIDE_KEYS = new Set(["Formula", "Defined in", "Location"]);
export const CODE_KEYS = new Set(["Formula", "Metric code", "Table"]);

interface Props {
  entity: Entity;
  sent: boolean;
  onFocus: (id: string) => void;
  onSend: (id: string) => void;
  onShowGraph: () => void;
}

function EntityRow({ entity: o, onFocus }: { entity: Entity; onFocus: (id: string) => void }) {
  return (
    <li>
      <button type="button" className={`ent-link t-${o.type}`} onClick={() => onFocus(o.id)}>
        <span className="tdot" />
        <span className="ent-name">{o.name}</span>
        <span className="ent-type">{TYPES[o.type].label}</span>
        <Pill status={o.status} sm />
      </button>
    </li>
  );
}

function governanceRows(e: Entity, onFocus: (id: string) => void): [string, ReactNode][] {
  const owner = ownerOf(e.id);
  const rows: [string, ReactNode][] = [["Status", <Pill status={e.status} />]];
  if (owner) {
    rows.push(["Owner", <>
      <button type="button" className="inline-link" onClick={() => onFocus(owner.id)}>{owner.name}</button>
      {owner.status === "left" && <> <Pill status="left" sm /></>}
    </>]);
  }
  if (e.type !== "person") rows.push(["Trust score", <Meter value={e.trust} />]);
  if (e.type === "metric") {
    const users = EDGES.filter((l) => l.t === e.id && l.rel === "uses").map((l) => byId[l.s]);
    const views = users.reduce((a, d) => a + (d.views ?? 0), 0);
    rows.push(["Used by", `${users.length} dashboard${users.length === 1 ? "" : "s"}`]);
    rows.push(["Views via those", `${views.toLocaleString("en-US")} in 90 days`]);
  }
  if (e.type === "dashboard" && e.views !== undefined) rows.push(["Audience", `${e.views.toLocaleString("en-US")} views in 90 days`]);
  if (e.type === "person") rows.push(["Assets owned", String(EDGES.filter((l) => l.s === e.id && l.rel === "owns").length)]);
  if (e.props["Next review"]) rows.push(["Next review", e.props["Next review"]]);
  return rows;
}

export function DetailsTab({ entity: e, sent, onFocus, onSend, onShowGraph }: Props) {
  const groups = relGroups(e.id);
  const total = groups.reduce((a, g) => a + g.items.length, 0);

  return (
    <div className="details-grid">
      <div className="details-main">
        <article className="card">
          <h2 className="card-title">Summary</h2>
          <p className="summary">{e.summary}</p>
        </article>
        <article className="card">
          <h2 className="card-title">Properties</h2>
          <dl className="props">
            {Object.entries(e.props).map(([k, v]) => (
              <div key={k} className={`prop${WIDE_KEYS.has(k) ? " wide" : ""}`}>
                <dt>{k}</dt>
                <dd className={CODE_KEYS.has(k) ? "mono" : undefined}>{v}</dd>
              </div>
            ))}
          </dl>
        </article>
        <article className="card">
          <div className="card-head">
            <h2 className="card-title">Relationships <span className="count">{total}</span></h2>
            <button type="button" className="btn-ghost" onClick={onShowGraph}>View in graph</button>
          </div>
          {groups.map((g) => (
            <div key={g.label} className="rel-group">
              <h3>{g.label} <span className="count">{g.items.length}</span></h3>
              <ul className="rel-list">
                {g.items.map((o) => <EntityRow key={o.id} entity={o} onFocus={onFocus} />)}
              </ul>
            </div>
          ))}
        </article>
      </div>

      <aside className="details-side">
        <article className="card">
          <h2 className="card-title">Governance</h2>
          <dl className="gov">
            {governanceRows(e, onFocus).map(([k, v]) => (
              <div key={k} className="gov-row"><dt>{k}</dt><dd>{v}</dd></div>
            ))}
          </dl>
          {e.action && (
            <div className="action-box">
              <span className="k">Recommended action</span>
              <p>{e.action}</p>
              {sent ? (
                <span className="done">Added to the action tracker. <a href="#actions">View actions</a></span>
              ) : (
                <div><button type="button" className="btn" onClick={() => onSend(e.id)}>Add to action tracker</button></div>
              )}
            </div>
          )}
        </article>
        <article className="card">
          <h2 className="card-title">AI review flags <span className="count">{e.flags.length}</span></h2>
          {e.flags.length ? (
            <ul className="flags">
              {e.flags.map((f, i) => (
                <li key={`${i}-${f.title}`} className="flag">
                  <div className="flag-top"><SeverityPill sev={f.sev} /><strong>{f.title}</strong></div>
                  <p>{f.text}</p>
                </li>
              ))}
            </ul>
          ) : (
            <p className="empty">No open issues. The last review found nothing to flag.</p>
          )}
        </article>
        <article className="card">
          <h2 className="card-title">Provenance</h2>
          <ul className="prov">
            {PROV[e.type](e).map(([s, d, t]) => (
              <li key={s}><span className="src">{s}</span><span className="meta">{d} · {t}</span></li>
            ))}
          </ul>
        </article>
      </aside>
    </div>
  );
}
