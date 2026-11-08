import { useEffect, useState, type FormEvent } from "react";
import { handoffPath, readHandoff, type AssignedWork, type DecisionHandoff, type HandoffPreview } from "../../api/handoff";
import type { CatalogMeta } from "../../api/types";
import { navigate } from "../../lib/navigation";
import { Icon } from "../Icon";
import { DashboardDesign } from "./DashboardDesign";
import { workbookViewUrl } from "../../api/dashboardBuilder";
import { DecisionDashboard } from "./DecisionDashboard";
import "./request-handoff.css";

const labelDate = (date: string) => new Date(date.slice(0, 10) + "T00:00:00Z").toLocaleDateString("en-GB", {
  day: "numeric", month: "short", year: "numeric", timeZone: "UTC",
});
const labelMonth = (date: string) => new Date(date.slice(0, 7) + "-01T00:00:00Z").toLocaleDateString("en-GB", {
  month: "short", year: "numeric", timeZone: "UTC",
});
const statusText = (status: string) => status.replaceAll("_", " ");
const errorText = (error: unknown) => error instanceof Error ? error.message : "Could not reach the saved decision.";

function RequestFit({ data, catalog }: { data: DecisionHandoff; catalog: CatalogMeta | null }) {
  const { candidate: report, intent } = data;
  const native = data.verdict === "reuse" && !report ? data.employee_report : null;
  const kpi = (id: string) => catalog?.measures[id]?.name ?? id.replaceAll("_", " ");
  const dim = (id: string) => catalog?.dimensions[id]?.name ?? id.replaceAll("_", " ");
  const countries = new Intl.DisplayNames(["en"], { type: "region" });
  const scope = [...Object.entries(intent.filters ?? {}).flatMap(([field, items]) => items.map(item =>
    field === "market" && /^[A-Z]{2}$/.test(item) ? `${countries.of(item)} (${item})` : item)), ...(intent.other_markets ?? [])];
  const requested = intent.measures ?? [];
  const breakdown = (intent.dimensions ?? []).filter(value => value !== "month").map(dim);
  const scopeProof = data.current_review?.scope_evidence ?? report?.scope_evidence;
  const scopeConflict = scopeProof?.conflict;
  const reference = (sheet: string, id: string | null) => {
    const ref = data.source_refs.find(source => source.sheet === sheet && source.id === id);
    return ref && <small className="rh-row-ref">{ref.sheet} · Row {ref.row} · {ref.id}</small>;
  };
  const blockers = (report?.gates_failed ?? []).filter(reason => reason !== scopeProof?.reason);
  const covered = [...(report?.measures_found ?? []).map(kpi), ...(report?.dimensions_found ?? []).map(dim)];
  const missing = [...(report?.measures_missing ?? []).map(kpi), ...(report?.dimensions_missing ?? []).map(dim)];
  if (report?.grain_supported === false) missing.push(`${intent.grain || "Requested"} time grain`);
  return <section className="rh-fit" aria-label="Request fit">
    <h3>{report || native ? "How the report fits your request" : "What the request needs"}</h3>
    {data.verdict === "new_build" && report && <p className="rh-sub">Closest existing report · {report.name} <code>{report.asset_id}</code></p>}
    <dl className="rh-list">
      {requested.length > 0 && <><dt>Requested KPIs</dt><dd>{requested.map(kpi).join(", ")}</dd></>}
      {(intent.grain || breakdown.length > 0) && <><dt>Breakdown</dt><dd>{[intent.grain === "month" ? "Monthly" : intent.grain, ...breakdown].filter(Boolean).join(" · ")}</dd></>}
      {(scope.length > 0 || intent.scope_global) && <><dt>Scope</dt><dd>{scope.length ? scope.join(" · ") : "All products and markets"}</dd></>}
      {report && <><dt>Listed on report</dt><dd>{!missing.length && requested.length > 0 && requested.every(id => report.measures_found.includes(id))
        ? `All ${requested.length} requested ${requested.length === 1 ? "KPI" : "KPIs"}` : covered.join(", ") || "None of the requested measures or breakdowns"}</dd></>}
      {native && <><dt>Employee view</dt><dd>{native.label} · {native.revision ? `Published revision ${native.revision}` : "Workbook baseline"}</dd></>}
      {missing.length > 0 && <><dt>Missing from report</dt><dd>{missing.join(", ")}</dd></>}
      {!!intent.unmatched_terms?.length && <><dt>Unavailable</dt><dd>{intent.unmatched_terms.join(", ")}</dd></>}
      {blockers.length > 0 && <><dt>Blocks reuse</dt><dd>{blockers.join(" ")}</dd></>}
    </dl>
    {scopeConflict && scopeProof && <div className="rh-scope-pair" aria-label="Report and model scope conflict">
      <strong>Source mismatch</strong><dl>
        <div><dt>Report scope</dt><dd>{[scopeProof.asset_product, scopeProof.asset_market].filter(Boolean).join(" · ") || "Unrecorded"}</dd>
          <dd>{reference("Analytics_Assets", scopeProof.asset_id)}</dd></div>
        <div><dt>Linked model scope</dt><dd>{[scopeProof.model_product, scopeProof.model_region].filter(Boolean).join(" · ") || "Unrecorded"}</dd>
          <dd>{reference("Semantic_Models", scopeProof.model_id)}</dd></div>
      </dl></div>}
  </section>;
}

function Preview({ preview }: { preview: HandoffPreview }) {
  const value = (number: number | undefined, unit: string) => number == null ? "—" : `${number.toLocaleString("en-GB", { maximumFractionDigits: 2 })} ${unit}`.trim();
  return <div className="rh-preview">
    <h4>Workbook preview</h4><p className="rh-sub">{preview.description || "Synthetic workbook values for this request."}</p>
    {preview.rows.map(row => <table key={row.label} className="rh-table">
      <caption>{row.label}</caption>
      <thead><tr><th scope="col">Measure</th>{preview.previous_month && <th scope="col">{labelMonth(preview.previous_month)}</th>}
        <th scope="col">{labelMonth(preview.month)}</th></tr></thead>
      <tbody>{preview.columns.map(col => <tr key={col.id}><th scope="row">{col.name}</th>
        {preview.previous_month && <td>{value(row.previous[col.id], col.unit)}</td>}<td>{value(row.values[col.id], col.unit)}</td></tr>)}</tbody>
    </table>)}
    {!!preview.not_previewed?.length && <p>Additional requested measures without preview values · {preview.not_previewed.join(", ")}</p>}
    <p className="rh-sub">{preview.source}{!!preview.source_rows.length && ` · Rows ${preview.source_rows.join(", ")}`}</p>
    {!!preview.fields.length && <p className="rh-fields">{preview.fields.join(" · ")}</p>}
  </div>;
}

function DecisionEvidence({ data }: { data: DecisionHandoff }) {
  return <details className="rh-evidence"><summary>Evidence for this decision</summary>
    <p>{data.reason}</p><p className="rh-sub">{data.question}</p>
    {data.estate_assessment?.reason && <p><strong>Imported catalog assessment</strong><br />{data.estate_assessment.reason}</p>}
    {data.source_refs.length > 0 && <ul className="rh-sources">{data.source_refs.map(ref =>
      <li key={`${ref.sheet}-${ref.row}-${ref.id}`}><strong>{ref.sheet} · Row {ref.row}</strong>
        <span><code>{ref.id}</code> {ref.detail}</span></li>)}</ul>}
    {data.evidence.map((e, i) => <details className="rh-evidence-step" key={e.stage + i}><summary>{e.summary}</summary>
      <p className="rh-sub">{e.sheets.join(" · ")}</p>
      <ul>{e.findings.map((finding, j) => <li key={j}>{finding}</li>)}</ul></details>)}
    <p className="rh-sub">Conversation <code>{data.conversation_id}</code> · Decision <code>{data.run_id}</code></p>
  </details>;
}

function Assignment({ data, path, completed, label = "Assign next step", secondary = false }: {
  label?: string; secondary?: boolean;
  data: DecisionHandoff; path: string; completed: (action: AssignedWork) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const action = data.action;
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    const outcome = String(fields.get("outcome") || "").trim();
    if (action && !outcome) { setError("Describe the result before marking this work done."); return; }
    setBusy(true);
    setError("");
    try {
      const body = action ? { status: "done", outcome } : { owner_id: fields.get("owner_id"), due_date: fields.get("due_date") };
      const updated = await readHandoff<AssignedWork>(path + "/actions", action ? "PATCH" : "POST", body);
      completed(updated);
      setEditing(false);
    } catch (e) { setError(errorText(e)); }
    finally { setBusy(false); }
  }
  if (action) return <section className="rh-assignment" aria-label="Assigned next step">
    <div className="rh-task-head"><span className="rh-kicker">Assigned work</span><span className="rh-status">{statusText(action.status)}</span></div>
    {action.title !== data.action_title && <h4>{action.title}</h4>}<p>{action.owner} · Due {labelDate(action.due_date)}</p>
    {action.outcome && <p className="rh-outcome"><strong>Recorded outcome</strong> {action.outcome}</p>}
    <details className="rh-provenance"><summary>Assignment record</summary><p>Action <code>{action._id}</code> · Decision <code>{data.run_id}</code></p>
      {action.created_by && <p>Recorded by {action.created_by}{action.created_by_id && ` (${action.created_by_id})`}</p>}
      <p className="rh-sub">Saved with this decision’s request, plan and evidence.</p></details>
    {["open", "in_progress", "blocked"].includes(action.status) && (editing
      ? <form onSubmit={save} className="rh-form"><label>Outcome<textarea name="outcome" required maxLength={1000} rows={2} /></label>
        {error && <p role="alert" className="text-bad">{error}</p>}
        <div className="rh-buttons"><button type="submit" className="btn" disabled={busy}>{busy ? "Saving…" : "Mark done"}</button>
          <button type="button" className="btn-outline" onClick={() => setEditing(false)} disabled={busy}>Cancel</button></div></form>
      : <button type="button" className="btn-outline" onClick={() => setEditing(true)}>Record outcome</button>)}
  </section>;
  return editing ? <form className="rh-form" onSubmit={save} aria-label="Assign this work">
    <h4>Assign this work</h4><div className="rh-inputs">
      <label><span id={`owner-${data.run_id}`}>Owner</span><select name="owner_id" aria-labelledby={`owner-${data.run_id}`} defaultValue={data.suggested_owner_id ?? ""} required>
        <option value="" disabled>Choose an active owner</option>{data.owners.map(owner =>
          <option key={owner.id} value={owner.id}>{owner.name} · {owner.role}</option>)}</select></label>
      <label>Due date<input type="date" name="due_date" required /></label></div>
    <p className="rh-sub">Demo participant · {data.actor.name} ({data.actor.id}). This assignment keeps the evidence from this decision.</p>
    {error && <p role="alert" className="text-bad">{error}</p>}
    <div className="rh-buttons"><button type="submit" className="btn" disabled={busy}>{busy ? "Saving…" : "Save assignment"}</button>
      <button type="button" className="btn-outline" onClick={() => setEditing(false)} disabled={busy}>Cancel</button></div>
  </form> : <button type="button" className={secondary ? "btn-outline" : "btn"} onClick={() => setEditing(true)}>
    {label} <Icon name="arrowRight" size={15}/></button>;
}

export function RequestHandoff({ conversationId, runId, catalog, isNative, onRecheck, onBuilt, dashboardReady }: {
  conversationId: string; runId: string; catalog: CatalogMeta | null; isNative: boolean;
  onRecheck: (runId: string, reason: string | null) => void;
  onBuilt: (runId: string, reused: boolean) => void; dashboardReady: boolean;
}) {
  const path = handoffPath(conversationId, runId);
  const [data, setData] = useState<DecisionHandoff | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [showPreview, setShowPreview] = useState(false);
  const [notice, setNotice] = useState("");
  useEffect(() => {
    let active = true;
    setError("");
    readHandoff<DecisionHandoff>(path).then(result => {
      if (active) { setData(result); onRecheck(runId, result.current_review?.reason ?? null); }
    })
      .catch(e => { if (active) setError(errorText(e)); });
    return () => { active = false; };
  }, [path, attempt, runId, onRecheck]);
  if (!data) return <div className="rh-load" role={error ? "alert" : "status"}>{error
    ? <>Could not open this decision’s next step. {error} <button type="button" className="btn-outline" onClick={() => setAttempt(n => n + 1)}>Retry</button></>
    : "Loading the saved decision…"}</div>;
  const employee = data.employee_report;
  const savedReuse = data.verdict === "reuse" ? data.saved_dashboard ?? null : null;
  const verdict = data.handoff_verdict || data.verdict;
  const canDesign = !data.current_review && ["new_build", "create", "extend"].includes(verdict);
  const workbook = verdict === "reuse" && !data.current_review && !isNative && !!data.metric_series?.points.length;
  const hasPrimary = canDesign || isNative || workbook || !!savedReuse;
  const labels: Partial<Record<typeof verdict, string>> = {
    repair: "Plan repairs with an owner", review: "Start owner review", migrate: "Plan migration with an owner",
    consolidate: "Review consolidation", retire: "Review retirement", not_feasible: "Assign a feasibility review",
  };
  const label = labels[verdict] ?? "Assign next step";
  const followUp = (<section className="rh-next"><span className="rh-kicker">{hasPrimary ? "Optional follow-up" : "Next step"}</span><h3>{data.action_title}</h3>
      {data.plan_steps[0] && <p>{data.plan_steps[0]}</p>}
      {data.plan_steps.length > 1 && <details className="rh-provenance"><summary>Work to check ({data.plan_steps.length - 1})</summary>
        <ol className="rh-plan">{data.plan_steps.slice(1).map((step, i) => <li key={i}>{step}</li>)}</ol></details>}
      {data.target_model?.id && (data.verdict === "new_build" || data.verdict === "migrate") &&
        <button className="rh-link" type="button" onClick={() => window.dispatchEvent(new CustomEvent("open-entity", { detail: data.target_model!.id }))}>
          Inspect shared model · {data.target_model.name || data.target_model.id}</button>}
      {employee && !isNative && <div className="rh-native"><p className="rh-sub">Separate employee workbook report · {employee.label} <code>{employee.report_id}</code></p>
        <a className="btn" href={employee.url} onClick={navigate}>Open matching employee report <Icon name="arrowRight" size={15}/></a></div>}
      {data.preview && <><button type="button" className={data.verdict === "reuse" && !employee ? "btn" : "btn-outline"} aria-expanded={showPreview}
        onClick={() => setShowPreview(open => !open)}>{showPreview ? "Hide workbook preview" : "View workbook preview"}</button>
        {showPreview && <Preview preview={data.preview} />}</>}
      <Assignment data={data} path={path} secondary={hasPrimary} label={label} completed={action => {
        setData({ ...data, action }); setNotice(action.status === "done" ? "Outcome saved." : "Assignment saved.");
      }} />
      {notice && <p role="status" className="rh-notice">{notice}</p>}
      {!!data.covering_actions?.length && <details className="rh-provenance"><summary>Existing work on this finding ({data.covering_actions.length})</summary>
        <ul>{data.covering_actions.map(action => <li key={action._id}>{action.title} · {action.owner} · {statusText(action.status)} <code>{action._id}</code></li>)}</ul></details>}
      {data.related_actions.length > 0 && <details className="rh-provenance"><summary>Other work from this decision ({data.related_actions.length})</summary>
        <ul>{data.related_actions.map(action => <li key={action._id}>{action.title} · {action.owner} · {statusText(action.status)}</li>)}</ul></details>}
      {data.storage_mode === "memory" && <p className="rh-sub">Demo storage resets when the server restarts.</p>}
    </section>);
  return <div className="rh" aria-label="Decision handoff">
    {canDesign && <DashboardDesign conversationId={conversationId} runId={runId} onBuilt={onBuilt}/>}
    {dashboardReady ? <details className="rh-provenance"><summary>Original catalog assessment</summary>
      <RequestFit data={data} catalog={catalog}/><DecisionEvidence data={data}/>
      {data.action && followUp}
    </details> : <>
    {employee && isNative && !savedReuse && <div className="rh-native"><a className="btn" href={employee.url} onClick={navigate}>Open matching employee report <Icon name="arrowRight" size={15}/></a></div>}
    {savedReuse && <div className="rh-native"><p className="rh-sub">Already built in Ask by {savedReuse.created_by} · {savedReuse.owner ? `Owner: ${savedReuse.owner}` : "No owner yet"}</p>
      <a className="btn" href={savedReuse.url} onClick={navigate}>Open the saved dashboard <Icon name="arrowRight" size={15}/></a></div>}
    {workbook && <div className="rh-native"><a className="btn" href={workbookViewUrl(conversationId, runId)} onClick={navigate}>Open verified workbook view <Icon name="arrowRight" size={15}/></a></div>}
    {data.current_review && <div className="rh-recheck"><strong>Saved recommendation · Reuse</strong>
      <p>Current catalog check · {data.current_review.reason}</p></div>}
    {!hasPrimary && followUp}
    <DecisionDashboard data={data} />
    {data.metric_series?.points.length ? <details className="rh-provenance"><summary>How the report fits your request</summary>
      <RequestFit data={data} catalog={catalog} /></details> : <RequestFit data={data} catalog={catalog} />}
    {hasPrimary && (canDesign && !data.action
      ? <details className="rh-provenance"><summary>Assign a separate owner follow-up</summary>{followUp}</details> : followUp)}
    <DecisionEvidence data={data} />
    </>}
  </div>;
}
