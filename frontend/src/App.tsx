import { WorkbookPage } from "./pages/WorkbookPage";
import { useCallback, useEffect, useState } from "react";
import { api } from "./api/client";
import { TopBar, type Page } from "./components/TopBar";
import { ActionsPage } from "./pages/ActionsPage";
import { AskPage } from "./pages/AskPage";
import { ExplorerPage } from "./pages/ExplorerPage";

const pageFromHash = (): Page =>
  window.location.hash.startsWith("#explorer")
    ? "explorer"
    : window.location.hash.startsWith("#actions")
      ? "actions"
      : window.location.hash.startsWith("#source") ? "source" : "ask";

export default function App() {
  const [page, setPage] = useState<Page>(pageFromHash);
  const [focusRequest, setFocusRequest] = useState<string | null>(null);
  const [activeActions, setActiveActions] = useState(0);

  const refreshActions = useCallback(() => {
    api.actions().then((d) => setActiveActions(d.summary.active)).catch(() => undefined);
  }, []);
  useEffect(() => { refreshActions(); }, [page, refreshActions]);

  useEffect(() => {
    const onHash = () => setPage(pageFromHash());
    // Other pages can ask to open an entity: window.dispatchEvent(new CustomEvent("open-entity", { detail: id }))
    const onOpen = (e: Event) => {
      setFocusRequest((e as CustomEvent<string>).detail);
      window.location.hash = "#explorer";
    };
    window.addEventListener("hashchange", onHash);
    window.addEventListener("open-entity", onOpen);
    return () => {
      window.removeEventListener("hashchange", onHash);
      window.removeEventListener("open-entity", onOpen);
    };
  }, []);

  useEffect(() => {
    if (page === "ask") document.title = "Investigations · Analytics Manager";
    if (page === "actions") document.title = "Actions · Analytics Manager";
  }, [page]);

  return (
    <div className={`app app-${page}`}>
      <TopBar
        page={page}
        onPick={(id) => {
          setFocusRequest(id);
          window.location.hash = "#explorer";
        }}
        activeActions={activeActions}
      />
      {/* Investigations stay mounted so the active session survives a visit to the asset index. */}
      <div hidden={page !== "ask"}>
        <AskPage onActionsChanged={refreshActions} />
      </div>
      {page === "explorer" && <ExplorerPage focusRequest={focusRequest} />}
      {page === "source" && <WorkbookPage />}
      {page === "actions" && <ActionsPage onChanged={refreshActions} />}
    </div>
  );
}
