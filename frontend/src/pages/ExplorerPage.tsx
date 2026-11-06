import { useCallback, useEffect, useState } from "react";
import { DetailsTab } from "../components/DetailsTab";
import { EntityHeader } from "../components/EntityHeader";
import { GraphTab } from "../components/GraphTab";
import type { EntityType } from "../data/types";
import { byId, loadEstate } from "../lib/estate";

type Tab = "details" | "graph";
const tabFromHash = (): Tab => (window.location.hash === "#explorer-graph" ? "graph" : "details");
const hashFor = (t: Tab) => (t === "graph" ? "#explorer-graph" : "#explorer");

type Load = { status: "loading" } | { status: "error"; message: string } | { status: "ready"; home: string };

/** Estate Explorer: entity details and the relationship graph ("molecular view") of the plant catalog. */
export function ExplorerPage({ focusRequest }: { focusRequest: string | null }) {
  const [load, setLoad] = useState<Load>({ status: "loading" });

  // Reload on every visit so reports registered from the Ask page appear.
  useEffect(() => {
    let alive = true;
    loadEstate()
      .then((d) => alive && setLoad({ status: "ready", home: d.focus }))
      .catch((e: unknown) => alive && setLoad({ status: "error", message: e instanceof Error ? e.message : String(e) }));
    return () => { alive = false; };
  }, []);

  if (load.status === "loading") {
    return <main className="page"><p className="muted">Loading the plant catalog…</p></main>;
  }
  if (load.status === "error") {
    return (
      <main className="page">
        <div className="banner" role="status">
          The catalog could not be loaded ({load.message}). Start the backend with <code>uvicorn app.main:app --reload --port 8000</code> in <code>backend/</code>, then reload.
        </div>
      </main>
    );
  }
  const initial = focusRequest && byId[focusRequest] ? focusRequest : load.home;
  return <ExplorerView initialFocus={initial} home={load.home} focusRequest={focusRequest} />;
}

function ExplorerView({ initialFocus, home, focusRequest }: { initialFocus: string; home: string; focusRequest: string | null }) {
  const [focus, setFocusId] = useState(initialFocus);
  const [selected, setSelected] = useState<string | null>(null);
  const [tab, setTabState] = useState<Tab>(tabFromHash);
  const [depth, setDepth] = useState(2);
  const [hidden, setHidden] = useState<Set<EntityType>>(() => new Set());
  const [sent, setSent] = useState<Set<string>>(() => new Set());

  const entity = byId[focus];

  useEffect(() => {
    const onHash = () => setTabState(tabFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    document.title = `${entity.name} · Estate Explorer`;
  }, [entity]);

  const setTab = useCallback((t: Tab) => {
    setTabState(t);
    if (window.location.hash !== hashFor(t)) history.replaceState(null, "", hashFor(t));
  }, []);

  const setFocus = useCallback((id: string, opts: { tab?: Tab; scroll?: boolean } = {}) => {
    setFocusId(id);
    setSelected(null);
    if (opts.tab) setTab(opts.tab);
    if (opts.scroll !== false) window.scrollTo({ top: 0, behavior: "smooth" });
  }, [setTab]);

  useEffect(() => {
    if (focusRequest && byId[focusRequest]) setFocus(focusRequest);
  }, [focusRequest, setFocus]);

  const toggleType = useCallback((t: EntityType, visible: boolean) => {
    setHidden((prev) => {
      const next = new Set(prev);
      if (visible) next.delete(t); else next.add(t);
      return next;
    });
  }, []);

  return (
    <>
      <main className="page">
        <EntityHeader entity={entity} homeId={home} onFocus={(id) => setFocus(id)} />
        <div className="tabs" role="tablist" aria-label="Entity views">
          {(["details", "graph"] as Tab[]).map((t) => (
            <button
              key={t}
              role="tab"
              id={`tab-${t}`}
              aria-controls={`panel-${t}`}
              aria-selected={tab === t}
              tabIndex={tab === t ? 0 : -1}
              onClick={() => setTab(t)}
              onKeyDown={(ev) => {
                if (ev.key === "ArrowRight" || ev.key === "ArrowLeft") {
                  const next: Tab = t === "details" ? "graph" : "details";
                  setTab(next);
                  document.getElementById(`tab-${next}`)?.focus();
                }
              }}
            >
              {t === "details" ? "Details" : "Graph"}
            </button>
          ))}
        </div>

        {tab === "details" ? (
          <section id="panel-details" role="tabpanel" aria-labelledby="tab-details">
            <DetailsTab
              entity={entity}
              sent={sent.has(entity.id)}
              onFocus={(id) => setFocus(id)}
              onSend={(id) => setSent((s) => new Set(s).add(id))}
              onShowGraph={() => setTab("graph")}
            />
          </section>
        ) : (
          <section id="panel-graph" role="tabpanel" aria-labelledby="tab-graph">
            <GraphTab
              focus={focus}
              selected={selected}
              depth={depth}
              hidden={hidden}
              onSelect={setSelected}
              onFocus={(id) => setFocus(id, { scroll: false })}
              onOpenDetails={(id) => setFocus(id, { tab: "details" })}
              onDepth={setDepth}
              onToggleType={toggleType}
            />
          </section>
        )}
      </main>
    </>
  );
}
