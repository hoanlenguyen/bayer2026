import type { ProcessingEvent, StageEvent, StageId } from "../../api/types";

/* The steps of one Ask turn, under the message that started it. Every state comes from the stream: a row is running only
   after the server announced its start and before its result arrived, and done rows keep the summary of what that step
   found. The rows stay as completed evidence after the question or recommendation appears. No timer is involved. */

type Stages = Partial<Record<StageId, StageEvent>>;
export type TurnPhase = ProcessingEvent["phase"] | "sent" | null;

const ROWS: [StageId, string][] = [
  ["intent", "Understand the request"], ["kpis", "Resolve metric definitions"], ["discovery", "Find and assess existing analytics"],
  ["lineage", "Trace data dependencies"], ["governance", "Check trust and ownership"], ["migration", "Check Tableau migration"],
  ["decision", "Prepare the recommendation and follow-up"],
];

const UNDERSTAND: Record<string, string> = {
  sent: "Sending your message…", relevance: "Checking your message…", intent: "Reading your answer…",
  scope: "Checking the example scope…", periods: "Checking which workbook months are covered…",
};

type RowState = "pending" | "running" | "done" | "waiting" | "not_needed" | "failed";
const LABEL: Record<RowState, string> = { pending: "Not started", running: "In progress", done: "Done", waiting: "Waiting for your answer",
  not_needed: "Not needed", failed: "Stopped" };

/** `active`: this turn's request is still open. `phase`: real work started inside Understand before a stage event. */
export function LiveSteps({ stages, active, phase, failed }: { stages: Stages; active: boolean; phase: TurnPhase; failed?: boolean }) {
  const intent = stages.intent;
  const state = (id: StageId): RowState => {
    if (id === "intent") {
      if (active && intent?.status !== "done") return "running";  // the request, an answer or a check is being processed
      if (!intent) return active ? "running" : failed ? "failed" : "pending";
      if (intent.status === "waiting") return "waiting";
      return intent.status === "running" ? (failed ? "failed" : "running") : "done";
    }
    if (id === "decision") {  // the recommendation and its follow-up proposals are one row
      const d = stages.decision, a = stages.actions;
      if (a?.status === "done" || (d?.status === "done" && !active)) return "done";
      if (d || a) return failed ? "failed" : "running";
      return "pending";
    }
    const s = stages[id];
    if (!s) return "pending";
    if (s.status === "running") return failed ? "failed" : "running";
    if (id === "migration" && /^not needed/i.test(s.summary ?? "")) return "not_needed";
    return "done";
  };
  const understood = intent?.status === "done";
  const rows = understood ? ROWS : ROWS.slice(0, 1);
  const summary = (id: StageId, st: RowState) => {
    if (st === "running") return id === "intent" ? UNDERSTAND[phase ?? "sent"] ?? intent?.summary : stages[id]?.summary;
    if (st === "done" || st === "not_needed") return id === "decision" ? stages.decision?.summary : stages[id]?.summary;
    if (st === "waiting") return intent?.summary;
    return "";
  };
  const current = rows.find(([id]) => state(id) === "running");
  return <div className="steps-live" aria-label="Steps for this request">
    <ol>{rows.map(([id, title]) => {
      const st = state(id), text = summary(id, st);
      return <li key={id} className={`sl-row sl-${st}`}>
        <span className="sl-mark" aria-hidden="true">{st === "running" ? <span className="spinner" /> : st === "done" ? "✓" : st === "not_needed" ? "–" : st === "failed" ? "!" : ""}</span>
        <div><p className="sl-title">{title} <span className="sl-state">{LABEL[st]}</span></p>{text && <p className="sl-sum">{text}</p>}</div>
      </li>;
    })}</ol>
    {!understood && intent?.status === "waiting" && !active && <p className="sl-note">The catalog checks start once the request is clear.</p>}
    {/* One concise announcement: the step now running. */}
    <p className="sr-only" role="status" aria-live="polite">{active && current ? `${current[1]}: in progress` : ""}</p>
  </div>;
}
