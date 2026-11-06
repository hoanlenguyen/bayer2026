import { Icon } from "./Icon";

export type Page = "ask" | "explorer" | "cala-graph";

export function Sidebar({ page }: { page: Page }) {
  return (
    <header className="sidebar">
      <a className="brand" href="/#ask">
        <span className="brand-mark" aria-hidden="true" />
        <span className="brand-name">Analytics Manager</span>
      </a>
      <nav className="app-nav" aria-label="Main">
        <a href="/#ask" aria-current={page === "ask" ? "page" : undefined}><Icon name="ask" />Ask</a>
        <a href="/#explorer" aria-current={page === "explorer" ? "page" : undefined}><Icon name="estate" />Estate Explorer</a>
      </nav>
      <p className="sample-note" title="All data in this app is fictional sample data">
        <span className="sample-tag">Sample data</span>
        <span className="sample-text">Synthetic pharma data.</span>
      </p>
    </header>
  );
}
