import { useEffect, useRef, useState } from "react";
import { dashboardUrl, type BuildReceipt, type BuildStepId, type DesignState } from "../../api/dashboardBuilder";
import { getCurrentConversation, useCurrentConversation } from "../../lib/conversations";
import { prefetchDashboard } from "../../lib/dashboardPrefetch";

/* "How your dashboard is prepared": the approved build as it runs. Each row is one checkpoint the server reports before
   its work starts and completes with that work's verified facts. "Dashboard saved" shows only after the server
   confirmed the committed result, and the dashboard opens at once if this attempt still owns the screen.
   No timer decides anything here. A server that answers with plain JSON gets one row for the single operation. */

export type BuildPhase =
  | { kind: "saving" }
  | { kind: "saved"; dashboardId: string; replayed: boolean }
  /** uncertain: the outcome could not be established. recovery: "review" after a 409, "retry" with the same brief, "reload" first */
  | { kind: "failed"; message: string; recovery: "review" | "retry" | "reload"; uncertain: boolean };

export interface BuildStep { status: "running" | "complete" | "failed"; facts?: Record<string, unknown> }
export interface BuildSession {
  id: number; startedAt: number; phase: BuildPhase; brief: DesignState;
  /** live: the server streams checkpoints. single: it answered with one JSON result, so only one operation is known. */
  mode: "live" | "single";
  steps: Partial<Record<BuildStepId, BuildStep>>;
}

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

const STEPS: [BuildStepId, string][] = [["brief", "Check the approved brief"], ["source", "Validate workbook evidence"],
  ["calculate", "Calculate the dashboard view"], ["save", "Save this dashboard"]];
const list = (v: unknown) => (Array.isArray(v) ? v.map(String) : []);
const n = (v: unknown) => (typeof v === "number" ? v : 0);

/** The facts a completed checkpoint reported, in plain words. Nothing here comes from the review: only from this build. */
function factLines(id: BuildStepId, f: Record<string, unknown> = {}): string[] {
  switch (id) {
    case "brief": {
      const period = f.period as { start?: string; end?: string } | undefined;
      const when = period?.start ? periodText({ period, first_month: period.start, last_month: period.end } as unknown as BuildReceipt) : "";
      return [[places(list(f.products), "products"), places(list(f.markets), "markets")].filter(Boolean).join(" in ") + (when ? ` · ${when}` : ""),
        list(f.measures).join(" · ")].filter(Boolean);
    }
    case "source":
      return [`${plural(n(f.rows), "source row")} in ${String(f.sheet ?? "the workbook")}, ${String(f.first)} to ${String(f.last)} (${plural(n(f.months), "month")})`,
        `${n(f.actual_like)} actual-like and ${n(f.forecast_like)} forecast-like synthetic records, checked for gaps, duplicates and valid numbers`];
    case "calculate": {
      const groups = list(f.groups);
      return [`${plural(n(f.points), "monthly point")} in ${plural(groups.length, "group")}: ${groups.join(", ")}`,
        list(f.measures).join(" · "), String(f.arrangement ?? "")].filter(Boolean);
    }
    case "save":
      return ["Saved as this request's own dashboard.", String(f.title ?? "")].filter(Boolean);
  }
}

const STATE_TEXT = { pending: "Not started", running: "In progress", complete: "Done", failed: "Stopped", earlier: "Done earlier" };

export function BuildHandoff({ session, conversationId, onRetry, onReviewUpdated, onReload, onFinished }: {
  session: BuildSession; conversationId: string; onRetry: () => void; onReviewUpdated: () => void; onReload: () => void;
  /** The hand-off is over: the dashboard opened, or opening by itself is no longer allowed. */
  onFinished: () => void;
}) {
  const { phase, brief, steps, mode } = session;
  const [autoOpen, setAutoOpen] = useState(true);  // permission to take over the screen
  const opened = useRef(false);
  const finished = useRef(false);
  const heading = useRef<HTMLHeadingElement>(null);
  const panel = useRef<HTMLElement>(null);
  const current = useCurrentConversation();

  const finish = () => { if (!finished.current) { finished.current = true; onFinished(); } };

  // On approval: bring the heading into view inside Ask's pane (only in a visible Ask), and load the destination's code.
  useEffect(() => {
    void import("../../pages/SavedDashboardPage");
    if (!stillHere(conversationId)) return;
    heading.current?.focus({ preventScroll: true });
    panel.current?.scrollIntoView({ block: "nearest" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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

  // The committed result: start the destination's one canonical read and open it once, if this attempt still owns the screen.
  const saved = phase.kind === "saved" ? phase : null;
  useEffect(() => {
    if (!saved || opened.current) return;
    prefetchDashboard(saved.dashboardId);
    if (autoOpen && stillHere(conversationId)) {
      opened.current = true;
      finish();
      openDashboard(saved.dashboardId);
    } else {
      setAutoOpen(false);
      finish();  // the parent may now show the saved result; this panel offers the ordinary link
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [saved?.dashboardId, autoOpen]);
  useEffect(() => { if (phase.kind === "failed") finish(); }, [phase.kind]);  // eslint-disable-line react-hooks/exhaustive-deps

  const status = phase.kind === "saving" ? "Building your dashboard…"
    : phase.kind === "saved" ? (opened.current ? "Dashboard saved. Opening it…" : "Dashboard saved")
    : phase.uncertain ? "Save could not be confirmed" : "The dashboard was not saved";
  const showLink = saved && !opened.current && !autoOpen;
  const r = brief.receipt;
  const rows: { id: string; title: string; state: keyof typeof STATE_TEXT; lines: string[] }[] = mode === "single"
    ? [{ id: "all", title: "Check and save your dashboard", lines: phase.kind === "saved" ? ["Saved as this request's own dashboard."] : [],
         state: phase.kind === "saving" ? "running" : phase.kind === "saved" ? "complete" : "failed" }]
    : STEPS.map(([id, title]) => {
        const step = steps[id];
        const earlier = saved?.replayed && !step;
        const state = earlier ? "earlier" : step?.status ?? (phase.kind === "failed" ? "pending" : "pending");
        return { id, title, state, lines: step?.status === "complete" ? factLines(id, step.facts) : earlier ? ["Completed when this approval was first saved."] : [] };
      });
  const announce = phase.kind === "saving" ? (STEPS.find(([id]) => steps[id]?.status === "running")?.[1] ?? "") : status;

  // A double click on Build would otherwise select a word in this panel, which replaces the button.
  return <section ref={panel} className={`bw bw-${phase.kind}`} aria-labelledby={`bw-${session.id}`}
    onMouseDown={e => { if (e.detail > 1) e.preventDefault(); }}>
    <h3 id={`bw-${session.id}`} ref={heading} tabIndex={-1}>How your dashboard is prepared</h3>
    <p className="bw-status">{phase.kind === "saving" && <span className="bh-spinner" aria-hidden="true" />}<strong>{status}</strong></p>
    {phase.kind === "failed" && <div className="db-error" role="alert">
      <p>{phase.message}</p>
      {phase.recovery === "review" ? <button type="button" className="btn-outline" onClick={onReviewUpdated}>Review updated brief</button>
        : phase.recovery === "retry" ? <button type="button" className="btn-outline" onClick={onRetry}>Try building again</button>
        : <button type="button" className="btn-outline" onClick={onReload}>Reload the brief</button>}
    </div>}
    {showLink && <a className="btn" href={dashboardUrl(saved.dashboardId)}
      onClick={e => { if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return; e.preventDefault(); opened.current = true; openDashboard(saved.dashboardId); }}>
      Open saved dashboard</a>}
    {r && <p className="bw-context">Approved brief: {[scopeText(r), periodText(r)].filter(Boolean).join(" · ")}</p>}
    <ol className="bw-steps">{rows.map((row, i) => <li key={row.id} className={`bw-step bws-${row.state}`}>
      <span className="bw-num" aria-hidden="true">{row.state === "running" ? <span className="bh-spinner" /> : row.state === "complete" || row.state === "earlier" ? "✓" : i + 1}</span>
      <div className="bw-body">
        <p className="bw-title">{row.title} <span className="bw-state">{STATE_TEXT[row.state]}</span></p>
        {row.lines.map((l, j) => <p key={j} className="bw-line">{l}</p>)}
      </div>
    </li>)}</ol>
    {/* One short announcement per meaningful change. */}
    <p className="sr-only" role="status" aria-live="polite">{announce}</p>
  </section>;
}
