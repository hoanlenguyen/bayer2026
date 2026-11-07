import { useEffect, useRef, useState } from "react";
import { dashboardUrl, type BuildReceipt, type DesignState } from "../../api/dashboardBuilder";
import { getCurrentConversation, useCurrentConversation } from "../../lib/conversations";
import { prefetchDashboard } from "../../lib/dashboardPrefetch";
import { BUILD_OVERVIEW_MS } from "../../lib/overview";

/* "Preparing your dashboard": the hand-off from an approved brief to the saved dashboard, shown as the four steps the
   build actually performs. Truth and timing are separate. Steps 1 to 3 describe work established during review (the
   receipt). Step 4 changes to "Dashboard saved" only after the server confirms the save. The reading window decides
   only when a confirmed dashboard may open by itself: at max(confirmed save, approval + window). */

export const READING_WINDOW_MS = BUILD_OVERVIEW_MS;

export type BuildPhase =
  | { kind: "saving" }
  | { kind: "saved"; dashboardId: string }
  /** uncertain: the outcome could not be established. recovery: "review" after a 409, "retry" with the same brief, "reload" first */
  | { kind: "failed"; message: string; recovery: "review" | "retry" | "reload"; uncertain: boolean };

export interface BuildSession { id: number; startedAt: number; phase: BuildPhase; brief: DesignState }

const monthName = (m: string | null | undefined, opts: Intl.DateTimeFormatOptions = { month: "long", year: "numeric" }) =>
  m ? new Date(m.slice(0, 7) + "-01T00:00:00Z").toLocaleDateString("en-GB", { ...opts, timeZone: "UTC" }) : "";

export function periodText(r: BuildReceipt) {
  const start = r.period?.start ?? r.first_month, end = r.period?.end ?? r.last_month;
  if (!start) return "";
  if (start.slice(0, 7) === end?.slice(0, 7)) return monthName(start);
  const sameYear = start.slice(0, 4) === end?.slice(0, 4);
  return `${monthName(start, sameYear ? { month: "long" } : undefined)} to ${monthName(end)}`;
}
const places = (names: string[], kind: string) => names.length > 3 ? `${names.length} ${kind}` : names.join(", ");
export const scopeText = (r: BuildReceipt) => [places(r.products, "products"), places(r.markets, "markets")].filter(Boolean).join(" in ");
const unitText = (u: string) => /^(m eur|eur m)$/i.test(u) ? "€m" : u;
const measureText = (r: BuildReceipt) => r.measures.map(m => m.unit ? `${m.name} (${unitText(m.unit)})` : m.name).join(" · ");
const plural = (n: number, one: string, many = one + "s") => `${n} ${n === 1 ? one : many}`;
const omitted = (r: BuildReceipt) => r.omitted_measures.map(m => m.replaceAll("_", " ")).join(", ");

/** Facts from the reviewed brief. Also shown on the saved dashboard under "Dashboard brief and sources". */
export function ReceiptFacts({ receipt, saved }: { receipt: BuildReceipt; saved: boolean }) {
  return <dl className="bh-facts">
    <div><dt>Brief</dt><dd>{scopeText(receipt)} · {periodText(receipt)}</dd></div>
    <div><dt>Measures</dt><dd>{measureText(receipt)}</dd></div>
    {receipt.omitted_measures.length > 0 && <div><dt>Left out, as you agreed</dt><dd>{omitted(receipt)}</dd></div>}
    <div><dt>Source</dt><dd>{plural(receipt.months, "monthly observation", "monthly observations")} matched
      {receipt.observations !== receipt.months && <> from {plural(receipt.observations, "workbook row")}</>}{saved ? "" : " during review"}</dd></div>
    <div><dt>{saved ? "Opens with" : "Will open with"}</dt><dd>{receipt.arrangement}</dd></div>
  </dl>;
}

export function ReceiptDetails({ receipt }: { receipt: BuildReceipt }) {
  return <ul className="bh-details">
    {receipt.rows && <li>Workbook sheet <code>{receipt.source}</code>, rows between {receipt.rows.first} and {receipt.rows.last}</li>}
    <li>{receipt.actual_like} actual-like and {receipt.forecast_like} forecast-like synthetic records</li>
    {receipt.measures.map(m => <li key={m.id}>{m.name}{m.kpi_id && <> · governed KPI <code>{m.kpi_id}</code></>}{m.unit && <> · {unitText(m.unit)}</>}</li>)}
    {receipt.groups > 1 && <li>{receipt.groups} groups: {receipt.group_labels.join(", ")}</li>}
  </ul>;
}

/** True only while the employee is still looking at this conversation in Ask, in a visible tab. */
function stillHere(conversationId: string) {
  const onAsk = window.location.pathname === "/" && (!window.location.hash || window.location.hash.startsWith("#ask"));
  return onAsk && document.visibilityState === "visible" && getCurrentConversation() === conversationId;
}

export function openDashboard(id: string) {
  history.pushState({ focusHeading: true }, "", dashboardUrl(id));
  window.scrollTo(0, 0);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

interface Row { title: string; lines: string[] }

/** The four rows: three from the reviewed brief (the receipt), and the saved result, which only the server confirms. */
function rows(brief: DesignState, phase: BuildPhase): Row[] {
  const r = brief.receipt;
  const saved = phase.kind === "saved" ? ["Saved as this request's own dashboard."] : phase.kind === "saving" ? ["Waiting for the server to confirm the save."]
    : [phase.uncertain ? "The save could not be confirmed." : "Not saved."];
  if (!r) return [
    { title: "Approved scope and period", lines: brief.summary.length ? brief.summary.slice(0, 3) : ["The brief you approved, unchanged."] },
    { title: "Workbook coverage and source rows", lines: ["The synthetic workbook rows matched during review are checked again."] },
    { title: "Governed measures and view", lines: ["The approved measures, as monthly figures with their source rows."] },
    { title: "Saved result", lines: saved },
  ];
  const scope = [[scopeText(r), periodText(r)].filter(Boolean).join(" · ")];
  if (r.decision_goal) scope.unshift(`Purpose: ${r.decision_goal}`);
  if (r.omitted_measures.length) scope.push(`Left out, as you agreed: ${omitted(r)}.`);
  const coverage = [`${plural(r.months, "month")} of figures in ${r.source ?? "the workbook"}`
    + (r.observations !== r.months ? `, from ${plural(r.observations, "source row")}` : "") + "."];
  if (r.observations) coverage.push(`${r.actual_like} actual-like and ${r.forecast_like} forecast-like synthetic records.`);
  return [
    { title: "Approved scope and period", lines: scope },
    { title: "Workbook coverage and source rows", lines: coverage },
    { title: "Governed measures and view", lines: [measureText(r), r.arrangement] },
    { title: "Saved result", lines: saved },
  ];
}

export function BuildHandoff({ session, conversationId, onRetry, onReviewUpdated, onReload, onFinished }: {
  session: BuildSession; conversationId: string; onRetry: () => void; onReviewUpdated: () => void; onReload: () => void;
  /** The hand-off is over: the dashboard opened, or opening by itself is no longer allowed. */
  onFinished: () => void;
}) {
  const { phase, brief, startedAt } = session;
  const [windowOver, setWindowOver] = useState(() => performance.now() - startedAt >= READING_WINDOW_MS);
  const [autoOpen, setAutoOpen] = useState(true);  // permission to take over the screen, separate from the window
  const opened = useRef(false);
  const finished = useRef(false);
  const heading = useRef<HTMLHeadingElement>(null);
  const panel = useRef<HTMLElement>(null);
  const current = useCurrentConversation();

  const finish = () => { if (!finished.current) { finished.current = true; onFinished(); } };

  // On approval: bring the heading into view inside Ask's pane (only in a visible Ask), and warm the destination's code.
  useEffect(() => {
    void import("../../pages/SavedDashboardPage");
    if (!stillHere(conversationId)) return;
    heading.current?.focus({ preventScroll: true });
    panel.current?.scrollIntoView({ block: "nearest" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // The overview: one window from approval. It only decides when a confirmed dashboard may open; it never saves or completes anything.
  useEffect(() => {
    const timer = window.setTimeout(() => setWindowOver(true), Math.max(0, READING_WINDOW_MS - (performance.now() - startedAt)));
    return () => window.clearTimeout(timer);
  }, [startedAt]);

  // Leaving Ask, Back, opening an entity, hiding the tab or switching conversation: this attempt never takes over later.
  useEffect(() => {
    if (!autoOpen) return;
    const stop = () => { if (!opened.current) setAutoOpen(false); };
    const hidden = () => { if (document.visibilityState !== "visible") stop(); };
    window.addEventListener("popstate", stop);
    window.addEventListener("hashchange", stop);
    window.addEventListener("open-entity", stop);
    document.addEventListener("visibilitychange", hidden);
    return () => {
      window.removeEventListener("popstate", stop);
      window.removeEventListener("hashchange", stop);
      window.removeEventListener("open-entity", stop);
      document.removeEventListener("visibilitychange", hidden);
    };
  }, [autoOpen]);
  useEffect(() => { if (current !== conversationId && !opened.current) setAutoOpen(false); }, [current, conversationId]);

  // Start the destination's one canonical read as soon as the server confirmed the dashboard ID.
  const saved = phase.kind === "saved" ? phase : null;
  useEffect(() => { if (saved) prefetchDashboard(saved.dashboardId); }, [saved?.dashboardId]);  // eslint-disable-line react-hooks/exhaustive-deps

  // Open exactly once, when the save is confirmed and the window has passed, if this attempt still owns the screen.
  useEffect(() => {
    if (!saved || !windowOver || opened.current) return;
    if (autoOpen && stillHere(conversationId)) {
      opened.current = true;
      finish();
      openDashboard(saved.dashboardId);
    } else {
      setAutoOpen(false);
      finish();  // the parent may now show the saved result; this panel offers the ordinary link
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [saved?.dashboardId, windowOver, autoOpen]);
  useEffect(() => { if (phase.kind === "failed") finish(); }, [phase.kind]);  // eslint-disable-line react-hooks/exhaustive-deps

  const status = phase.kind === "saving" ? "Checking and saving your dashboard…"
    : phase.kind === "saved" ? "Dashboard ready"
    : phase.uncertain ? "Save could not be confirmed" : "The dashboard was not saved";
  const showLink = saved && windowOver && !opened.current && !autoOpen;

  // A double click on Build would otherwise select a word in this panel, which replaces the button.
  return <section ref={panel} className={`bw bw-${phase.kind}`} aria-labelledby={`bw-${session.id}`}
    onMouseDown={e => { if (e.detail > 1) e.preventDefault(); }}>
    <h3 id={`bw-${session.id}`} ref={heading} tabIndex={-1}>How your dashboard is prepared</h3>
    <p className="bw-status">{phase.kind === "saving" && <span className="bh-spinner" aria-hidden="true" />}<strong>{status}</strong></p>
    {saved && <p className="bw-lede">Take a moment to review what went into it.</p>}
    {phase.kind === "failed" && <div className="db-error" role="alert">
      <p>{phase.message}</p>
      {phase.recovery === "review" ? <button type="button" className="btn-outline" onClick={onReviewUpdated}>Review updated brief</button>
        : phase.recovery === "retry" ? <button type="button" className="btn-outline" onClick={onRetry}>Try building again</button>
        : <button type="button" className="btn-outline" onClick={onReload}>Reload the brief</button>}
    </div>}
    {showLink && <a className="btn" href={dashboardUrl(saved.dashboardId)}
      onClick={e => { if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return; e.preventDefault(); opened.current = true; openDashboard(saved.dashboardId); }}>
      Open saved dashboard</a>}
    <p className="db-label">From your reviewed brief</p>
    <ol className="bw-steps">{rows(brief, phase).map((row, i) => {
      const last = i === 3;
      return <li key={row.title} className={`bw-step${last ? ` bw-final bw-${phase.kind}` : ""}`}>
        <span className="bw-num" aria-hidden="true">{i + 1}</span>
        <div className="bw-body">
          <p className="bw-title">{row.title}</p>
          {row.lines.map((l, j) => <p key={j} className="bw-line">{l}</p>)}
        </div>
      </li>;
    })}</ol>
    {/* One short announcement per outcome. */}
    <p className="sr-only" role="status" aria-live="polite">{phase.kind === "saving" ? "" : status}</p>
  </section>;
}
