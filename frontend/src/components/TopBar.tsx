import { useState } from "react";
import { ENTITIES, TYPES } from "../data/estate";
import type { Entity } from "../data/types";

export type Page = "ask" | "explorer" | "actions";

interface Props {
  page: Page;
  onPick: (id: string) => void;
  activeActions?: number;
}

export function TopBar({ page, onPick, activeActions }: Props) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);

  const q = query.trim().toLowerCase();
  const matches: Entity[] = q
    ? ENTITIES.filter((e) => `${e.name} ${e.uid} ${TYPES[e.type].label}`.toLowerCase().includes(q)).slice(0, 8)
    : [];

  const pick = (id: string) => {
    setQuery("");
    setOpen(false);
    onPick(id);
  };

  return (
    <header className="topbar">
      <div className="topbar-inner">
        <a className="brand" href="#ask">
          <span className="brand-mark" aria-hidden="true" />
          Analytics Manager
        </a>
        <nav className="app-nav" aria-label="Main">
          <a href="#ask" aria-current={page === "ask" ? "page" : undefined}>Ask</a>
          <a href="#explorer" aria-current={page === "explorer" ? "page" : undefined}>Estate Explorer</a>
          <a href="#actions" aria-current={page === "actions" ? "page" : undefined}>
            Actions{activeActions ? <span className="nav-count" aria-label={`${activeActions} active`}>{activeActions}</span> : null}
          </a>
        </nav>
        {page === "explorer" && <div className="search">
          <label htmlFor="search" className="sr-only">Search entities</label>
          <input
            id="search"
            type="search"
            placeholder="Search reports, KPIs, models, owners (e.g. AST-0217, Nubeqa)"
            autoComplete="off"
            aria-controls="search-results"
            aria-expanded={open && !!q}
            value={query}
            onChange={(e) => { setQuery(e.target.value); setActive(0); setOpen(true); }}
            onBlur={() => setOpen(false)}
            onKeyDown={(e) => {
              if (!open || !q) return;
              if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(matches.length - 1, a + 1)); }
              else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(0, a - 1)); }
              else if (e.key === "Enter" && matches[active]) { e.preventDefault(); pick(matches[active].id); }
              else if (e.key === "Escape") setOpen(false);
            }}
          />
          {open && q && (
            <ul id="search-results" className="search-results" role="listbox" onMouseDown={(e) => e.preventDefault()}>
              {matches.length ? (
                matches.map((e, i) => (
                  <li key={e.id} role="option" aria-selected={i === active}>
                    <button type="button" tabIndex={-1} className={`t-${e.type}${i === active ? " active" : ""}`} onClick={() => pick(e.id)}>
                      <span className="tdot" />
                      <span className="ent-name">{e.name}</span>
                      <span className="ent-type">{TYPES[e.type].label}</span>
                    </button>
                  </li>
                ))
              ) : (
                <li className="empty" style={{ padding: 8 }}>No entity matches “{query}”.</li>
              )}
            </ul>
          )}
        </div>}
        <span className="sample-tag" title="All entities on this page are fictional sample data">Sample data</span>
      </div>
    </header>
  );
}
