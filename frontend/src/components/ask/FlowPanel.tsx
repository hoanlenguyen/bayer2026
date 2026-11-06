import { useEffect, useState } from "react";
import type { CatalogMeta, DecisionType, Health, StageEvent, StageId } from "../../api/types";
import { Icon } from "../Icon";
import { StageDetail } from "./StageDetail";

/** Who does the work in each stage. Mirrors the legend in Bayer's reference pipeline. */
const STAGE_KIND: Record<StageId, { label: string; cls: string }> = {
  intent: { label: "Intent agent", cls: "kind-ai" },
  discovery: { label: "Catalog + Python", cls: "kind-state" },
  governance: { label: "Python", cls: "kind-py" },
  decision: { label: "Python", cls: "kind-py" },
  deliver: { label: "Python", cls: "kind-py" },
  evidence: { label: "Evidence agent", cls: "kind-ai" },
  spec: { label: "Spec agent", cls: "kind-ai" },
  approval: { label: "Human", cls: "kind-human" },
  render: { label: "Python", cls: "kind-py" },
  register: { label: "Python", cls: "kind-py" },
};

const TITLES: Record<StageId, string> = {
  intent: "Understand the request",
  discovery: "Find existing reports",
  governance: "Check they can be trusted",
  decision: "Decide what to do",
  deliver: "Open the existing report",
  evidence: "Check the data sources",
  spec: "Design the report",
  approval: "Get approval",
  render: "Create the report files",
  register: "Add to the catalog",
};

export const RUNNING_COPY: Record<StageId, string> = {
  intent: "Reading your question",
  discovery: "Looking through the catalog",
  governance: "Checking ownership and certification",
  decision: "Applying the decision rules",
  deliver: "Opening the report",
  evidence: "Checking the data sources",
  spec: "Designing the report",
  approval: "Waiting for approval",
  render: "Creating the report files",
  register: "Adding it to the catalog",
};

const BASE: StageId[] = ["intent", "discovery", "governance", "decision"];
const BUILD: StageId[] = ["evidence", "spec", "approval", "render", "register"];
const TECH_KEY = "am.technical";

function stagesFor(decision: DecisionType | null): StageId[] {
  if (decision === "reuse") return [...BASE, "deliver"];
  if (decision === "extend" || decision === "create") return [...BASE, ...BUILD];
  return BASE;
}

function readTechnical() {
  try { return localStorage.getItem(TECH_KEY) === "1"; } catch { return false; }
}

function summaryFor(ev: StageEvent | undefined, technical: boolean): string | null {
  if (!ev) return null;
  if (technical) return ev.summary;
  if (ev.status === "running") return null;
  if (ev.stage === "render" && ev.data?.files) return `${ev.data.files.length} files created`;
  return ev.summary;
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
  const [technical, setTechnical] = useState(readTechnical);

  // What the approver is signing off on opens by itself; everything else stays one click away.
  const awaitingApproval = stages.approval?.status === "waiting";
  useEffect(() => {
    if (awaitingApproval) setOpen((prev) => new Set(prev).add("evidence").add("spec"));
  }, [awaitingApproval]);

  const toggle = (s: StageId) => setOpen((prev) => {
    const next = new Set(prev);
    if (next.has(s)) next.delete(s); else next.add(s);
    return next;
  });

  const toggleTechnical = () => {
    setTechnical((on) => {
      try { localStorage.setItem(TECH_KEY, on ? "0" : "1"); } catch { /* preference only lasts this visit */ }
      return !on;
    });
  };

  return (
    <aside className="flow-panel" aria-label="How this was decided">
      <div className="pane-head">
        <h2>How this was decided</h2>
        <button type="button" className="switch" role="switch" aria-checked={technical} onClick={toggleTechnical}>
          Technical details<span className="switch-track" aria-hidden="true" />
        </button>
      </div>

      <div className="flow-scroll">
        {technical && health && (
          <div className="flow-badges">
            <span className="badge" title={health.models ? `${health.models.reasoning} / ${health.models.fast}` : "Rule-based, runs offline"}>
              {health.provider === "openai" ? "OpenAI" : "Mock model"}
            </span>
            <span className="badge">{health.store === "mongodb" ? "MongoDB" : "In-memory store"}</span>
          </div>
        )}

        <ol className="flow-steps">
          {order.map((id) => {
            const ev = stages[id];
            const status = ev?.status ?? "pending";
            const isOpen = open.has(id) && !!ev?.data;
            const summary = summaryFor(ev, technical);
            return (
              <li key={id} className={`flow-step st-${status}`}>
                <span className="flow-icon" aria-hidden="true">
                  {status === "done" && <Icon name="check" size={12} />}
                  {status === "rejected" && <Icon name="close" size={12} />}
                </span>
                <div className="flow-body">
                  <button
                    type="button"
                    className="flow-title"
                    onClick={() => ev?.data && toggle(id)}
                    aria-expanded={ev?.data ? isOpen : undefined}
                    disabled={!ev?.data}
                  >
                    <span className="flow-name">{TITLES[id]}</span>
                    {technical && <span className={`kind ${STAGE_KIND[id].cls}`}>{STAGE_KIND[id].label}</span>}
                    {ev?.data && <span className={`flow-chevron${isOpen ? " open" : ""}`}><Icon name="chevron" size={14} /></span>}
                  </button>
                  {summary && <p className="flow-summary">{summary}</p>}
                  {status === "pending" && <span className="sr-only">Not started</span>}
                  {isOpen && <div className="flow-detail"><StageDetail stage={id} data={ev!.data} catalog={catalog} technical={technical} /></div>}
                </div>
              </li>
            );
          })}
          {!decision && (
            <li className="flow-step st-pending flow-branch">
              <span className="flow-icon" aria-hidden="true" />
              <div className="flow-body">
                <span className="flow-name">Then: reuse a report, or build one after your approval</span>
              </div>
            </li>
          )}
        </ol>

        {technical && (
          <div className="flow-legend" aria-label="Legend">
            <span className="kind kind-ai">AI agent</span>
            <span className="kind kind-py">Deterministic Python</span>
            <span className="kind kind-human">Human</span>
            <span className="kind kind-state">Catalog</span>
          </div>
        )}
      </div>
    </aside>
  );
}
