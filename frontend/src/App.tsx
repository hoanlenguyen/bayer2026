import { useEffect, useState } from "react";
import { Sidebar, type Page } from "./components/Sidebar";
import { AskPage } from "./pages/AskPage";
import { ExplorerPage } from "./pages/ExplorerPage";

const pageFromHash = (): Page => (window.location.hash.startsWith("#explorer") ? "explorer" : "ask");

export default function App() {
  const [page, setPage] = useState<Page>(pageFromHash);
  const [focusRequest, setFocusRequest] = useState<string | null>(null);

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
  console.log('clg')
  return (
    <div className={`app app-${page}`}>
      <Sidebar page={page} />
      <div className="app-main">
        {page === "ask" ? <AskPage /> : <ExplorerPage focusRequest={focusRequest} />}
      </div>
    </div>
  );
}
