import { useEffect, useRef, useState } from "react";
import logo from "../assets/analytiq-logo.png";
import { Icon } from "../components/Icon";
import { KnowledgeGraph } from "../components/KnowledgeGraph";
import { navigate } from "../components/Sidebar";
import { loadEstate, type GraphPayload } from "../lib/estate";

/** Each problem with the way AnalytIQ answers it. "Solution rationale" crosses out the problem and shows the answer. */
const PROBLEMS: { title: string; text: string; solution: string }[] = [
  { title: "The same report, built again and again", text: "Each department asks for its own dashboard. The same KPI ends up in many reports, often with different numbers.",
    solution: "Checks what already exists first, and recommends reusing or extending it instead of building a copy." },
  { title: "Nobody knows which one to trust", text: "Owners move on, reports go unchecked, and there is no clear sign of which version is certified.",
    solution: "Scores every report for trust: certified definitions, an active owner, passing quality tests and a recent review." },
  { title: "Reports never retire", text: "New dashboards keep arriving, old ones stay, and Tableau reports wait for a move to Power BI.",
    solution: "Flags overlapping and poorly governed reports to merge or retire, and says which Tableau reports to move first." },
  { title: "Hard to review or fix", text: "Point-and-click reports can't be version controlled or debugged, so mistakes are hard to trace.",
    solution: "Every recommendation shows its scores, the rules applied and the evidence, so each decision can be traced." },
];

/** One-screen landing page at /index: text on the left, the live knowledge graph on the right. No sidebar. */
export function LandingPage() {
  const [graph, setGraph] = useState<GraphPayload | null>(null);
  const [failed, setFailed] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const [rationale, setRationale] = useState(false);

  useEffect(() => {
    document.title = "AnalytIQ Intelligence";
    let current = true;
    loadEstate()
      .then((data) => { if (current) setGraph(data); })
      .catch(() => { if (current) setFailed(true); });
    return () => { current = false; };
  }, []);

  const close = () => { dialog.current?.close(); setRationale(false); };

  return (
    <main className="landing">
      <div className="landing-body">
        <section className="landing-hero">
          <img className="landing-logo" src={logo} alt="AnalytIQ Intelligence" width={900} height={300} />
          <p className="landing-kicker">Build less, build better</p>
          <h1>Ask the question. We check what already exists before anything is built.</h1>
          <p className="landing-lead">
            Describe the decision you need to make. <strong className="landing-name">AnalytIQ Intelligence</strong> finds the certified KPIs and reports that already answer it,
            checks if they can be trusted, and recommends what to do, with the evidence.
          </p>
          <div className="landing-actions">
            <a className="landing-primary" href="/" onClick={navigate}>Try our solution</a>
            <button type="button" className="landing-secondary" aria-haspopup="dialog" onClick={() => dialog.current?.showModal()}>See the problem we solve</button>
          </div>
        </section>

        <section className="landing-graph" aria-label="Knowledge graph of the live catalog. Drag to turn.">
          {graph ? (
            <KnowledgeGraph entities={graph.entities} edges={graph.edges} groupLabels={false} selectable={false} autoHighlight nameTips={false} animateLinks fill={0.95} zoomable={false} dotScale={1.6} />
          ) : (
            <p className="kg-status" role="status">
              {failed ? "The knowledge graph needs the backend. Start it, then reload this page." : "Loading the catalog"}
            </p>
          )}
        </section>
      </div>

      <footer className="landing-footer">Built by Brainrot team</footer>

      {/* Native dialog: focus stays inside and Esc closes it. A click on the backdrop (the dialog element itself) closes it too. */}
      <dialog ref={dialog} className="problem" aria-labelledby="problem-title" onClose={() => setRationale(false)} onClick={(e) => { if (e.target === e.currentTarget) close(); }}>
        <div className="problem-body">
          <header className="problem-head">
            <div>
              <p className="landing-kicker">{rationale ? "How we solve it" : "The problem we solve"}</p>
              <h2 id="problem-title" className={rationale ? "problem-title-struck" : undefined}>Too many reports, and no way to tell which one to use.</h2>
              {rationale && (
                <p className="problem-title-fix">AnalytIQ Intelligence solves it: one trusted answer, with the evidence, before anything new is built.</p>
              )}
            </div>
            <button type="button" className="problem-close" aria-label="Close" onClick={close}><Icon name="close" /></button>
          </header>
          <ol className={`problem-list${rationale ? " solved" : ""}`}>
            {PROBLEMS.map((p, i) => (
              <li key={p.title} style={{ ["--i" as string]: i }}>
                <span className="problem-n" aria-hidden="true">{rationale ? <span className="problem-badge"><Icon name="close" size={13} /></span> : String(i + 1).padStart(2, "0")}</span>
                <div>
                  <h3>{rationale && <span className="sr-only">Problem: </span>}{p.title}</h3>
                  <p className="problem-text">{p.text}</p>
                </div>
                {rationale && (
                  <p className="problem-fix"><span className="problem-badge"><Icon name="check" size={13} /></span><span><span className="sr-only">Solution: </span>{p.solution}</span></p>
                )}
              </li>
            ))}
          </ol>
          <p className="problem-answer">
            Hit{" "}
            <button type="button" className="problem-inline-btn" aria-pressed={rationale} onClick={() => setRationale((r) => !r)}>
              Solution rationale
            </button>{" "}
            {rationale
              ? <>again to see the problems. Above is how <strong>AnalytIQ Intelligence</strong> solves each one.</>
              : <>to see how <strong>AnalytIQ Intelligence</strong> solves each problem.</>}
          </p>
          <div className="problem-actions">
            <a className="landing-primary" href="/" onClick={(e) => { close(); navigate(e); }}>Try our solution</a>
          </div>
        </div>
      </dialog>
    </main>
  );
}
