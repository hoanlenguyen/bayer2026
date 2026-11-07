import { lazy, Suspense, useEffect, useState } from "react";
import { Sidebar, type Page } from "./components/Sidebar";
import { AskPage } from "./pages/AskPage";
import { CalaGraphPage } from "./pages/CalaGraphPage";
import { ExplorerPage } from "./pages/ExplorerPage";
import { LandingPage } from "./pages/LandingPage";
import { SimulatorPage } from "./pages/SimulatorPage";

const BriefingsPage = lazy(() => import("./pages/BriefingsPage").then(({ BriefingsPage }) => ({ default: BriefingsPage })));

const SavedDashboardPage = lazy(() => import("./pages/SavedDashboardPage").then(({ SavedDashboardPage }) => ({ default: SavedDashboardPage })));
const BIPortfolioPage = lazy(() => import("./pages/BIPortfolioPage").then(({ BIPortfolioPage }) => ({ default: BIPortfolioPage })));
const WorkbookViewPage = lazy(() => import("./pages/SavedDashboardPage").then(({ WorkbookViewPage }) => ({ default: WorkbookViewPage })));

type Route = { page: Page; ids: string[] };
const routeFromLocation = (): Route => {
  const path = window.location.pathname.replace(/\/+$/, "");
  if (path === "/index") return { page: "landing", ids: [] };
  const dashboard = /^\/dashboards\/([\w-]+)$/.exec(path);
  if (dashboard) return { page: "dashboard", ids: [dashboard[1]] };
  const workbook = /^\/workbook-view\/([\w-]+)\/([\w-]+)$/.exec(path);
  if (workbook) return { page: "workbook", ids: [workbook[1], workbook[2]] };
  const governance = /^\/bi-estate\/governance\/(evidence|risks|documents|assessments)\/([^/]+)$/.exec(path);
  if (governance) return { page: "bi-estate", ids: ["governance", governance[1], decodeURIComponent(governance[2])] };
  const portfolio = /^\/bi-estate(?:\/compare\/([\w-]+)\/([\w-]+)|\/([\w-]+))?$/.exec(path);
  // "compare" and "governance" are reserved words, never asset IDs.
  if (portfolio) return { page: "bi-estate", ids: portfolio[1] ? ["compare", portfolio[1], portfolio[2]]
    : portfolio[3] && !["compare", "governance"].includes(portfolio[3]) ? [portfolio[3]] : [] };
  if (path === "/cala-graph" || path === "/simulator" || path === "/briefings") return { page: path.slice(1) as Page, ids: [] };
  return { page: window.location.hash.startsWith("#explorer") ? "explorer" : "ask", ids: [] };
};

export default function App() {
  const [{ page, ids }, setRoute] = useState<Route>(routeFromLocation);
  const [focusRequest, setFocusRequest] = useState<string | null>(null);

  useEffect(() => {
    const onNavigate = () => setRoute(routeFromLocation());
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
    if (page === "ask") document.title = "AnalytIQ intelligence";
    if (page === "simulator") document.title = "Conversation simulation · AnalytIQ intelligence";
    if (page === "briefings") document.title = "Team briefings · AnalytIQ intelligence";
  }, [page]);
  return (
    <>
    {page === "landing" && <LandingPage />}
    <div className={`app app-${page}`} hidden={page === "landing"}>
      <Sidebar page={page} />
      <div className="app-main">
        {/* Ask and Simulator stay mounted so an answer keeps arriving, and the screen stays as it was, while on another page. */}
        <div hidden={page !== "ask"}><AskPage /></div>
        <div hidden={page !== "simulator"}><SimulatorPage /></div>
        {page === "explorer" && <ExplorerPage focusRequest={focusRequest} />}
        {page === "cala-graph" && <CalaGraphPage />}
        {page === "dashboard" && <Suspense fallback={<main aria-busy="true">Opening saved dashboard…</main>}>
          <SavedDashboardPage key={ids[0]} id={ids[0]}/></Suspense>}
        {page === "workbook" && <Suspense fallback={<main aria-busy="true">Opening verified workbook view…</main>}>
          <WorkbookViewPage key={ids.join("/")} conversationId={ids[0]} runId={ids[1]}/></Suspense>}
        {page === "bi-estate" && <Suspense fallback={<main className="page" aria-busy="true">Loading the BI Portfolio…</main>}><BIPortfolioPage ids={ids} /></Suspense>}
        {page === "briefings" && <Suspense fallback={<main className="page" aria-busy="true">Loading team briefings…</main>}><BriefingsPage /></Suspense>}
      </div>
    </div>
    </>
  );
}
