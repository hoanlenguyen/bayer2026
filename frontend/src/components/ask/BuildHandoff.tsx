import { useEffect, useRef, useState } from "react";
import { dashboardUrl, type BuildReceipt, type DesignState } from "../../api/dashboardBuilder";
import { getCurrentConversation, useCurrentConversation } from "../../lib/conversations";

/* "Preparing your dashboard": the hand-off from an approved brief to the saved dashboard, shown as the four steps the
   build actually performs. Truth and timing are separate. Steps 1 to 3 describe work established during review (the
   receipt). Step 4 changes to "Dashboard saved" only after the server confirms the save. The reading window decides
   only when a confirmed dashboard may open by itself: at max(confirmed save, approval + window). */

export const READING_WINDOW_MS = 4500;

export type BuildPhase =
  | { kind: "saving" }
  | { kind: "saved"; dashboardId: string; exactReuse?: boolean }
  /** recovery: "review" after a 409, "retry" when the same reviewed brief can be sent again, "reload" when it must be checked first */
  | { kind: "failed"; message: string; recovery: "review" | "retry" | "reload" };

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

interface Step { title: string; lines: string[] }

/** The four steps, from what review established (the receipt) or, without one, from the reviewed summary. */
function steps(brief: DesignState): Step[] {
  const r = brief.receipt;
  if (!r) return [
    { title: "Confirm the reviewed brief", lines: brief.summary.length ? brief.summary : ["The brief you approved, unchanged."] },
    { title: "Match the workbook evidence", lines: ["The synthetic workbook rows matched during review are checked again."] },
    { title: "Prepare the dashboard view", lines: ["The approved measures are laid out as monthly figures with their source rows."] },
    { title: "Save and open the dashboard", lines: [] },
  ];
  const evidence = [`From the review: ${plural(r.months, "month")} of figures in ${r.source ?? "the workbook"}`
    + (r.observations !== r.months ? `, from ${plural(r.observations, "source row")}` : "") + "."];
  if (r.observations) evidence.push(`${r.actual_like} actual-like and ${r.forecast_like} forecast-like synthetic records.`);
  const brief1 = [[scopeText(r), periodText(r)].filter(Boolean).join(" · ")];
  if (r.decision_goal) brief1.unshift(`Purpose: ${r.decision_goal}`);
  if (r.omitted_measures.length) brief1.push(`Left out, as you agreed: ${omitted(r)}.`);
  return [
    { title: "Confirm the reviewed brief", lines: brief1 },
    { title: "Match the workbook evidence", lines: evidence },
    { title: "Prepare the dashboard view", lines: [measureText(r), r.arrangement] },
    { title: "Save and open the dashboard", lines: [] },
  ];
}

export function BuildHandoff({ session, conversationId, onRetry, onReviewUpdated, onReload, onFinished }: {
  session: BuildSession; conversationId: string; onRetry: () => void; onReviewUpdated: () => void; onReload: () => void;
  /** The hand-off is over: the dashboard opened, or opening by itself is no longer allowed. */
  onFinished: () => void;
}) {
  const { phase, brief, startedAt } = session;
  const [windowOver, setWindowOver] = useState(() => performance.now() - startedAt >= READING_WINDOW_MS);
  const [highlight, setHighlight] = useState(0);
  const [autoOpen, setAutoOpen] = useState(true);  // permission to take over the screen, separate from the window
  const opened = useRef(false);
  const finished = useRef(false);
  const heading = useRef<HTMLHeadingElement>(null);
  const panel = useRef<HTMLElement>(null);
  const current = useCurrentConversation();

  const finish = () => { if (!finished.current) { finished.current = true; onFinished(); } };

  // On approval: focus the workflow heading (only in a visible Ask) and keep the panel in view inside Ask's scroll area.
  useEffect(() => {
    if (!stillHere(conversationId)) return;
    heading.current?.focus({ preventScroll: true });
    panel.current?.scrollIntoView({ block: "nearest" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // The reading window and a gentle highlight through the four steps. Timers only move emphasis; they never save or open.
  useEffect(() => {
    const elapsed = performance.now() - startedAt;
    const each = READING_WINDOW_MS / 4;
    const timers = [1, 2, 3].map(i => window.setTimeout(() => setHighlight(h => Math.max(h, i)), Math.max(0, i * each - elapsed)));
    timers.push(window.setTimeout(() => setWindowOver(true), Math.max(0, READING_WINDOW_MS - elapsed)));
    setHighlight(Math.min(3, Math.floor(elapsed / each)));
    return () => timers.forEach(t => window.clearTimeout(t));
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

  // Open exactly once, when the save is confirmed and the window has passed, if this attempt still owns the screen.
  const saved = phase.kind === "saved" ? phase : null;
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

  const list = steps(brief);
  const status = phase.kind === "saving" ? (windowOver ? "Still preparing your dashboard…" : "Saving your dashboard…")
    : phase.kind === "saved" ? (phase.exactReuse ? "Dashboard saved. It matches an identical dashboard saved earlier, so that saved version opens."
      : autoOpen && !windowOver ? "Dashboard saved." : autoOpen ? "Dashboard saved. Opening it now." : "Dashboard saved.")
    : "The dashboard was not saved.";
  const active = phase.kind === "saving" ? highlight : phase.kind === "saved" ? (windowOver ? 3 : highlight) : 3;

  // A double click on Build would otherwise select a word in this panel, which replaces the button.
  return <section ref={panel} className={`bw bw-${phase.kind}`} aria-labelledby={`bw-${session.id}`}
    onMouseDown={e => { if (e.detail > 1) e.preventDefault(); }}>
    <h3 id={`bw-${session.id}`} ref={heading} tabIndex={-1}>Preparing your dashboard</h3>
    <p className="bw-lede">Here’s how your reviewed brief becomes a dashboard.</p>
    <ol className="bw-steps">{list.map((s, i) => {
      const last = i === 3;
      const state = last ? phase.kind : "described";
      return <li key={s.title} className={`bw-step${i === active ? " bw-active" : ""}${last ? ` bw-final bw-${state}` : ""}`}>
        <span className="bw-num" aria-hidden="true">{i + 1}</span>
        <div className="bw-body">
          <p className="bw-title"><span className="sr-only">Step {i + 1}: </span>{s.title}</p>
          {s.lines.map((l, j) => <p key={j} className="bw-line">{l}</p>)}
          {last && <p className="bw-status">{phase.kind === "saving" && <span className="bh-spinner" aria-hidden="true" />}{status}</p>}
          {last && phase.kind === "failed" && <div className="db-error" role="alert">
            <p>{phase.message}</p>
            {phase.recovery === "review" ? <button type="button" className="btn-outline" onClick={onReviewUpdated}>Review updated brief</button>
              : phase.recovery === "retry" ? <button type="button" className="btn-outline" onClick={onRetry}>Try building again</button>
              : <button type="button" className="btn-outline" onClick={onReload}>Reload the brief</button>}
          </div>}
          {last && saved && windowOver && !opened.current && !autoOpen && <a className="btn" href={dashboardUrl(saved.dashboardId)}
            onClick={e => { if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return; e.preventDefault(); opened.current = true; openDashboard(saved.dashboardId); }}>
            Open saved dashboard</a>}
        </div>
      </li>;
    })}</ol>
    {/* One short announcement per outcome, not per step. */}
    <p className="sr-only" role="status" aria-live="polite">{phase.kind === "saved" ? "Dashboard saved." : phase.kind === "failed" ? "The dashboard was not saved." : ""}</p>
  </section>;
}
