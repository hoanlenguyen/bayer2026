import { useState } from "react";
import { TYPES } from "../data/estate";
import type { Entity } from "../data/types";
import { ownerOf, relationCount, toneOf } from "../lib/estate";
import { Pill, TypeChip } from "./ui";

interface Props {
  entity: Entity;
  homeId: string;
  onFocus: (id: string) => void;
}

export function EntityHeader({ entity: e, homeId, onFocus }: Props) {
  const owner = ownerOf(e.id);
  const [copyLabel, setCopyLabel] = useState("Copy ID");
  const openFlags = e.flags.filter((f) => f.sev !== "info").length;
  const flagColor = e.flags.some((f) => f.sev === "bad") ? "bad" : openFlags ? "warn" : "fg";

  const copy = () => {
    navigator.clipboard?.writeText(e.uid).then(
      () => { setCopyLabel("Copied"); setTimeout(() => setCopyLabel("Copy ID"), 1400); },
      () => setCopyLabel("Copy failed"),
    );
  };

  return (
    <>
      <nav className="breadcrumb" aria-label="Breadcrumb">
        <button type="button" onClick={() => onFocus(homeId)}>Estate</button>
        <span aria-hidden="true">/</span>
        <span>{TYPES[e.type].plural}</span>
        <span aria-hidden="true">/</span>
        <span aria-current="page">{e.name}</span>
      </nav>
      <section className="entity-head">
        <div className="head-main">
          <div className="head-kicker">
            <TypeChip type={e.type} />
            <Pill status={e.status} />
          </div>
          <h1>{e.name}</h1>
          <div className="head-meta">
            <span className="uid">
              <code>{e.uid}</code>
              <button type="button" className="copy" onClick={copy}>{copyLabel}</button>
            </span>
            {owner && (
              <span>
                Owner{" "}
                <button type="button" className="inline-link" onClick={() => onFocus(owner.id)}>{owner.name}</button>
              </span>
            )}
            <span>Updated {e.updated}</span>
          </div>
        </div>
        <div className="head-stats">
          <div className="head-stat">
            <span className="k">Trust</span>
            <span className="v" style={{ color: `var(--${toneOf(e.trust)})` }}>{e.trust.toFixed(2)}</span>
          </div>
          <div className="head-stat">
            <span className="k">Relations</span>
            <span className="v">{relationCount(e.id)}</span>
          </div>
          <div className="head-stat">
            <span className="k">Open flags</span>
            <span className="v" style={{ color: `var(--${flagColor})` }}>{openFlags}</span>
          </div>
        </div>
      </section>
    </>
  );
}
