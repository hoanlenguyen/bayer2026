import { useEffect, useState } from "react";
import { Sidebar, type Page } from "./components/Sidebar";
import { AskPage } from "./pages/AskPage";
import { CalaGraphPage } from "./pages/CalaGraphPage";
import { ExplorerPage } from "./pages/ExplorerPage";

const pageFromLocation = (): Page => {
  if (window.location.pathname.replace(/\/+$/, "") === "/cala-graph") return "cala-graph";
  return window.location.hash.startsWith("#explorer") ? "explorer" : "ask";
};

export default function App() {
  const [page, setPage] = useState<Page>(pageFromLocation);
  const [focusRequest, setFocusRequest] = useState<string | null>(null);

  useEffect(() => {
    const onNavigate = () => setPage(pageFromLocation());
    // Other pages can ask to open an entity: window.dispatchEvent(new CustomEvent("open-entity", { detail: id }))
    const onOpen = (e: Event) => {
      setFocusRequest((e as CustomEvent<string>).detail);
      // Set the path too: a hash change alone would stay on /cala-graph.
      history.pushState(null, "", "/#explorer");
      onNavigate();
    };
    window.addEventListener("hashchange", onNavigate);
    window.addEventListener("popstate", onNavigate);
    window.addEventListener("open-entity", onOpen);
    return () => {
      window.removeEventListener("hashchange", onNavigate);
      window.removeEventListener("popstate", onNavigate);
      window.removeEventListener("open-entity", onOpen);
    };
  }, []);
  useEffect(() => {
    if (page === "ask") document.title = "Analytics Manager";
  }, [page]);
  console.log('clg')
  return (
    <div className={`app app-${page}`}>
      <Sidebar page={page} />
      <div className="app-main">
        {/* Stays mounted so an answer keeps arriving, and the screen stays as it was, while on another page. */}
        <div hidden={page !== "ask"}><AskPage /></div>
        {page === "explorer" && <ExplorerPage focusRequest={focusRequest} />}
        {page === "cala-graph" && <CalaGraphPage />}
      </div>
    </div>
  );
}
