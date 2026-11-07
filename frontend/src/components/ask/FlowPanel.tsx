import { useEffect, useState } from "react";
import type { CatalogMeta, DecisionType, Health, StageEvent, StageId } from "../../api/types";
import { Icon } from "../Icon";
import { RecommendationChip } from "./RecommendationChip";
import { currentTriage, TriageTags } from "./TriageStrip";
import { StageDetail } from "./StageDetail";

/** Who does the work in each stage. Mirrors the legend in SinceAI's reference pipeline. */
const STAGE_KIND: Record<StageId, { label: string; cls: string }> = {
  intent: { label: "Intent agent", cls: "kind-ai" },
  kpis: { label: "KPI_Catalog", cls: "kind-state" },
  discovery: { label: "Analytics_Assets + Asset_Usage", cls: "kind-state" },
  lineage: { label: "Semantic_Models + Lineage_Edges", cls: "kind-state" },
  governance: { label: "Governance_Signals + Data_Quality", cls: "kind-state" },
  migration: { label: "Migration_Backlog", cls: "kind-state" },
  decision: { label: "Python", cls: "kind-py" },
  actions: { label: "Python", cls: "kind-py" },
  deliver: { label: "Python", cls: "kind-py" },
};

const TITLES: Record<StageId, string> = {
  intent: "Parse business question",
  kpis: "Resolve metric definitions",
  discovery: "Find existing analytics",
  lineage: "Trace data dependencies",
  governance: "Check trust and ownership",
  migration: "Handle Tableau → Power BI",
  decision: "Recommend what to do",
  actions: "Suggest follow-up work",
  deliver: "Show the matched catalogue record",
};

const NATIVE_STEP_TITLES: Partial<Record<StageId, string>> = {
  discovery: "Search the imported BI catalog",
  lineage: "Trace dependencies in the imported catalog",
  governance: "Check governance of the imported candidate",
  migration: "Check imported Tableau reports",
  deliver: "Open the matched employee report",
};

export const RUNNING_COPY: Record<StageId, string> = {
  intent: "Reading your question",
  kpis: "Resolving metric definitions",
  discovery: "Looking through the catalog",
  lineage: "Tracing data dependencies",
  governance: "Checking trust and ownership",
  migration: "Checking for Tableau reports",
  decision: "Applying the decision rules",
  actions: "Suggesting follow-up work",
  deliver: "Loading catalogue details",
};

const BASE: StageId[] = ["intent", "kpis", "discovery", "lineage", "governance", "migration", "decision"];
const TECH_KEY = "am.technical";
const COLLAPSED_KEY = "am.flow.collapsed";

function stagesFor(decision: DecisionType | null, hasActions: boolean): StageId[] {
  const base: StageId[] = hasActions ? [...BASE, "actions"] : BASE;
  return decision === "reuse" ? [...base, "deliver"] : base;
}

function readCollapsed() {
  try { return localStorage.getItem(COLLAPSED_KEY) === "1"; } catch { return false; }
}

function readTechnical() {
  try { return localStorage.getItem(TECH_KEY) === "1"; } catch { return false; }
}

/** The recommendation step shows its outcome, and the Tableau step its per-report outcomes, as chips instead of a sentence. */
function recommendationChips(ev: StageEvent | undefined) {
  if (ev?.status !== "done") return null;
  if (ev.stage === "decision") return <RecommendationChip value={String(ev.data?.decision)} />;
  const counts: Record<string, number> = ev.stage === "migration" ? ev.data?.step?.data?.counts ?? {} : {};
  const entries = Object.entries(counts);
  if (entries.length === 0) return null;
  return entries.map(([value, count]) => <RecommendationChip key={value} value={value} count={count} />);
}

function summaryFor(ev: StageEvent | undefined, technical: boolean): string | null {
  if (!ev) return null;
  if (technical) return ev.summary;
  if (ev.status === "running") return null;
  if (ev.stage === "actions") return `${ev.data?.proposals?.length ?? 0} suggestions`;
  return ev.summary;
}


/** The steps of one request, each opening to its evidence. */
function StepList({ stages, decision, catalog, technical }: { stages: Partial<Record<StageId, StageEvent>>; decision: DecisionType | null; catalog: CatalogMeta | null; technical: boolean }) {
  const triage = currentTriage(stages);
  const order = stagesFor(decision, (stages.actions?.data?.proposals?.length ?? 0) > 0);
  const [open, setOpen] = useState<Set<StageId>>(new Set());
  const toggle = (s: StageId) => setOpen((prev) => {
    const next = new Set(prev);
    if (next.has(s)) next.delete(s); else next.add(s);
    return next;
  });
  return (
    <ol className="flow-steps">
      {order.map((id) => {
        const ev = stages[id];
        const status = ev?.status ?? "pending";
        const isOpen = open.has(id) && !!ev?.data;
        const summary = summaryFor(ev, technical);
        const chips = recommendationChips(ev);
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
                <span className="flow-name">{stages.decision?.data?.employee_report
                  ? (NATIVE_STEP_TITLES[id] ?? TITLES[id]) : TITLES[id]}</span>
                {technical && <span className={`kind ${STAGE_KIND[id].cls}`}>{STAGE_KIND[id].label}</span>}
                {ev?.data && <span className={`flow-chevron${isOpen ? " open" : ""}`}><Icon name="chevron" size={14} /></span>}
              </button>
              {summary && !chips && <p className="flow-summary">{summary}</p>}
              {chips && <div className="rec-chips">{chips}</div>}
              {id === "intent" && triage &&<div className="flow-tags"><TriageTags triage={triage} compact only="urgency" /></div>}
              {id === "decision" && status === "done" && triage?.status && <div className="flow-tags"><TriageTags triage={triage} compact only="status" /></div>}
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
            <span className="flow-name">Then: a recommendation with its evidence</span>
          </div>
        </li>
      )}
    </ol>
  );
}

export interface FlowGroup {
  key: string;
  title: string;
  stages: Partial<Record<StageId, StageEvent>>;
  decision: DecisionType | null;
}

interface Props {
  stages: Partial<Record<StageId, StageEvent>>;
  decision: DecisionType | null;
  health: Health | null;
  catalog: CatalogMeta | null;
  /** Several requests, one accordion each, numbered (1), (2)... Used by the conversation simulation. */
  groups?: FlowGroup[];
  /** The group to open and scroll to, such as the newest answer. */
  focusGroup?: string | null;
  /** Changes on every request to focus, so asking again reopens a group someone closed. */
  focusTick?: number;
}

export function FlowPanel({ stages, decision, health, catalog, groups, focusGroup, focusTick }: Props) {
  const [openGroup, setOpenGroup] = useState<string | null>(null); // one at a time
  const [technical, setTechnical] = useState(readTechnical);
  const [collapsed, setCollapsed] = useState(readCollapsed);

  const toggleCollapsed = () => {
    setCollapsed((on) => {
      try { localStorage.setItem(COLLAPSED_KEY, on ? "0" : "1"); } catch { /* preference only lasts this visit */ }
      return !on;
    });
  };

  const toggleGroup = (key: string) => setOpenGroup((prev) => (prev === key ? null : key));

  useEffect(() => {
    if (!focusGroup) return;
    setCollapsed(false); // a hidden panel can't show what was asked for
    setOpenGroup(focusGroup);
    requestAnimationFrame(() => document.getElementById(`flow-group-${focusGroup}`)?.scrollIntoView({ block: "start", behavior: "smooth" }));
  }, [focusGroup, focusTick]);

  const toggleTechnical = () => {
    setTechnical((on) => {
      try { localStorage.setItem(TECH_KEY, on ? "0" : "1"); } catch { /* preference only lasts this visit */ }
      return !on;
    });
  };

  return (
    <aside className={`flow-panel${collapsed ? " collapsed" : ""}`} aria-label="How this was decided">
      <div className="pane-head">
        <h2>How this was decided</h2>
        <div className="flow-head-actions">
        <button type="button" className="switch" role="switch" aria-checked={technical} onClick={toggleTechnical}>
          Technical details<span className="switch-track" aria-hidden="true" />
        </button>
          <button type="button" className="flow-collapse" aria-expanded={!collapsed} aria-label={collapsed ? "Show how this was decided" : "Hide how this was decided"} title={collapsed ? "Show how this was decided" : "Hide how this was decided"} onClick={toggleCollapsed}>
            <Icon name="panel" />
          </button>
        </div>
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

        {groups ? (
          groups.length === 0 ? (
            <p className="flow-groups-empty">Each answer from AnalytIQ will show its steps here.</p>
          ) : (
            <ol className="flow-groups">
              {groups.map((g, i) => {
                const isOpen = openGroup === g.key;
                return (
                  <li key={g.key} id={`flow-group-${g.key}`} className="flow-group">
                    <button type="button" className="flow-group-head" aria-expanded={isOpen} onClick={() => toggleGroup(g.key)}>
                      <span className="flow-group-num">({i + 1})</span>
                      <span className="flow-group-title">{g.title}</span>
                      {g.decision && <RecommendationChip value={g.decision} />}
                      <span className={`flow-chevron${isOpen ? " open" : ""}`}><Icon name="chevron" size={14} /></span>
                    </button>
                    {isOpen && <StepList stages={g.stages} decision={g.decision} catalog={catalog} technical={technical} />}
                  </li>
                );
              })}
            </ol>
          )
        ) : (
          <StepList stages={stages} decision={decision} catalog={catalog} technical={technical} />
        )}

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
