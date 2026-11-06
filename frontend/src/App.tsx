import { useCallback, useEffect, useState } from "react";
import { api } from "./api/client";
import { TopBar, type Page } from "./components/TopBar";
import { ActionsPage } from "./pages/ActionsPage";
import { AskPage } from "./pages/AskPage";
import { ExplorerPage } from "./pages/ExplorerPage";

const pageFromHash = (): Page =>
  window.location.hash.startsWith("#explorer") ? "explorer" : window.location.hash.startsWith("#actions") ? "actions" : "ask";

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

  return (
    <div className={`app app-${page}`}>
      <TopBar
        page={page}
        onPick={(id) => { setFocusRequest(id); window.location.hash = "#explorer"; }}
        activeActions={activeActions}
      />
      {page === "ask" && <AskPage onActionsChanged={refreshActions} />}
      {page === "explorer" && <ExplorerPage focusRequest={focusRequest} />}
      {page === "actions" && <ActionsPage onChanged={refreshActions} />}
    </div>
  );
}
