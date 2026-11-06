import { useEffect, useState } from "react";
import { TopBar, type Page } from "./components/TopBar";
import { AskPage } from "./pages/AskPage";
import { ExplorerPage } from "./pages/ExplorerPage";

const pageFromHash = (): Page => (window.location.hash.startsWith("#explorer") ? "explorer" : "ask");

export default function App() {
  const [page, setPage] = useState<Page>(pageFromHash);
  const [focusRequest, setFocusRequest] = useState<string | null>(null);

  useEffect(() => {
    const onHash = () => setPage(pageFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  return (
    <div className={`app app-${page}`}>
      <TopBar
        page={page}
        onPick={(id) => { setFocusRequest(id); window.location.hash = "#explorer"; }}
      />
      {page === "ask" ? <AskPage /> : <ExplorerPage focusRequest={focusRequest} />}
    </div>
  );
}
