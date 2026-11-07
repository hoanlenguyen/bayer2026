import type { MouseEvent } from "react";
import { Icon } from "./Icon";

export type Page = "ask" | "explorer" | "cala-graph";

/** Moves between / and /cala-graph without reloading, so the sidebar stays on screen and nothing redraws. */
function navigate(e: MouseEvent<HTMLAnchorElement>) {
  if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return; // let the browser open a new tab or window
  const to = new URL(e.currentTarget.href);
  if (to.pathname === window.location.pathname) return; // only the hash changes: already no reload
  e.preventDefault();
  history.pushState(null, "", to.pathname + to.hash);
  window.scrollTo(0, 0);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

export function Sidebar({ page }: { page: Page }) {
  return (
    <header className="sidebar">
      <a className="brand" href="/#ask" onClick={navigate}>
        <span className="brand-mark" aria-hidden="true" />
        <span className="brand-name">Analytics Manager</span>
      </a>
      <nav className="app-nav" aria-label="Main">
        <a href="/#ask" onClick={navigate} aria-current={page === "ask" ? "page" : undefined}><Icon name="ask" />Ask</a>
        <a href="/#explorer" onClick={navigate} aria-label="Estate Explorer" aria-current={page === "explorer" ? "page" : undefined}><Icon name="estate" /><span><span className="nav-extra">Estate </span>Explorer</span></a>
        <a href="/cala-graph" onClick={navigate} aria-label="Knowledge Graph" aria-current={page === "cala-graph" ? "page" : undefined}><Icon name="graph" /><span><span className="nav-extra">Knowledge </span>Graph</span></a>
      </nav>
      <p className="sample-note" title="All data in this app is fictional sample data">
        <span className="sample-tag">Sample data</span>
        <span className="sample-text">Synthetic pharma data.</span>
      </p>
    </header>
  );
}
