import { useEffect, useState } from "react";
import type { CatalogMeta, DecisionType, Health, StageEvent, StageId } from "../../api/types";
import { StageDetail } from "./StageDetail";

/** Who does the work in each stage. Mirrors the legend in Bayer's reference pipeline. */
const STAGE_KIND: Record<StageId, { label: string; cls: string }> = {
  intent: { label: "AI agent", cls: "kind-ai" },
  discovery: { label: "AI + catalog", cls: "kind-ai" },
  governance: { label: "Python", cls: "kind-py" },
  decision: { label: "Python", cls: "kind-py" },
  deliver: { label: "Python", cls: "kind-py" },
  evidence: { label: "Catalog", cls: "kind-state" },
  spec: { label: "AI + Python", cls: "kind-ai" },
  approval: { label: "Human", cls: "kind-human" },
  render: { label: "Python", cls: "kind-py" },
  register: { label: "Python", cls: "kind-py" },
};

const TITLES: Record<StageId, string> = {
  intent: "Understand the request",
  discovery: "Find existing analytics",
  governance: "Check governance",
  decision: "Decide: reuse, extend or create",
  deliver: "Open the existing report",
  evidence: "Gather evidence",
  spec: "Write the specification",
  approval: "Human approval",
  render: "Generate PBIP files",
  register: "Register in the catalog",
};

const BASE: StageId[] = ["intent", "discovery", "governance", "decision"];
const BUILD: StageId[] = ["evidence", "spec", "approval", "render", "register"];
const AUTO_OPEN: StageId[] = ["intent", "decision", "spec", "render"];

function stagesFor(decision: DecisionType | null): StageId[] {
  if (decision === "reuse") return [...BASE, "deliver"];
  if (decision === "extend" || decision === "create") return [...BASE, ...BUILD];
  return BASE;
}

interface Props {
  stages: Partial<Record<StageId, StageEvent>>;
  decision: DecisionType | null;
  health: Health | null;
  catalog: CatalogMeta | null;
}

export function FlowPanel({ stages, decision, health, catalog }: Props) {
  const order = stagesFor(decision);
  const [open, setOpen] = useState<Set<StageId>>(new Set());

  // Open the important stages automatically as they complete.
  useEffect(() => {
    setOpen((prev) => {
      const next = new Set(prev);
      AUTO_OPEN.forEach((s) => { if (stages[s]?.status === "done" || stages[s]?.status === "waiting") next.add(s); });
      if (stages.intent?.status === "done" && stages.decision) next.delete("intent");
      return next;
    });
  }, [stages]);

  const toggle = (s: StageId) => setOpen((prev) => {
    const next = new Set(prev);
    if (next.has(s)) next.delete(s); else next.add(s);
    return next;
  });

  const started = Object.keys(stages).length > 0;

  return (
    <aside className="flow-panel" aria-label="Processing flow">
      <div className="flow-head">
        <h2>Processing flow</h2>
        {health && (
          <div className="flow-badges">
            <span className="badge" title={health.models ? `${health.models.reasoning} / ${health.models.fast}` : "Rule-based, runs offline"}>
              {health.provider === "openai" ? "OpenAI" : "Mock model"}
            </span>
            <span className="badge">{health.store === "mongodb" ? "MongoDB" : "In-memory store"}</span>
          </div>
        )}
      </div>

      {!started && (
        <p className="flow-empty">
          Each step appears here as it runs: what the AI understood, which reports already exist, how well they are governed,
          and why the system chose to reuse, extend or create.
        </p>
      )}

      <ol className="flow-steps">
        {order.map((id) => {
          const ev = stages[id];
          const status = ev?.status ?? "pending";
          const isOpen = open.has(id) && !!ev?.data;
          return (
            <li key={id} className={`flow-step st-${status}`}>
              <span className="flow-icon" aria-hidden="true">
                {status === "done" ? "✓" : status === "rejected" ? "✕" : status === "waiting" ? "…" : ""}
              </span>
              <div className="flow-body">
                <button
                  type="button"
                  className="flow-title"
                  onClick={() => ev?.data && toggle(id)}
                  aria-expanded={isOpen}
                  disabled={!ev?.data}
                >
                  <span className="flow-name">{TITLES[id]}</span>
                  <span className={`kind ${STAGE_KIND[id].cls}`}>{STAGE_KIND[id].label}</span>
                </button>
                {ev?.summary && <p className="flow-summary">{ev.summary}</p>}
                {status === "pending" && <span className="sr-only">Not started</span>}
                {isOpen && <div className="flow-detail"><StageDetail stage={id} data={ev!.data} catalog={catalog} /></div>}
              </div>
            </li>
          );
        })}
        {!decision && (
          <li className="flow-step st-pending flow-branch">
            <span className="flow-icon" aria-hidden="true" />
            <div className="flow-body">
              <span className="flow-name">Then: reuse it, or build with evidence → spec → approval → PBIP</span>
            </div>
          </li>
        )}
      </ol>

      <div className="flow-legend" aria-label="Legend">
        <span className="kind kind-ai">AI agent</span>
        <span className="kind kind-py">Deterministic Python</span>
        <span className="kind kind-human">Human</span>
        <span className="kind kind-state">Catalog</span>
      </div>
    </aside>
  );
}
