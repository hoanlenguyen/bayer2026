import { useEffect, useRef, useState } from "react";
import { dashboardUrl, type BuildReceipt, type DesignState } from "../../api/dashboardBuilder";
import { getCurrentConversation } from "../../lib/conversations";
import { Icon } from "../Icon";

/* The hand-off from an approved brief to the saved dashboard.
   Truth and timing are separate: "Dashboard ready" appears only after the server confirms the save, and the
   5.5 s reading target (from the click) only decides when the dashboard opens by itself. */

export const READING_TARGET_MS = 5500;

export type BuildPhase =
  | { kind: "saving" }
  | { kind: "ready"; dashboardId: string; savedAfterMs: number; exactReuse?: boolean }
  | { kind: "failed"; message: string; stale: boolean };

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
const measureText = (r: BuildReceipt) => r.measures.map(m => m.unit ? `${m.name} (${m.unit})` : m.name).join(" · ");
const plural = (n: number, one: string, many = one + "s") => `${n} ${n === 1 ? one : many}`;

/** Facts shown from the reviewed brief, before and after the save. Only fields the server computed. */
export function ReceiptFacts({ receipt, saved }: { receipt: BuildReceipt; saved: boolean }) {
  return <dl className="bh-facts">
    <div><dt>Brief</dt><dd>{scopeText(receipt)} · {periodText(receipt)}</dd></div>
    <div><dt>Measures</dt><dd>{measureText(receipt)}</dd></div>
    {receipt.omitted_measures.length > 0 && <div><dt>Left out, as you agreed</dt><dd>{receipt.omitted_measures.map(m => m.replaceAll("_", " ")).join(", ")}</dd></div>}
    <div><dt>Source</dt><dd>{plural(receipt.months, "monthly observation", "monthly observations")} matched
      {receipt.observations !== receipt.months && <> from {plural(receipt.observations, "workbook row")}</>}{saved ? "" : " during review"}</dd></div>
    <div><dt>{saved ? "Opens with" : "Will open with"}</dt><dd>{receipt.arrangement}</dd></div>
  </dl>;
}

export function ReceiptDetails({ receipt }: { receipt: BuildReceipt }) {
  return <ul className="bh-details">
    {receipt.rows && <li>Workbook sheet <code>{receipt.source}</code>, rows {receipt.rows.first} to {receipt.rows.last}</li>}
    <li>{receipt.actual_like} actual-like and {receipt.forecast_like} forecast-like synthetic records</li>
    {receipt.measures.map(m => <li key={m.id}>{m.name}{m.kpi_id && <> · governed KPI <code>{m.kpi_id}</code></>}{m.unit && <> · {m.unit}</>}</li>)}
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

export function BuildHandoff({ session, conversationId, onRetry, onReviewUpdated, onStay }: {
  session: BuildSession; conversationId: string; onRetry: () => void; onReviewUpdated: () => void; onStay: () => void;
}) {
  const { phase, brief } = session;
  const receipt = brief.receipt;
  const [auto, setAuto] = useState(true);
  const [now, setNow] = useState(() => performance.now());
  const opened = useRef(false);
  const heading = useRef<HTMLHeadingElement>(null);

  const open = (id: string) => { if (opened.current) return; opened.current = true; setAuto(false); openDashboard(id); };

  // Any navigation, conversation switch or hidden tab while waiting stops the automatic opening for good.
  useEffect(() => {
    if (!auto) return;
    const stop = () => { if (!opened.current) setAuto(false); };
    const hidden = () => { if (document.visibilityState !== "visible") stop(); };
    window.addEventListener("popstate", stop);
    window.addEventListener("hashchange", stop);
    document.addEventListener("visibilitychange", hidden);
    return () => {
      window.removeEventListener("popstate", stop);
      window.removeEventListener("hashchange", stop);
      document.removeEventListener("visibilitychange", hidden);
    };
  }, [auto]);

  // Open once at the reading target, or right away if the save itself took longer. Never before a confirmed save.
  useEffect(() => {
    if (!auto || phase.kind !== "ready") return;
    const wait = Math.max(0, session.startedAt + READING_TARGET_MS - performance.now());
    const timer = window.setTimeout(() => {
      if (stillHere(conversationId)) open(phase.dashboardId); else setAuto(false);
    }, wait);
    const tick = window.setInterval(() => setNow(performance.now()), 250);
    return () => { window.clearTimeout(timer); window.clearInterval(tick); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auto, phase, session.startedAt, conversationId]);

  useEffect(() => { if (phase.kind !== "saving") heading.current?.focus({ preventScroll: true }); }, [phase.kind]);

  const stay = () => { setAuto(false); onStay(); };
  const left = Math.max(0, Math.ceil((session.startedAt + READING_TARGET_MS - now) / 1000));
  const title = phase.kind === "saving" ? "Saving your reviewed dashboard…" : phase.kind === "ready" ? "Dashboard ready" : "The dashboard was not saved";

  // A double click on Build would otherwise select a word in this panel, which replaces the button.
  return <section className={`bh bh-${phase.kind}`} aria-labelledby={`bh-${session.id}`} onMouseDown={e => { if (e.detail > 1) e.preventDefault(); }}>
    <div className="bh-head">
      {phase.kind === "saving" && <span className="bh-spinner" aria-hidden="true" />}
      {phase.kind === "ready" && <span className="bh-done" aria-hidden="true"><Icon name="check" size={14} /></span>}
      <h3 id={`bh-${session.id}`} ref={heading} tabIndex={-1}>{title}</h3>
    </div>
    {/* Announced once per change: saving, ready or failed. The countdown is not announced. */}
    <p className="sr-only" role="status" aria-live="polite">{phase.kind === "saving" ? "Saving your reviewed dashboard."
      : phase.kind === "ready" ? "Dashboard ready. Open now is available." : ""}</p>

    {receipt ? <>
      {phase.kind === "ready" && phase.exactReuse && <p className="small">An identical dashboard (same purpose, scope, period, KPI definitions and values) was saved earlier. This review now points to that saved version.</p>}
      <p className="db-label">{phase.kind === "ready" ? "Built from your approved brief" : "From your approved brief"}</p>
      <ReceiptFacts receipt={receipt} saved={phase.kind === "ready"} />
      <details className="bh-more" onToggle={e => { if ((e.currentTarget as HTMLDetailsElement).open) stay(); }}>
        <summary>View build details</summary><ReceiptDetails receipt={receipt} />
        {phase.kind === "ready" && <p className="db-caption">Saved {phase.savedAfterMs < 1000 ? "in under a second" : `after ${(phase.savedAfterMs / 1000).toFixed(1)} s`}.
          The figures come from the workbook rows above. No model was used to build it.</p>}
      </details>
    </> : <ul className="db-brief">{brief.summary.map((line, i) => <li key={i}>{line}</li>)}</ul>}

    {phase.kind === "ready" && <div className="bh-actions">
      <button type="button" className="btn" onClick={() => open(phase.dashboardId)}>Open now<Icon name="arrowRight" size={15} /></button>
      {auto ? <>
        <span className="db-caption" aria-hidden="true">{left > 0 ? `Opens by itself in ${left} s` : "Opening…"}</span>
        <button type="button" className="db-text-link" onClick={stay}>Stay here</button>
      </> : <span className="db-caption">Also saved under Saved dashboards on the start screen.</span>}
    </div>}

    {phase.kind === "failed" && <div className="db-error" role="alert">
      <p>{phase.message}</p>
      {phase.stale ? <button type="button" className="btn-outline" onClick={onReviewUpdated}>Review updated brief</button>
        : <button type="button" className="btn-outline" onClick={onRetry}>Try building again</button>}
    </div>}
  </section>;
}
