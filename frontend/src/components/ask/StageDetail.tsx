import type { ActionProposal, Candidate, CatalogMeta, StageId } from "../../api/types";
import { RecommendationChip } from "./RecommendationChip";

const pct = (v: number) => `${Math.round(v * 100)}%`;
const tone = (v: number, good = 0.9, ok = 0.6) => (v >= good ? "ok" : v >= ok ? "warn" : "bad");

function names(ids: string[] = [], kind: "m" | "d", catalog: CatalogMeta | null): string {
  if (!ids.length) return "None";
  const src = kind === "m" ? catalog?.measures : catalog?.dimensions;
  return ids.map((i) => src?.[i]?.name ?? i).join(", ");
}

function Score({ label, value, good }: { label: string; value: number; good?: number }) {
  return (
    <span className={`score tone-${tone(value, good)}`} title={label}>
      <span className="score-k">{label}</span>
      <span className="score-v">{pct(value)}</span>
    </span>
  );
}

function KV({ rows }: { rows: [string, React.ReactNode][] }) {
  return (
    <dl className="kv">
      {rows.map(([k, v]) => (
        <div key={k}><dt>{k}</dt><dd>{v}</dd></div>
      ))}
    </dl>
  );
}

/** Named values, or what the request implies when it names none: "by product" means every product. */
function scope(values: string[], breakdown: string[], dimension: string, all: string): string {
  if (values.length) return values.join(", ");
  return breakdown.some((b) => b.startsWith(dimension)) ? all : "Not specified";
}

const REPORT_STATUS: Record<string, string> = {
  usable: "ready to use",
  needs_repair: "needs repair",
  needs_migration: "needs moving to Power BI",
  needs_review: "needs a human decision",
  retire: "should be retired",
};

function existingReport(t: any): string {
  const { status, report } = t.existing_report_detail;
  if (t.existing_report === "yes") return report ? `Yes: ${report.name}, ${REPORT_STATUS[status] ?? status}` : "Yes";
  return status === "partial_match" && report ? `No. Closest: ${report.name}, covers part of it` : "No";
}

/** The request's classification, in the same order as POST /api/v2/classify. */
function classificationRows(t: any): [string, React.ReactNode][] {
  const model = t.semantic_model;
  return [
    ["Domain", t.domain ?? "Not specified"],
    ["Market", scope(t.market, t.breakdown, "Market", "All markets")],
    ["Product", scope(t.product, t.breakdown, "Product", "All products")],
    ["Governed KPIs", t.governed_kpis.length
      ? t.governed_kpis.map((k: { kpi_id?: string; name: string }) => (k.kpi_id ? `${k.name} (${k.kpi_id})` : k.name)).join(", ")
      : "None found"],
    // Known from the catalog assessment on; a clarification shows only what the request itself says.
    ...("semantic_model" in t ? [["Semantic model", model ? `${model.name} (${model.id})${model.serves_all_kpis ? "" : ", does not serve every KPI"}` : "None found"] as [string, React.ReactNode],
      ["Existing report", existingReport(t)] as [string, React.ReactNode]] : []),
  ];
}

interface AnalysisStep {
  step: number;
  sheets: string[];
  task: string;
  output: string;
  summary: string;
  findings: string[];
}

/** One step's findings from the data pack. */
function StepFindings({ step, technical }: { step?: AnalysisStep; technical: boolean }) {
  if (!step) return null;
  return (
    <>
      {technical && <p className="muted small">Sheets: {step.sheets.join(", ")}. Output: {step.output}.</p>}
      {step.findings.length > 0 ? <ul className="step-findings">{step.findings.map((f) => <li key={f}>{f}</li>)}</ul> : <p className="muted">{step.summary}</p>}
    </>
  );
}

interface AgentTraceData {
  agent: string;
  mode: "jev" | "llm" | "rules";
  model: string;
  ms: number;
  usage?: { input_tokens: number; output_tokens: number; calls: number } | null;
  fallback_reason: string | null;
  steps: { kind: string; name: string; detail: string; ok: boolean }[];
}

const STEP_LABEL: Record<string, string> = { tool: "Tool", model: "Model", rule: "Rule", check: "Check", note: "Note" };

/** What the agent did: every tool call, model call and Python check, in order. */
function AgentTrace({ trace }: { trace: AgentTraceData }) {
  return (
    <details className="agent-trace" open={trace.steps.length <= 4}>
      <summary>
        <span className="agent-name">{trace.agent}</span>
        <span className={`badge mode-${trace.mode}`}>{trace.mode === "rules" ? "rules, no model" : trace.model}</span>
        <span className="muted small">
          {trace.steps.length} steps · {trace.ms} ms
          {trace.usage && trace.usage.calls > 0 && ` · ${(trace.usage.input_tokens + trace.usage.output_tokens).toLocaleString("en-US")} tokens`}
        </span>
      </summary>
      {trace.fallback_reason && <p className="text-warn small">Model failed, used rules instead: {trace.fallback_reason}</p>}
      <ol className="steps">
        {trace.steps.map((st, i) => (
          <li key={i} className={st.ok ? "" : "step-bad"}>
            <span className={`step-kind sk-${st.kind}`}>{STEP_LABEL[st.kind] ?? st.kind}</span>
            <span className="step-text">
              <code>{st.name}</code>
              {st.detail && <span className="muted"> → {st.detail}</span>}
            </span>
          </li>
        ))}
      </ol>
    </details>
  );
}

interface Props {
  stage: StageId;
  data: any;
  catalog: CatalogMeta | null;
  /** Agent traces, rules, weights and raw files. Off by default for plant staff. */
  technical: boolean;
}

export function StageDetail({ stage, data, catalog, technical }: Props) {
  switch (stage) {
    case "intent":
      return (
        <div className="detail-stack">
        {technical && data.agent && <AgentTrace trace={data.agent} />}
        <KV rows={[
          ["Decision", data.decision ?? "Not yet known"],
          ...(data.triage ? [["Urgency", `${data.triage.urgency.value} (${data.triage.urgency.source}${data.triage.urgency.evidence ? `: “${data.triage.urgency.evidence}”` : ""})`] as [string, string]] : []),
          ...(data.classification ? classificationRows(data.classification) : [["Numbers", names(data.measures, "m", catalog)] as [string, string]]),
          ["Broken down by", names(data.dimensions, "d", catalog)],
          ["Time grain", data.grain ?? "Not yet known"],
          ...(!data.classification && Object.keys(data.filters ?? {}).length
            ? [["Filters", Object.entries(data.filters).map(([k, v]) => `${k} = ${v}`).join(", ")] as [string, string]]
            : []),
          ...(!data.classification && data.department ? [["Department", data.department] as [string, string]] : []),
          ...(data.unmatched_terms?.length ? [["Not in catalog", data.unmatched_terms.join(", ")] as [string, string]] : []),
          ...(data.triage ? [
            ...(data.triage.similar ? [["Earlier requests", data.triage.similar.duplicate_count
              ? `same as ${data.triage.similar.duplicate_count} in the queue`
              : data.triage.similar.similar?.length ? `similar to one asked ${data.triage.similar.similar[0].asked} times` : "none found"] as [string, string]] : []),
            ...(technical && data.triage.similar ? [["Vector search", `${data.triage.similar.embedder} embeddings, ${data.triage.similar.search === "atlas" ? "MongoDB Atlas Vector Search" : "in-memory search"}`] as [string, string]] : []),
          ] : []),
        ]} />
        </div>
      );

    case "kpis":
    case "lineage":
      return <div className="detail-stack"><StepFindings step={data.step} technical={technical} /></div>;

    case "migration": {
      const rows: { id: string; name: string; recommendation: string; reason: string }[] = data.step?.data?.assets ?? [];
      if (rows.length === 0) return <div className="detail-stack"><StepFindings step={data.step} technical={technical} /></div>;
      return (
        <div className="detail-stack">
          {technical && <p className="muted small">Sheets: {data.step.sheets.join(", ")}. Output: {data.step.output}.</p>}
          <ul className="rec-list">
            {rows.slice(0, data.step.findings.length).map((r) => (
              <li key={r.id}>
                <RecommendationChip value={r.recommendation} />
                <span><strong>{r.name}</strong><span className="muted">: {r.reason}</span></span>
              </li>
            ))}
          </ul>
        </div>
      );
    }

    case "discovery": {
      const cands: Candidate[] = data.candidates ?? [];
      return (
        <div className="detail-stack">
          <StepFindings step={data.step} technical={technical} />
          <p className="muted">Searched {data.searched} catalog assets. Scores compare each report with your request.</p>
          {cands.length === 0 && <p className="muted">No existing report uses these numbers.</p>}
          {cands.map((c) => (
            <div key={c.asset_id} className="cand">
              <div className="cand-head"><strong>{c.name}</strong></div>
              <div className="scores">
                <Score label="Coverage" value={c.coverage} />
                <Score label="Freshness" value={c.freshness} />
                <Score label="Governance" value={c.governance} good={0.8} />
              </div>
              {c.scope_note && <p className="muted small">{c.scope_note}</p>}
              {(c.measures_missing.length > 0 || (c.dimensions_missing?.length ?? 0) > 0 || c.grain_supported === false) && (
                <p className="muted small">
                  Missing: {[...c.measures_missing.map((m) => catalog?.measures[m]?.name ?? m),
                    ...(c.dimensions_missing ?? []).map((d) => catalog?.dimensions[d]?.name ?? d),
                    ...(c.grain_supported === false ? ["finer time grain"] : [])].join(", ")}
                </p>
              )}
            </div>
          ))}
          {!data.availability?.available && (
            <p className="text-warn small">
              Data not available: {[...(data.availability?.missing_terms ?? []), ...(data.availability?.missing_dimensions ?? [])].join(", ") || "no catalog measures matched"}
            </p>
          )}
        </div>
      );
    }

    case "governance":
      return (
        <div className="detail-stack">
          <StepFindings step={data.step} technical={technical} />
          {(data.candidates ?? []).map((c: Candidate) => (
            <div key={c.asset_id} className="cand">
              <div className="cand-head"><strong>{c.name}</strong><Score label="Score" value={c.governance} good={0.8} /></div>
              <ul className="checks">
                {c.checks.map((k) => (
                  <li key={k.id} className={k.passed ? "pass" : "fail"}>
                    <span aria-hidden="true">{k.passed ? "✓" : "✕"}</span> {k.label}
                    {technical && <span className="muted"> ({k.weight.toFixed(2)})</span>}
                  </li>
                ))}
              </ul>
              {(c.gates_failed ?? []).map((g) => <p key={g} className="text-bad small">Blocked: {g}</p>)}
            </div>
          ))}
        </div>
      );

    case "decision":
      return (
        <div className="detail-stack">
          <p>{data.reason}</p>
          <p className="rule"><span className="muted">Rule applied: </span>{data.rule}</p>
          {data.triage?.status && (
            <KV rows={[
              ["Status", data.triage.status === "triaged" ? "Triaged" : "New"],
              ...(data.triage.request_id ? [["Request", data.triage.request_id] as [string, string]] : []),
              ...(technical && data.triage.request_store ? [["Saved for search", data.triage.request_store === "atlas"
                ? "MongoDB Atlas (request_vectors)" : "in-memory, until the backend restarts"] as [string, string]] : []),
            ]} />
          )}
          {technical && (
            <details className="thresholds">
              <summary>Thresholds</summary>
              <KV rows={Object.entries(data.thresholds ?? {}).map(([k, v]) => [k.replace(/_/g, " "), String(v)])} />
            </details>
          )}
        </div>
      );

    case "actions":
      return (
        <div className="detail-stack">
          <p className="muted">Suggested work for a person to review.</p>
          {(data.proposals ?? []).map((p: ActionProposal) => (
            <div key={p.key} className="cand">
              <div className="cand-head"><strong>{p.title}</strong></div>
              <p className="muted small">{p.owner} · due {p.due_date}</p>
            </div>
          ))}
        </div>
      );

    case "deliver": {
      const employee = data.employee_report;
      if (employee) return <KV rows={[
        ["Employee report", employee.title], ["Scope", "Nubeqa · Germany · Monthly"],
        ["KPI definition", employee.kpi_id], ["Owner", employee.owner],
        ["Latest source period", employee.period],
      ]} />;
      const a = data.asset;
      return (
        <KV rows={[
          ["Workspace", a.workspace],
          ["Views (90 days)", a.views_90d?.toLocaleString("en-US") ?? "0"],
          [a.last_review ? "Last reviewed" : "Last changed", a.last_review ?? a.last_modified ?? "Not recorded"],
        ]} />
      );
    }

  }
}
