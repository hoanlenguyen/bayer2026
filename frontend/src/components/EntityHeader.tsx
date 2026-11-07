import { useState, type ReactNode } from "react";
import { TYPES } from "../data/estate";
import type { Entity } from "../data/types";
import { Pill, TypeChip } from "./ui";

interface Props {
  entity: Entity;
  homeId: string;
  onFocus: (id: string) => void;
  search: ReactNode;
}

export function EntityHeader({ entity: e, homeId, onFocus, search }: Props) {
  const [copyLabel, setCopyLabel] = useState("Copy ID");

  const copy = () => {
    navigator.clipboard?.writeText(e.uid).then(
      () => { setCopyLabel("Copied"); setTimeout(() => setCopyLabel("Copy ID"), 1400); },
      () => setCopyLabel("Copy failed"),
    );
  };

  return (
    <>
      <div className="pane-head page-bar">
        <nav className="breadcrumb" aria-label="Breadcrumb">
          <button type="button" onClick={() => onFocus(homeId)}>Estate</button>
          <span aria-hidden="true">/</span>
          <span>{TYPES[e.type].plural}</span>
          <span aria-hidden="true">/</span>
          <span aria-current="page">{e.name}</span>
        </nav>
        {search}
      </div>
      <section className="entity-head">
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
          <span>Updated {e.updated}</span>
        </div>
      </section>
    </>
  );
}
