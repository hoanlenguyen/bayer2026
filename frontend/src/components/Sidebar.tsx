import { useEffect, useState } from "react";
import { openConversation, removeConversation, useAnswerInProgress, useConversations, useCurrentConversation } from "../lib/conversations";
import { navigate } from "../lib/navigation";
import { Icon } from "./Icon";

export type Page = "ask" | "explorer" | "cala-graph" | "simulator" | "briefings";

function HistoryList({ page }: { page: Page }) {
  const conversations = useConversations();
  const current = useCurrentConversation();
  const answering = useAnswerInProgress();
  const [confirming, setConfirming] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [failed, setFailed] = useState(false);

  const open = (id: string) => {
    openConversation(id);
    if (page !== "ask") {
      history.pushState(null, "", "/#ask");
      window.dispatchEvent(new PopStateEvent("popstate"));
    }
  };
  const ask = (id: string) => { setConfirming(id); setFailed(false); };
  const remove = async (id: string) => {
    setDeleting(true);
    setFailed(false);
    try {
      await removeConversation(id);
      setConfirming(null);
    } catch {
      setFailed(true); // the chat stays in the list, so nothing looks deleted that isn't
    } finally {
      setDeleting(false);
    }
  };

  return (
    <section className="side-history" aria-labelledby="side-history-title">
      <h2 id="side-history-title">History</h2>
      {conversations.length > 0 ? (
        <ul>
          {conversations.map((c) => {
            const title = c.title || "Untitled conversation";
            const isCurrent = c._id === current;
            if (confirming === c._id) {
              return (
                <li key={c._id}>
                  <div className="side-history-confirm" role="group" aria-label={`Delete ${title}`}
                    onKeyDown={(e) => { if (e.key === "Escape") { e.stopPropagation(); setConfirming(null); } }}>
                    <p>{failed ? "Could not delete it. Try again?" : "Delete this chat for good?"}</p>
                    <div>
                      <button type="button" className="side-history-danger" autoFocus disabled={deleting} onClick={() => void remove(c._id)}>Delete</button>
                      <button type="button" disabled={deleting} onClick={() => setConfirming(null)}>Cancel</button>
                    </div>
                  </div>
                </li>
              );
            }
            return (
              <li key={c._id}>
                <button type="button" className="side-history-open" title={title} aria-current={isCurrent && page === "ask" ? "true" : undefined} onClick={() => open(c._id)}>
                  <span className="side-history-text">{title}</span>
                </button>
                {!(isCurrent && answering) && (
                  <button type="button" className="side-history-delete" aria-label={`Delete ${title}`} title="Delete this chat" onClick={() => ask(c._id)}>
                    <Icon name="trash" size={14} />
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      ) : (
        <p>Your conversations will show here.</p>
      )}
    </section>
  );
}

const COLLAPSED_KEY = "am.sidebar.collapsed";

function readCollapsed() {
  try { return localStorage.getItem(COLLAPSED_KEY) === "1"; } catch { return false; }
}

export function Sidebar({ page }: { page: Page }) {
  const [collapsed, setCollapsed] = useState(readCollapsed);

  useEffect(() => {
    try { localStorage.setItem(COLLAPSED_KEY, collapsed ? "1" : "0"); } catch { /* preference only lasts this visit */ }
    window.dispatchEvent(new Event("resize")); // the graphs size themselves on this, and the content area just changed width
  }, [collapsed]);

  const tip = (label: string) => (collapsed ? label : undefined);
  const toggleLabel = collapsed ? "Expand sidebar" : "Collapse sidebar";

  return (
    <header className={`sidebar${collapsed ? " collapsed" : ""}`}>
      <div className="sidebar-head">
        <a className="brand" href="/#ask" onClick={navigate} aria-label="Analytics Manager" title={tip("Analytics Manager")}>
          <span className="brand-mark" aria-hidden="true" />
          <span className="brand-name">Analytics Manager</span>
        </a>
        <button type="button" className="sidebar-toggle" aria-label={toggleLabel} aria-expanded={!collapsed} title={toggleLabel} onClick={() => setCollapsed((c) => !c)}>
          <Icon name="panel" />
        </button>
      </div>
      <nav className="app-nav" aria-label="Main">
        <a href="/#ask" onClick={navigate} aria-label="Ask" title={tip("Ask")} aria-current={page === "ask" ? "page" : undefined}><Icon name="ask" /><span>Ask</span></a>
        <a href="/simulator" onClick={navigate} aria-label="Conversation simulation" title={tip("Conversation simulation")} aria-current={page === "simulator" ? "page" : undefined}><Icon name="chat" /><span><span className="nav-extra">Conversation </span>Simulation</span></a>
        <a href="/#explorer" onClick={navigate} aria-label="Estate Explorer" title={tip("Estate Explorer")} aria-current={page === "explorer" ? "page" : undefined}><Icon name="estate" /><span><span className="nav-extra">Estate </span>Explorer</span></a>
        <a href="/cala-graph" onClick={navigate} aria-label="Knowledge Graph" title={tip("Knowledge Graph")} aria-current={page === "cala-graph" ? "page" : undefined}><Icon name="graph" /><span><span className="nav-extra">Knowledge </span>Graph</span></a>
        <a href="/briefings" onClick={navigate} aria-label="Team briefings" title={tip("Team briefings")} aria-current={page === "briefings" ? "page" : undefined}><Icon name="briefings" /><span>Briefings</span></a>
      </nav>
      {!collapsed && <HistoryList page={page} />}
      <p className="sample-note" title="All data in this app is fictional sample data">
        <span className="sample-tag">Sample<span className="sample-extra"> data</span></span>
        <span className="sample-text">Synthetic pharma data.</span>
      </p>
    </header>
  );
}
