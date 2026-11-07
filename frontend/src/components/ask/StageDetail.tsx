import type { ActionProposal, Candidate, CatalogMeta, StageId } from "../../api/types";

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

interface AgentTraceData {
  agent: string;
  mode: "llm" | "rules";
  model: string;
  ms: number;
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
        <span className={`badge mode-${trace.mode}`}>{trace.mode === "llm" ? trace.model : "rules, offline"}</span>
        <span className="muted small">{trace.steps.length} steps · {trace.ms} ms</span>
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
          ["Numbers", names(data.measures, "m", catalog)],
          ["Broken down by", names(data.dimensions, "d", catalog)],
          ["Time grain", data.grain ?? "Not yet known"],
          ...(Object.keys(data.filters ?? {}).length
            ? [["Filters", Object.entries(data.filters).map(([k, v]) => `${k} = ${v}`).join(", ")] as [string, string]]
            : []),
          ...(data.department ? [["Department", data.department] as [string, string]] : []),
          ...(data.unmatched_terms?.length ? [["Not in catalog", data.unmatched_terms.join(", ")] as [string, string]] : []),
          ...(data.triage ? [
            ["Status", data.triage.status] as [string, string],
            ["Urgency", `${data.triage.urgency.value} (${data.triage.urgency.source}${data.triage.urgency.evidence ? `: “${data.triage.urgency.evidence}”` : ""})`] as [string, string],
            ...(data.triage.similar ? [["Earlier requests", data.triage.similar.duplicate_count
              ? `same as ${data.triage.similar.duplicate_count} in the queue`
              : data.triage.similar.similar?.length ? `similar to one asked ${data.triage.similar.similar[0].asked} times` : "none found"] as [string, string]] : []),
            ...(technical && data.triage.similar ? [["Vector search", `${data.triage.similar.embedder} embeddings, ${data.triage.similar.search === "atlas" ? "MongoDB Atlas Vector Search" : "in-memory search"}`] as [string, string]] : []),
          ] : []),
        ]} />
        </div>
      );

    case "discovery": {
      const cands: Candidate[] = data.candidates ?? [];
      return (
        <div className="detail-stack">
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
          <p className="muted">Suggestions only. Nothing is assigned, because this screen has no action tracker yet.</p>
          {(data.proposals ?? []).map((p: ActionProposal) => (
            <div key={p.key} className="cand">
              <div className="cand-head"><strong>{p.title}</strong></div>
              <p className="muted small">{p.owner} · due {p.due_date}</p>
            </div>
          ))}
        </div>
      );

    case "deliver": {
      const a = data.asset;
      return (
        <KV rows={[
          ["Workspace", a.workspace],
          ["Views (90 days)", a.views_90d?.toLocaleString("en-US") ?? "0"],
          [a.last_review ? "Last reviewed" : "Last changed", a.last_review ?? a.last_modified ?? "Not recorded"],
        ]} />
      );
    }

    case "evidence":
      return (
        <div className="detail-stack">
          {technical && data.agent && <AgentTrace trace={data.agent} />}
          {data.summary && <p>{data.summary}</p>}
          <strong className="small">Proof from the catalog</strong>
          <ul className="checks">
            {data.proofs.map((p: { ok: boolean; text: string }) => (
              <li key={p.text} className={p.ok ? "pass" : "fail"}><span aria-hidden="true">{p.ok ? "✓" : "!"}</span> {p.text}</li>
            ))}
          </ul>
          {technical && (
            <>
              <strong className="small">Python verification of the agent's choice</strong>
              <ul className="checks">
                {(data.verification ?? []).map((v: { ok: boolean; text: string }) => (
                  <li key={v.text} className={v.ok ? "pass" : "fail"}><span aria-hidden="true">{v.ok ? "✓" : "!"}</span> {v.text}</li>
                ))}
              </ul>
              <KV rows={Object.entries(data.columns as Record<string, string[]>).map(([t, cols]) => [t, <code key={t}>{cols.join(", ")}</code>])} />
            </>
          )}
        </div>
      );

    case "spec":
      return (
        <div className="detail-stack">
          {technical && data.agent && <AgentTrace trace={data.agent} />}
          <KV rows={[
            ["Name", <strong key="n">{data.name}</strong>],
            ["Type", `${data.decision_type}${data.change_type ? ` (${data.change_type})` : ""}`],
            ["Owner", data.owner],
            ["Review date", data.review_date],
            ["Pages", data.pages.map((p: { name: string; visuals: unknown[] }) => `${p.name} (${p.visuals.length} visuals)`).join(", ")],
          ]} />
          {data.rationale && <p className="muted">{data.rationale}</p>}
          {data.validation && (technical || !data.validation.passed) && (
            <details open={!data.validation.passed}>
              <summary>
                Validation: {data.validation.passed ? "all checks pass" : "failed"}
                {data.validation.attempts > 1 ? ` after ${data.validation.attempts} attempts` : ""}
              </summary>
              <ul className="checks">
                {data.validation.checks.map((c: { ok: boolean; text: string }) => (
                  <li key={c.text} className={c.ok ? "pass" : "fail"}><span aria-hidden="true">{c.ok ? "✓" : "✕"}</span> {c.text}</li>
                ))}
              </ul>
            </details>
          )}
          {technical && (
            <details>
              <summary>DashboardSpec (JSON)</summary>
              <pre className="code">{JSON.stringify({ ...data, agent: undefined }, null, 2)}</pre>
            </details>
          )}
        </div>
      );

    case "approval":
      return <KV rows={[["Approver", data.approver], ...(data.approved_at ? [["Approved at", data.approved_at] as [string, string]] : [])]} />;

    case "render":
      return (
        <div className="detail-stack">
          {technical ? (
            <>
              <ul className="files">
                {data.files.map((f: { path: string; bytes: number }) => (
                  <li key={f.path}><code>{f.path}</code><span className="muted">{f.bytes.toLocaleString("en-US")} B</span></li>
                ))}
              </ul>
              <details>
                <summary>Table definition (TMDL preview)</summary>
                <pre className="code">{data.preview.model}</pre>
              </details>
            </>
          ) : (
            <p className="muted">A Power BI project, saved as text files so changes can be tracked.</p>
          )}
          {!data.validated_in_power_bi && <p className="muted small">Skeleton output: not yet opened in Power BI Desktop.</p>}
        </div>
      );

    case "register":
      return (
        <KV rows={[
          ["Asset", <strong key="n">{data.name}</strong>],
          ["Workspace", data.workspace],
          ["Owner", data.owner],
          ["Next review", data.next_review],
        ]} />
      );
  }
}
