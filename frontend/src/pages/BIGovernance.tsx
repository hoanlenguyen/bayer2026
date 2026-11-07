import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from "react";
import {
  gov, type Assessment, type AssessmentRecord, type AssetGovernance, type DocumentDetail, type Evidence, type HistoryEntry, type IndexPage,
  type MappingView, type Permissions, type PermittedSource, type PolicyRow, type Risk, type RiskDetail, type RiskRow,
} from "../api/biGovernance";
import { useActor } from "../lib/actor";
import { Card, Notice, OwnerCell, go, link, useLoad, usePersonas, when } from "./biShared";

/* Evidence & governance inside the BI Portfolio. Every fact links to the record it comes from, every label says whose
   authority it carries, and the server decides scope, applicability and access. */

const G = "/bi-estate/governance";
export const evidenceUrl = (id: string, asset: string) => `${G}/evidence/${encodeURIComponent(id)}?asset=${encodeURIComponent(asset)}`;
export const riskUrl = (id: string) => `${G}/risks/${encodeURIComponent(id)}`;
export const docUrl = (id: string, asset?: string) => `${G}/documents/${encodeURIComponent(id)}${asset ? `?asset=${encodeURIComponent(asset)}` : ""}`;
export const assessmentUrl = (id: string) => `${G}/assessments/${encodeURIComponent(id)}`;
export const assetGovUrl = (id: string, finding?: string) => `/bi-estate/${encodeURIComponent(id)}?tab=governance${finding ? `&finding=${finding}` : ""}`;
const dateOnly = (v: string | null | undefined) => v ? v.slice(0, 10) : "not stated";

function Loading({ error, retry, what }: { error: string; retry: () => void; what: string }) {
  if (!error) return <p role="status">Loading {what}…</p>;
  const hidden = /available to you/.test(error);
  return <Notice kind={hidden ? "info" : "error"}>{hidden ? `This ${what} is not available to you, or it does not exist.` : `Could not load the ${what}: ${error}`}
    {!hidden && <> <button type="button" className="bp-linkbtn" onClick={retry}>Try again</button></>}</Notice>;
}

const Authority = ({ label }: { label: string }) => <span className={`bg-auth bg-auth-${label.split(/[ ,]/)[0].toLowerCase()}`}>{label}</span>;

function Locator({ e }: { e: Evidence }) {
  const s = e.source;
  if (s.kind === "workbook") return <span className="muted small">{s.sheet} row {s.row}{s.record_id && <> · <span className="mono">{s.record_id}</span></>} · {s.file} <span className="mono">{s.revision}</span></span>;
  if (s.kind === "check") return <span className="muted small">{s.id} v{s.version}</span>;
  return <span className="muted small">{s.label}{s.record_id && <> · <span className="mono">{s.record_id}</span></>}</span>;
}

function EvidenceRow({ e, asset }: { e: Evidence; asset: string }) {
  return <li className="bg-ev">
    <a href={evidenceUrl(e.id, asset)} onClick={link}>{e.label}</a>
    <div className="bg-meta"><Authority label={e.authority_label} /> <Locator e={e} />
      {e.observed_at && <span className="muted small"> · {e.observed_meaning ?? "Observed"}: {dateOnly(e.observed_at)}</span>}
      {e.status === "superseded" && <span className="text-warn small"> · Superseded</span>}
      {e.availability !== "available" && <span className="text-warn small"> · {e.availability === "changed_since_cited" ? "Source changed since cited" : "Source unavailable"}</span>}
    </div></li>;
}

const RESULT_CLASS: Record<string, string> = { finding: "bad", expired_exception: "bad", needs_evidence: "warn", limitation: "muted", clear: "ok", exception: "ok" };
function ResultTag({ a }: { a: Assessment }) {
  return <span className={`bg-result bg-result-${a.result ? RESULT_CLASS[a.result] : "muted"}`}>{a.result_label ?? a.status_label}</span>;
}

/* ---------------------------------------------------------------- portfolio index */

export function GovernanceIndex({ params, update }: { params: URLSearchParams; update: (c: Record<string, string | null>) => void }) {
  const tab = (params.get("gtab") ?? "policies") as "policies" | "risks" | "evidence";
  const query = new URLSearchParams([...params].filter(([k]) => !["view", "gtab", "gq", "gpage", "q", "sort", "direction", "page"].includes(k)));
  query.set("tab", tab);
  if (params.get("gq")) query.set("q", params.get("gq")!);
  if (params.get("gpage")) query.set("page", params.get("gpage")!);
  const key = query.toString();
  const actor = useActor();
  const { data, error, retry, loading } = useLoad<IndexPage<PolicyRow & RiskRow & Evidence>>((s) => gov.index(new URLSearchParams(key), s), [key, actor]);
  const [q, setQ] = useState(params.get("gq") ?? "");
  useEffect(() => setQ(params.get("gq") ?? ""), [params]);
  const [registering, setRegistering] = useState(false);
  const filters = ["origin", "platform", "issue", "lifecycle", "owner_state", "product", "market"].filter((k) => params.get(k));
  const tabs: [typeof tab, string][] = [["policies", "Applicable policies"], ["risks", "Risks"], ["evidence", "Evidence"]];
  const noun = tab === "policies" ? "documents and rules" : tab === "risks" ? "risks" : "evidence items";
  return <section className="bg-index" aria-label="Evidence and governance">
    <div className="bg-tabs" role="tablist" aria-label="Evidence and governance views">{tabs.map(([k, l]) =>
      <button key={k} role="tab" type="button" aria-selected={tab === k} onClick={() => update({ gtab: k === "policies" ? null : k, gpage: null })}>{l}</button>)}</div>
    <p className="bg-scope small">Scope: {data ? <>{data.scope_assets} of {data.portfolio_assets} dashboards in this portfolio</> : "the portfolio"}
      {filters.length > 0 && <> · filtered by {filters.map((k) => `${k.replace("_", " ")} ${params.get(k)}`).join(", ")}
        <button type="button" className="bp-linkbtn" onClick={() => update(Object.fromEntries(filters.map((k) => [k, null])))}>Clear filters</button></>}
      {data && <> · as of {data.as_of} · workbook <span className="mono">{data.workbook.sha}</span></>}</p>
    <form className="bp-filters" role="search" onSubmit={(e) => { e.preventDefault(); update({ gq: q.trim() || null, gpage: null }); }}>
      <label className="bp-search"><span className="sr-only">Search {noun}</span>
        <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search by dashboard, owner, KPI, policy or finding" /></label>
      <button className="btn-outline" type="submit">Search</button>
      {data?.permissions.steward && tab === "policies" && <button type="button" className="btn-outline" onClick={() => setRegistering((v) => !v)}>
        {registering ? "Close" : "Register a document"}</button>}
    </form>
    {registering && <RegisterForm onDone={(doc) => { setRegistering(false); go(docUrl(doc)); }} />}
    {data && data.mapping_tasks.length > 0 && <MappingTasks tasks={data.mapping_tasks} permissions={data.permissions} onChange={retry} />}
    <p role="status" aria-live="polite">{data ? <><strong>{data.total}</strong> {noun} · <strong>{data.distinct_assets}</strong> distinct {data.distinct_assets === 1 ? "dashboard" : "dashboards"} affected</> : loading ? "Loading…" : ""}</p>
    {error && <Notice kind="error">Could not load this view: {error} <button type="button" className="bp-linkbtn" onClick={retry}>Try again</button></Notice>}
    {data && data.rows.length === 0 && <Notice kind="info">{tab === "policies" ? "No policy or rule applies to a dashboard in this scope." : `No ${noun} match this scope and search.`}</Notice>}
    {data && data.rows.length > 0 && <div className="bp-tablewrap"><table className="bp-table">
      {tab === "policies" && <><thead><tr><th scope="col">Policy or rule</th><th scope="col">Source and version</th><th scope="col">Dashboards</th></tr></thead>
        <tbody>{data.rows.map((p) => <tr key={p.id}>
          <td data-label="Policy"><a className="bp-title" href={docUrl(p.id)} onClick={link}>{p.title}</a><div className="muted small mono">{p.id}</div></td>
          <td data-label="Source"><Authority label={p.authority_label} /><div className="muted small">{p.version ? `Version ${p.version}, effective ${p.effective_from}` : "No author-assigned version"}{p.priority && ` · priority ${p.priority}`}</div></td>
          <td data-label="Dashboards"><strong>{p.affected}</strong> {p.affected === 1 ? "dashboard" : "dashboards"}{p.with_findings > 0 && <span className="text-bad"> · {p.with_findings} need action</span>}
            <div className="muted small">{p.sample.map((a) => a.title).join(", ")}{p.affected > p.sample.length && ", …"}</div></td></tr>)}</tbody></>}
      {tab === "risks" && <><thead><tr><th scope="col">Risk</th><th scope="col">Dashboard and owner</th><th scope="col">Priority</th><th scope="col">Review</th></tr></thead>
        <tbody>{data.rows.map((x) => <tr key={x.id}>
          <td data-label="Risk"><a className="bp-title" href={riskUrl(x.id)} onClick={link}>{x.title}</a><p className="bp-finding small">{x.observation}</p>
            <div className="muted small">{x.origin_label}{x.rule_ids.length > 0 && ` · ${x.rule_ids.join(", ")}`}</div></td>
          <td data-label="Dashboard"><a href={assetGovUrl(x.asset_id)} onClick={link}>{x.asset_title}</a><div><OwnerCell owner={x.owner} state={x.owner_state as "active"} /></div></td>
          <td data-label="Priority"><Priorities x={x} /></td>
          <td data-label="Review">{x.review.label}</td></tr>)}</tbody></>}
      {tab === "evidence" && <><thead><tr><th scope="col">Evidence</th><th scope="col">Source</th><th scope="col">Dashboards</th></tr></thead>
        <tbody>{data.rows.map((e) => <tr key={e.id}>
          <td data-label="Evidence"><a className="bp-title" href={evidenceUrl(e.id, e.assets![0].id)} onClick={link}>{e.label}</a>
            <div className="muted small">{e.observed_at ? `${e.observed_meaning}: ${dateOnly(e.observed_at)}` : "No observation time in the source"} · collected {dateOnly(e.collected_at)}</div></td>
          <td data-label="Source"><Authority label={e.authority_label} /><div><Locator e={e} /></div></td>
          <td data-label="Dashboards">{e.assets!.map((a) => a.title).join(", ")}{(e.asset_count ?? 0) > e.assets!.length && ` and ${(e.asset_count ?? 0) - e.assets!.length} more`}</td></tr>)}</tbody></>}
    </table></div>}
    {data && data.pages > 1 && <nav className="bp-pages" aria-label="Pages">
      <button type="button" className="btn-outline bp-small" disabled={data.page <= 1} onClick={() => update({ gpage: String(data.page - 1) })}>Previous</button>
      <span>Page {data.page} of {data.pages}</span>
      <button type="button" className="btn-outline bp-small" disabled={data.page >= data.pages} onClick={() => update({ gpage: String(data.page + 1) })}>Next</button></nav>}
    <p className="muted small">Labels: Company document · Demo document (synthetic, not company policy) · Challenge workbook (SinceAI's rules, no signed version) · AnalytIQ check · Source observation (imported signal). Reading evidence never counts as a report open.</p>
  </section>;
}

function Priorities({ x }: { x: { source_severity: string | null; rule_priority: string | null; action_priority: string } }) {
  return <dl className="bg-prio small">
    <div><dt>Action</dt><dd>{x.action_priority}</dd></div>
    <div><dt>Source severity</dt><dd>{x.source_severity ?? "none"}</dd></div>
    <div><dt>Rule priority</dt><dd>{x.rule_priority ?? "none"}</dd></div></dl>;
}

/* ---------------------------------------------------------------- one dashboard */

export function AssetGovernanceView({ id, finding }: { id: string; finding: string | null }) {
  const actor = useActor();
  const [at, setAt] = useState("");
  const { data, error, retry } = useLoad<AssetGovernance>((s) => gov.asset(id, at || undefined, s), [id, at, actor]);
  const focus = useRef<HTMLElement | null>(null);
  const [adding, setAdding] = useState(false);
  useEffect(() => { if (data && finding) { focus.current?.scrollIntoView({ block: "start" }); focus.current?.focus({ preventScroll: true }); } }, [data?.asset.id, finding]);
  if (!data) return <Loading error={error} retry={retry} what="evidence and governance" />;
  const g = data;
  const focused = new Set(finding ? g.finding_map[finding] ?? [] : []);
  const pending = g.policies.filter((p) => p.status === "undetermined");
  const applies = g.policies.filter((p) => p.status === "applies");
  return <div className="bg-asset">
    <p className="small">Owner: <OwnerCell owner={g.asset.owner} state={g.asset.owner_state as "active"} /> · as of
      <label className="bg-asof"> <span className="sr-only">Assess as of date</span><input type="date" value={at || g.as_of} onChange={(e) => setAt(e.target.value)} /></label>
      {at && <button type="button" className="bp-linkbtn" onClick={() => setAt("")}>Today</button>}
      · workbook <span className="mono">{g.workbook.sha}</span></p>
    {finding && focused.size === 0 && <Notice kind="info">This finding has no separate risk record here. It is explained by the evidence below.</Notice>}

    <Card title={`Risks (${g.risks.length})`}>
      {g.risks.length === 0 ? <p className="muted small">No risk was derived from the workbook, the app's checks or imported signals. This does not prove the dashboard is risk free.</p> :
        <ul className="bg-risks">{g.risks.map((x) => <li key={x.id} className={focused.has(x.id) ? "bg-focus" : ""} tabIndex={focused.has(x.id) ? -1 : undefined}
          ref={focused.has(x.id) && !focus.current ? (el) => { focus.current = el; } : undefined}>
          <a className="bp-title" href={riskUrl(x.id)} onClick={link}>{x.title}</a> <span className="muted small">· {x.origin_label}{x.source_status && ` · ${x.source_severity} severity, ${x.source_status} in source`}</span>
          <p className="small">{x.observation}</p><p className="muted small">Review: {x.review.label}</p></li>)}</ul>}
    </Card>

    <Card title={`Applicable policies and rules (${applies.length})`}>
      {applies.length === 0 && <p className="muted small">No policy or rule applies to this dashboard on this date.</p>}
      <ul className="bg-pols">{applies.map((p) => <PolicyItem key={p.doc_id + (p.clause?.clause_id ?? "")} p={p} asset={id} />)}</ul>
      {pending.length > 0 && <details><summary>Applicability undetermined ({pending.length})</summary>
        <ul className="bg-pols">{pending.map((p) => <li key={p.doc_id}><a href={docUrl(p.doc_id, id)} onClick={link}>{p.title}</a> <span className="mono small">{p.doc_id}</span>
          <div className="muted small">{p.reason}</div></li>)}</ul></details>}
      {g.not_applicable.length > 0 && <details><summary>Checked and not applicable ({g.not_applicable.length})</summary>
        <ul className="bg-pols">{g.not_applicable.map((p) => <li key={p.doc_id}><a href={docUrl(p.doc_id, id)} onClick={link}>{p.title}</a> <span className="mono small">{p.doc_id}</span>
          <div className="muted small">{p.reason}</div></li>)}</ul></details>}
    </Card>

    {g.missing_evidence.length > 0 && <Card title="Missing evidence">
      <ul className="bp-plain">{g.missing_evidence.map((m, i) => <li key={i}>{m.policy ? <a href={docUrl(m.policy, id)} onClick={link}>{m.policy}</a> : <a href={riskUrl(m.risk!)} onClick={link}>Requested for {m.risk}</a>}: {m.text}</li>)}</ul>
    </Card>}

    <Card title={`Evidence (${g.evidence.length})`}>
      {g.permissions.submit_evidence && (adding
        ? <AddEvidence g={g} onDone={() => { setAdding(false); retry(); }} onCancel={() => setAdding(false)} />
        : <div><button type="button" className="btn-outline bp-small" onClick={() => setAdding(true)}>Add evidence</button></div>)}
      <ul className="bg-evs">{g.evidence.map((e) => <EvidenceRow key={e.id} e={e} asset={id} />)}</ul>
      <p className="muted small">Not available for this dashboard: {g.unavailable.join("; ")}.</p>
    </Card>

    {g.mapping_tasks.length > 0 && <MappingTasks tasks={g.mapping_tasks} permissions={g.permissions} onChange={retry} />}

    <Card title="Review history">
      {g.history.length === 0 ? <p className="muted small">No review, evidence or mapping has been recorded for this dashboard yet.</p> :
        <History items={g.history} />}
    </Card>
  </div>;
}

function PolicyItem({ p, asset }: { p: Assessment; asset: string }) {
  return <li>
    <div className="bg-polhead"><a className="bp-title" href={docUrl(p.doc_id, asset)} onClick={link}>{p.title}</a> <span className="mono small">{p.doc_id}{p.clause && p.clause.doc_id !== p.doc_id ? "" : p.clause && p.authority !== "challenge_workbook" ? ` §${p.clause.clause_id} r${p.clause.revision}` : ""}</span>
      <Authority label={p.authority_label} /> <ResultTag a={p} /></div>
    {p.clause && <blockquote className="bg-clause small">{p.clause.text}</blockquote>}
    {p.facts.length > 0 && <details><summary className="small">Why it applies ({p.facts.length} {p.facts.length === 1 ? "fact" : "facts"})</summary>
      <ul className="bp-plain small">{p.facts.map((f, i) => <li key={i}>{f.evidence_id ? <a href={evidenceUrl(f.evidence_id, asset)} onClick={link}>{f.text}</a> : f.text}</li>)}</ul></details>}
    {p.reason && <p className="muted small">{p.reason}</p>}
    {p.risk_ids.length > 0 && <p className="small">Related {p.risk_ids.length === 1 ? "risk" : "risks"}: {p.risk_ids.map((r, i) => <span key={r}>{i > 0 && ", "}<a href={riskUrl(r)} onClick={link}>{r}</a></span>)}</p>}
    {p.exception && <p className="small">Exception <span className="mono">{p.exception.id}</span>: {p.exception.state}, expires {p.exception.expires}. {p.exception.rationale}</p>}
  </li>;
}

function History({ items }: { items: HistoryEntry[] }) {
  return <ol className="bp-history">{items.map((h) => <li key={h.id}>{when(h.at)}: {h.actor_name}. {h.text}
    {h.assessment && <> <a href={assessmentUrl(h.assessment)} onClick={link}>Reopen the assessment</a></>}</li>)}</ol>;
}

function AddEvidence({ g, onDone, onCancel }: { g: AssetGovernance; onDone: () => void; onCancel: () => void }) {
  const records = g.evidence.filter((e) => e.kind !== "owner_submission");
  const clauses = g.policies.filter((p) => p.clause && p.authority !== "challenge_workbook").map((p) => `${p.doc_id}#${p.clause!.clause_id}`);
  const [form, setForm] = useState({ record_evidence_id: "", reference: "", revision_or_section: "", supports: "", finding_id: "", clause_ref: clauses[0] ?? "" });
  const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  const own = g.evidence.filter((e) => e.kind === "owner_submission");
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setBusy(true); setError("");
    try {
      await gov.submitEvidence(g.asset.id, { expected_seq: Math.max(0, ...own.map((x) => x.seq ?? 0)), revision_or_section: form.revision_or_section,
        supports: form.supports, reference: form.reference, record_evidence_id: form.record_evidence_id || null,
        finding_id: form.finding_id || null, clause_ref: form.clause_ref || null });
      onDone();
    } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };
  return <form className="bp-form" onSubmit={submit}>
    <h4>Add evidence</h4>
    <label>Existing source record (optional)<select value={form.record_evidence_id} onChange={set("record_evidence_id")}><option value="">None, I will enter a reference</option>
      {records.map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}</select></label>
    <label>Reference (document, link or record; https only for links)<input value={form.reference} onChange={set("reference")} /></label>
    <label>Exact revision or section<input required value={form.revision_or_section} onChange={set("revision_or_section")} placeholder="For example: clause 2, revision 1" /></label>
    <label>What it supports<textarea required minLength={5} rows={2} value={form.supports} onChange={set("supports")} /></label>
    <label>Finding it answers (optional)<select value={form.finding_id} onChange={set("finding_id")}><option value="">None</option>
      {g.risks.map((r) => <option key={r.id} value={r.id}>{r.title}</option>)}</select></label>
    {clauses.length > 0 && <label>Clause it answers (optional)<select value={form.clause_ref} onChange={set("clause_ref")}><option value="">None</option>
      {clauses.map((c) => <option key={c} value={c}>{c}</option>)}</select></label>}
    <p className="muted small">Shown as your statement until a reviewer verifies it.</p>
    {error && <Notice kind="error">{error}</Notice>}
    <div className="bp-actions"><button className="btn" disabled={busy}>Submit evidence</button><button type="button" className="btn-outline" onClick={onCancel}>Cancel</button></div>
  </form>;
}

/* ---------------------------------------------------------------- items */

export function GovernanceItem({ kind, id, asset }: { kind: string; id: string; asset: string | null }) {
  return <section className="bp-detail">
    {kind === "evidence" && asset && <EvidenceView id={id} asset={asset} />}
    {kind === "risks" && <RiskView id={id} />}
    {kind === "documents" && <DocumentView id={id} asset={asset} />}
    {kind === "assessments" && <AssessmentView id={id} />}
    {!["evidence", "risks", "documents", "assessments"].includes(kind) || (kind === "evidence" && !asset)
      ? <Notice kind="info">This governance link is incomplete. <a href="/bi-estate?view=governance" onClick={link}>Open Evidence &amp; governance</a></Notice> : null}
  </section>;
}

function Back({ asset }: { asset?: { id: string; title: string } | null }) {
  return <p className="bg-back"><a href="/bi-estate?view=governance" onClick={link}>← Evidence &amp; governance</a>
    {asset && <> · <a href={assetGovUrl(asset.id)} onClick={link}>{asset.title}</a></>}</p>;
}

function Heading({ kicker, children }: { kicker: ReactNode; children: ReactNode }) {
  const ref = useRef<HTMLHeadingElement>(null);
  useEffect(() => { ref.current?.focus(); }, []);
  return <header><p className="bp-kicker">{kicker}</p><h2 tabIndex={-1} ref={ref}>{children}</h2></header>;
}

function EvidenceView({ id, asset }: { id: string; asset: string }) {
  const actor = useActor();
  const { data, error, retry } = useLoad<Evidence>((s) => gov.evidence(id, asset, s), [id, asset, actor]);
  if (!data) return <><Back /><Loading error={error} retry={retry} what="evidence item" /></>;
  const e = data;
  return <>
    <Back asset={e.asset} />
    <Heading kicker={<><Authority label={e.authority_label} /> · {e.kind.replaceAll("_", " ")} · <span className="mono">{e.id}</span></>}>{e.label}</Heading>
    <dl className="bp-dl">
      <dt>Source</dt><dd><Locator e={e} /></dd>
      <dt>{e.observed_meaning ?? "Observed"}</dt><dd>{e.observed_at ? dateOnly(e.observed_at) : "The source gives no observation or reporting time"}</dd>
      <dt>Collected by AnalytIQ</dt><dd>{when(e.collected_at)}</dd>
      <dt>Availability</dt><dd>{e.availability === "available" ? "Available" : e.availability === "changed_since_cited" ? "The source row has changed since it was cited; the cited values are kept" : "Source unavailable; the citation is kept"}</dd>
      {e.submitted_by && <><dt>Submitted by</dt><dd>{e.submitted_by} · {e.status === "verified" ? "verified" : e.status === "superseded" ? `superseded by ${e.superseded_by}` : e.status === "correction_requested" ? "correction requested" : "not yet verified"}</dd></>}
      {e.clause_ref && <><dt>Clause</dt><dd className="mono">{e.clause_ref}</dd></>}
      {e.finding_id && <><dt>Finding</dt><dd><a href={riskUrl(e.finding_id)} onClick={link}>{e.finding_id}</a></dd></>}
    </dl>
    <Card title="Values"><table className="bp-mini"><tbody>{Object.entries(e.value).map(([k, v]) =>
      <tr key={k}><th scope="row" className="mono">{k}</th><td>{typeof v === "object" ? JSON.stringify(v) : String(v ?? "")}</td></tr>)}</tbody></table>
      {e.record && <details><summary>Full source row</summary><table className="bp-mini"><tbody>{Object.entries(e.record).map(([k, v]) =>
        <tr key={k}><th scope="row" className="mono">{k}</th><td>{String(v ?? "")}</td></tr>)}</tbody></table></details>}</Card>
    {e.linked && e.linked.length > 0 && <Card title="Records this check joins"><ul className="bg-evs">{e.linked.map((l) => <EvidenceRow key={l.id} e={l} asset={asset} />)}</ul></Card>}
    {e.reviews && e.reviews.length > 0 && <Card title="Reviews"><ol className="bp-history">{e.reviews.map((r) => <li key={r.seq}>{when(r.at)}: {r.actor_name}, {r.decision.replace("_", " ")}. {r.note}</li>)}</ol></Card>}
    {e.kind === "owner_submission" && e.permissions?.review && e.status !== "superseded" && <ReviewEvidence e={e} onDone={retry} />}
  </>;
}

function ReviewEvidence({ e, onDone }: { e: Evidence; onDone: () => void }) {
  const [decision, setDecision] = useState("verified"); const [note, setNote] = useState("");
  const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  const submit = async (ev: FormEvent) => {
    ev.preventDefault(); setBusy(true); setError("");
    try { await gov.reviewEvidence(e.id, { decision, note, expected_reviews: e.reviews?.length ?? 0 }); onDone(); }
    catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };
  return <form className="bp-card bp-form" onSubmit={submit}><h3>Review this evidence</h3>
    <fieldset><legend>Decision</legend>{[["verified", "Verified against the source"], ["correction_requested", "Request a correction"]].map(([v, l]) =>
      <label key={v} className="bp-radio"><input type="radio" name="evdec" checked={decision === v} onChange={() => setDecision(v)} /> {l}</label>)}</fieldset>
    <label>Note<textarea required minLength={5} rows={2} value={note} onChange={(x) => setNote(x.target.value)} /></label>
    {error && <Notice kind="error">{error}</Notice>}
    <div className="bp-actions"><button className="btn" disabled={busy}>Record review</button></div></form>;
}

function RiskView({ id }: { id: string }) {
  const actor = useActor();
  const { data, error, retry } = useLoad<RiskDetail>((s) => gov.risk(id, s), [id, actor]);
  if (!data) return <><Back /><Loading error={error} retry={retry} what="risk" /></>;
  const x = data;
  return <>
    <Back asset={{ id: x.asset_id, title: x.asset_title }} />
    <Heading kicker={<><Authority label={x.origin_label} /> · <span className="mono">{x.id}</span></>}>{x.title}</Heading>
    <dl className="bp-dl">
      <dt>Observation</dt><dd>{x.observation}</dd>
      <dt>Decision it could affect</dt><dd>{x.consequence}</dd>
      <dt>Impact</dt><dd>{x.impact}</dd>
      <dt>Dashboard owner</dt><dd><OwnerCell owner={x.owner} state={x.owner_state as "active"} /></dd>
      <dt>Source status</dt><dd>{x.source_status ? `${x.source_status} in the source (kept as imported)` : "Not an imported signal"}</dd>
      <dt>Review</dt><dd>{x.review.label}</dd>
      <dt>Next action</dt><dd>{x.next_action}</dd>
    </dl>
    <Priorities x={x} />
    <Card title="Evidence"><ul className="bg-evs">{x.evidence.map((e) => <EvidenceRow key={e.id} e={e} asset={x.asset_id} />)}</ul></Card>
    {(x.guidance.length > 0 || x.checks.length > 0) && <Card title="Related guidance">
      {x.guidance.map((c) => <div key={c.doc_id}><p><a href={docUrl(c.doc_id, x.asset_id)} onClick={link}>{c.doc_title}</a> <span className="mono small">{c.doc_id}</span> <Authority label={c.authority_label} />
        {c.priority && <span className="muted small"> · priority {c.priority}</span>}</p><blockquote className="bg-clause small">{c.text}</blockquote>
        {c.source?.row && <p className="muted small">Governance_Rules row {c.source.row}</p>}</div>)}
      {x.checks.map((c) => <p key={c.id} className="small"><strong>{c.id} v{c.version}</strong> (AnalytIQ check): {c.text}</p>)}
      {x.guidance.length === 0 && <p className="muted small">No verified policy is linked. The risk stands on its evidence.</p>}
    </Card>}
    <div className="bp-links">
      <a href={assetGovUrl(x.asset_id)} onClick={link}>Back to the dashboard</a>
      {x.pair_ids.length > 0 && x.code === "consolidation" && <a href={`/bi-estate/compare/${x.pair_ids[0].split("~").join("/")}`} onClick={link}>Open the comparison and owner review</a>}
      {x.cases.map((c) => <a key={c.id} href={`/bi-estate/compare/${c.assets.join("/")}`} onClick={link}>Owner review {c.id} ({c.status_label})</a>)}
    </div>
    <SubjectActions permissions={x.permissions} review={x.review} evidence={x.evidence}
      send={(body) => gov.riskEvent(x.id, body)} onDone={retry} canException={x.code === "definition"} risk={x} />
    <Card title="History">{x.history.length ? <History items={x.history} /> : <p className="muted small">Nothing recorded yet.</p>}</Card>
  </>;
}

function SubjectActions({ permissions, review, evidence, send, onDone, canException, risk }: {
  permissions: Permissions; review: { seq: number; status: string }; evidence: Evidence[]; send: (b: Record<string, unknown>) => Promise<unknown>;
  onDone: () => void; canException?: boolean; risk?: Risk;
}) {
  const personas = usePersonas();
  const [mode, setMode] = useState<"" | "assign" | "request_evidence" | "assessment" | "exception">("");
  const [assignee, setAssignee] = useState("DEMO-GOV-REVIEWER");
  const [note, setNote] = useState(""); const [judgment, setJudgment] = useState(""); const [reason, setReason] = useState("");
  const [cited, setCited] = useState<string[]>([]); const [ack, setAck] = useState(false);
  const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  const [exc, setExc] = useState({ rationale: "", expires: "", reference: "" });
  if (!permissions.steward && !permissions.review) return permissions.read_only
    ? <p className="muted small">You can read this record. Choose a steward or reviewer identity to act on it.</p> : null;
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setBusy(true); setError("");
    try {
      if (mode === "exception" && risk) {
        await gov.proposeException({ asset_ids: [risk.asset_id], rule_ref: "RULE-002", kpi_id: null, ...exc });
      } else {
        await send({ kind: mode, expected_seq: review.seq, assignee_id: mode === "assign" ? assignee : null, note,
          judgment: mode === "assessment" ? judgment : null, reason, evidence_ids: cited, acknowledge_changes: ack });
      }
      setMode(""); setNote(""); setReason(""); setCited([]); onDone();
    } catch (err) {
      const m = (err as Error).message; setError(m);
      if (/changed since this review started/.test(m)) setAck(false);
    } finally { setBusy(false); }
  };
  const judgments: [string, string][] = [["needs_action", "Needs action"], ["clear", "No finding after review"], ["remediated", "Remediation verified"],
    ["exception", "Covered by an accepted exception"], ["not_applicable", "Guidance does not apply"]];
  return <section className="bp-card" aria-label="Actions">
    <h3>Actions</h3>
    <div className="bp-actions">
      {permissions.steward && <button type="button" className="btn-outline bp-small" aria-pressed={mode === "assign"} onClick={() => setMode("assign")}>Assign a review</button>}
      <button type="button" className="btn-outline bp-small" aria-pressed={mode === "request_evidence"} onClick={() => setMode("request_evidence")}>Request missing evidence</button>
      <button type="button" className="btn-outline bp-small" aria-pressed={mode === "assessment"} onClick={() => setMode("assessment")}>Record a judgment</button>
      {canException && permissions.steward && <button type="button" className="btn-outline bp-small" aria-pressed={mode === "exception"} onClick={() => setMode("exception")}>Propose an exception</button>}
    </div>
    {mode && <form className="bp-form" onSubmit={submit}>
      {mode === "assign" && <><label>Reviewer<select value={assignee} onChange={(e) => setAssignee(e.target.value)}>
        {personas.filter((p) => p.role !== "employee" && p.role !== "auditor").map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}</select></label>
        <p className="muted small">Taking the review does not change the dashboard's accountable owner.</p></>}
      {mode === "request_evidence" && <label>What evidence is needed<textarea required minLength={5} rows={2} value={note} onChange={(e) => setNote(e.target.value)} /></label>}
      {mode === "assessment" && <>
        <fieldset><legend>Judgment</legend>{judgments.map(([v, l]) => <label key={v} className="bp-radio">
          <input type="radio" name="judgment" required checked={judgment === v} onChange={() => setJudgment(v)} /> {l}</label>)}</fieldset>
        <fieldset><legend>Evidence it rests on (needed to close)</legend>{evidence.map((e) => <label key={e.id} className="bp-radio">
          <input type="checkbox" checked={cited.includes(e.id)} onChange={(x) => setCited((c) => x.target.checked ? [...c, e.id] : c.filter((y) => y !== e.id))} /> {e.label}</label>)}</fieldset>
        <label>Reason<textarea required minLength={5} rows={2} value={reason} onChange={(e) => setReason(e.target.value)} /></label>
        {/changed since this review started/.test(error) && <label className="bp-radio"><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} /> I reassessed the changed owner or evidence</label>}
      </>}
      {mode === "exception" && <>
        <label>Rationale<textarea required minLength={10} rows={2} value={exc.rationale} onChange={(e) => setExc({ ...exc, rationale: e.target.value })} /></label>
        <label>Expires<input type="date" required value={exc.expires} onChange={(e) => setExc({ ...exc, expires: e.target.value })} /></label>
        <label>Supporting reference<input required minLength={3} value={exc.reference} onChange={(e) => setExc({ ...exc, reference: e.target.value })} /></label>
        <p className="muted small">A governance reviewer approves it. It covers this dashboard's conflicting KPIs under RULE-002 until it expires.</p></>}
      {error && <Notice kind="error">{error}</Notice>}
      <div className="bp-actions"><button className="btn" disabled={busy}>Save</button><button type="button" className="btn-outline" onClick={() => setMode("")}>Cancel</button></div>
    </form>}
  </section>;
}

function DocumentView({ id, asset }: { id: string; asset: string | null }) {
  const actor = useActor();
  const { data, error, retry } = useLoad<DocumentDetail>((s) => gov.document(id, asset, s), [id, asset, actor]);
  const [original, setOriginal] = useState<{ rev: number; text: string | null; availability: string } | null>(null);
  const [mapping, setMapping] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [q, setQ] = useState("");
  if (!data) return <><Back /><Loading error={error} retry={retry} what="document" /></>;
  const d = data;
  const cur = d.current;
  const open = async (rev: number) => {
    try { const o = await gov.original(d.id, rev); setOriginal({ rev, text: o.text, availability: o.availability }); }
    catch (err) { setOriginal({ rev, text: null, availability: (err as Error).message }); }
  };
  const shown = q ? d.affected.filter((a) => `${a.id} ${a.title} ${a.owner}`.toLowerCase().includes(q.toLowerCase())) : d.affected;
  return <>
    <Back asset={asset ? { id: asset, title: d.why ? "Back to the dashboard" : asset } : null} />
    <Heading kicker={<><Authority label={d.authority_label} /> · <span className="mono">{d.id}</span></>}>{d.title}</Heading>
    <dl className="bp-dl">
      <dt>Issued by</dt><dd>{d.issuer ?? "Not stated"}</dd>
      <dt>Owner and team</dt><dd>{[d.owner, d.accountable_team].filter(Boolean).join(" · ") || "Not stated in the source"}</dd>
      <dt>Version</dt><dd>{cur ? (cur.version ? `Version ${cur.version} (revision ${cur.revision})` : `No author-assigned version · workbook ${cur.workbook_revision}`) : "No revision effective on this date"}</dd>
      <dt>Effective</dt><dd>{cur?.effective_from ? `From ${cur.effective_from}${cur.effective_to ? ` to ${cur.effective_to}` : ""}` : "No effective date in the source"}</dd>
      {d.priority && <><dt>Priority</dt><dd>{d.priority} (as stated in the workbook)</dd></>}
    </dl>
    {d.note && <p className="muted small">{d.note}</p>}
    {cur && <Card title="Clauses">{Object.entries(cur.clauses).map(([cid, c]) => <div key={cid}><p><strong>{d.authority === "challenge_workbook" ? c.title : `§${cid} ${c.title}`}</strong></p>
      <blockquote className="bg-clause">{c.text}</blockquote></div>)}
      <div className="bp-actions">{d.revisions.map((r) => <button key={r.revision} type="button" className="btn-outline bp-small" onClick={() => void open(r.revision)}>Open original{d.revisions.length > 1 ? `, revision ${r.revision}` : ""}</button>)}</div>
      {original && (original.text ? <pre className="bg-original" tabIndex={0} aria-label={`Original, revision ${original.rev}`}>{original.text}</pre>
        : <Notice kind="info">The original is not available here: {original.availability}.</Notice>)}
    </Card>}
    {d.why && <Card title={`Why it applies to ${asset}`}><PolicyItem p={d.why} asset={asset!} /></Card>}
    {d.why && d.why.subject && d.why.status === "applies" && <ClauseJudgment d={d} asset={asset!} onDone={retry} />}
    <Card title={`Affected dashboards (${d.affected_count})`}>
      {d.affected.length > 10 && <label className="bp-search"><span className="sr-only">Filter affected dashboards</span>
        <input type="search" placeholder="Filter by dashboard or owner" value={q} onChange={(e) => setQ(e.target.value)} /></label>}
      {d.affected.length === 0 ? <p className="muted small">No dashboard you can see is governed by this on {d.as_of}.</p> :
        <ul className="bp-plain">{shown.slice(0, 50).map((a) => <li key={a.id}><a href={assetGovUrl(a.id)} onClick={link}>{a.title}</a> <span className="mono small">{a.id}</span>
          <span className="muted small"> · {a.owner ?? "unassigned"} · {a.result_label ?? "applies"}</span></li>)}
          {shown.length > 50 && <li className="muted small">and {shown.length - 50} more; filter to narrow</li>}</ul>}
    </Card>
    {d.authority !== "challenge_workbook" && <Card title="Applicability mappings">
      {d.mappings.length === 0 && <p className="muted small">No mapping yet. Until one is accepted, this document governs no dashboard.</p>}
      <MappingList maps={d.mappings} permissions={d.permissions} onChange={retry} />
      {d.permissions.steward && (mapping ? <MappingForm doc={d} onDone={() => { setMapping(false); retry(); }} /> :
        <button type="button" className="btn-outline bp-small" onClick={() => setMapping(true)}>Propose a mapping</button>)}
    </Card>}
    {d.exceptions.length > 0 && <Card title="Exceptions"><ul className="bp-plain">{d.exceptions.map((e) => <li key={e.id}><span className="mono">{e.id}</span> · {e.asset_ids.join(", ")} · {e.state}, expires {e.expires}. {e.rationale}
      {e.status === "proposed" && d.permissions.approve && <DecideButtons onDecide={(dec, reason) => gov.decideException(e.id, { decision: dec, reason }).then(retry)} />}</li>)}</ul></Card>}
    <Card title="Revision history"><ol className="bp-history">{d.revisions.map((r) => <li key={r.revision}>Revision {r.revision}{r.version && `, version ${r.version}`}: effective {r.effective_from ?? "date not stated"}{r.effective_to && ` until ${r.effective_to}`}
      {r.registered_by && ` · registered by ${r.registered_by} ${when(r.registered_at ?? null)}`}{r.source?.sha256 && <> · source <span className="mono">{r.source.sha256}</span></>}</li>)}</ol>
      {d.permissions.steward && d.authority !== "challenge_workbook" && (publishing ? <RegisterForm docId={d.id} expected={d.revisions.length} onDone={() => { setPublishing(false); retry(); }} /> :
        <button type="button" className="btn-outline bp-small" onClick={() => setPublishing(true)}>Publish the next revision</button>)}
    </Card>
  </>;
}

function ClauseJudgment({ d, asset, onDone }: { d: DocumentDetail; asset: string; onDone: () => void }) {
  const actor = useActor();
  const { data } = useLoad<AssetGovernance>((s) => gov.asset(asset, undefined, s), [asset, actor, d.why?.review?.seq]);
  if (!data || !d.why?.review || !d.why.clause || !(d.permissions.review)) return null;
  return <SubjectActions permissions={{ ...d.permissions, steward: false }} review={d.why.review} evidence={data.evidence}
    send={(b) => gov.clauseEvent(d.id, d.why!.clause!.clause_id, asset, b)} onDone={onDone} />;
}

function MappingList({ maps, permissions, onChange }: { maps: MappingView[]; permissions: Permissions; onChange: () => void }) {
  return <ul className="bp-plain">{maps.map((m) => <li key={m.id}><a href={assetGovUrl(m.asset_id)} onClick={link}>{m.asset_id}</a> · clause {m.clause_id} · <strong>{m.status}</strong>
    <div className="muted small">Proposed by {m.proposed_by} {when(m.proposed_at)}: {m.reason}{m.decided_by && <> · {m.status} by {m.decided_by} {when(m.decided_at)}: {m.decision_reason}</>}</div>
    {m.status === "proposed" && permissions.approve && <DecideButtons onDecide={(dec, reason) => gov.decideMapping(m.id, { decision: dec, reason }).then(onChange)} />}</li>)}</ul>;
}

function MappingTasks({ tasks, permissions, onChange }: { tasks: MappingView[]; permissions: Permissions; onChange: () => void }) {
  return <Card title={`Mappings awaiting confirmation (${tasks.length})`}>
    <p className="muted small">{permissions.approve ? "Confirm or reject. A proposer cannot confirm their own mapping." : "Waiting for a governance reviewer."}</p>
    <MappingList maps={tasks} permissions={permissions} onChange={onChange} /></Card>;
}

function DecideButtons({ onDecide }: { onDecide: (d: "accepted" | "rejected", reason: string) => Promise<unknown> }) {
  const [reason, setReason] = useState(""); const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  const id = useId();
  const act = async (d: "accepted" | "rejected") => {
    if (reason.trim().length < 5) { setError("Give a reason of at least five characters."); return; }
    setBusy(true); setError("");
    try { await onDecide(d, reason); } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };
  return <div className="bp-form bg-decide"><label htmlFor={id}>Reason</label><input id={id} value={reason} onChange={(e) => setReason(e.target.value)} />
    <div className="bp-actions"><button type="button" className="btn bp-small" disabled={busy} onClick={() => void act("accepted")}>Accept</button>
      <button type="button" className="btn-outline bp-small" disabled={busy} onClick={() => void act("rejected")}>Reject</button></div>
    {error && <Notice kind="error">{error}</Notice>}</div>;
}

function MappingForm({ doc, onDone }: { doc: DocumentDetail; onDone: () => void }) {
  const clauses = Object.keys(doc.current?.clauses ?? doc.revisions.at(-1)?.clauses ?? {});
  const [asset, setAsset] = useState(""); const [clause, setClause] = useState(clauses.at(-1) ?? ""); const [reason, setReason] = useState("");
  const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setBusy(true); setError("");
    try { await gov.proposeMapping(doc.id, { asset_id: asset.trim(), clause_id: clause, reason }); onDone(); }
    catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };
  return <form className="bp-form" onSubmit={submit}><h4>Propose a mapping</h4>
    <label>Dashboard ID<input required value={asset} onChange={(e) => setAsset(e.target.value)} placeholder="For example AST-0009" /></label>
    <label>Clause<select value={clause} onChange={(e) => setClause(e.target.value)}>{clauses.map((c) => <option key={c} value={c}>§{c}</option>)}</select></label>
    <label>Reason (the facts that make it apply)<textarea required minLength={5} rows={2} value={reason} onChange={(e) => setReason(e.target.value)} /></label>
    <p className="muted small">A shared word or a similar title is not enough. A governance reviewer confirms the mapping before it applies.</p>
    {error && <Notice kind="error">{error}</Notice>}
    <div className="bp-actions"><button className="btn" disabled={busy}>Propose</button></div></form>;
}

function RegisterForm({ docId, expected = 0, onDone }: { docId?: string; expected?: number; onDone: (doc: string) => void }) {
  const [list, setList] = useState<PermittedSource[] | null>(null);
  const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  const [ref, setRef] = useState("");
  const [form, setForm] = useState<Record<string, string>>({});
  useEffect(() => { gov.sources().then((s) => setList(s.sources)).catch((e) => setError(e.message)); }, []);
  const options = (list ?? []).filter((s) => !docId || s.doc_id === docId);
  const choose = (r: string) => {
    setRef(r);
    const s = options.find((x) => x.ref === r);
    if (s) { const clause = Object.keys(s.clauses).at(-1)!;
      setForm({ doc_id: s.doc_id, title: s.title, issuer: s.issuer, accountable_team: s.accountable_team, version: s.version,
        effective_from: s.effective_from, clause_id: clause, excerpt: s.clauses[clause].text }); }
  };
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setBusy(true); setError("");
    try { const res = await gov.register({ source_ref: ref, ...form, expected_revision: expected }); onDone(res.document); }
    catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };
  const field = (k: string, label: string, type = "text") => <label key={k}>{label}<input type={type} required value={form[k] ?? ""} onChange={(e) => setForm({ ...form, [k]: e.target.value })} /></label>;
  return <form className="bp-card bp-form" onSubmit={submit}>
    <h3>{docId ? "Publish the next revision" : "Register a governance document"}</h3>
    <p className="muted small">Only permitted sources can be registered. The details are checked against the source; AnalytIQ records applicability, it does not approve the document itself.</p>
    <label>Permitted source<select required value={ref} onChange={(e) => choose(e.target.value)}><option value="">Choose a source</option>
      {options.map((s) => <option key={s.ref} value={s.ref}>{s.doc_id} · {s.title} · version {s.version} (effective {s.effective_from})</option>)}</select></label>
    {ref && <>{field("doc_id", "Document ID")}{field("title", "Title")}{field("issuer", "Issuing authority")}{field("accountable_team", "Accountable team")}
      {field("version", "Version")}{field("effective_from", "Effective from", "date")}{field("clause_id", "Clause")}
      <label>Permitted excerpt (quoted from the clause)<textarea required rows={3} value={form.excerpt ?? ""} onChange={(e) => setForm({ ...form, excerpt: e.target.value })} /></label></>}
    {error && <Notice kind="error">{error}</Notice>}
    <div className="bp-actions"><button className="btn" disabled={busy || !ref}>{docId ? "Publish revision" : "Register"}</button></div>
  </form>;
}

function AssessmentView({ id }: { id: string }) {
  const actor = useActor();
  const { data, error, retry } = useLoad<AssessmentRecord>((s) => gov.assessment(id, s), [id, actor]);
  if (!data) return <><Back /><Loading error={error} retry={retry} what="assessment" /></>;
  const a = data; const s = a.snapshot;
  return <>
    <Back asset={a.asset} />
    <Heading kicker={<>Assessment record · <span className="mono">{a.id}</span></>}>{a.judgment_label}</Heading>
    <p>{a.reason}</p>
    <p className="muted small">Recorded by {a.actor_name} on {when(a.at)} against workbook <span className="mono">{s.workbook.sha}</span>
      {s.acknowledged_changes && " · the reviewer confirmed changes made during the review"}.</p>
    {a.changes_since.length > 0 ? <Notice kind="info"><strong>Changed since this assessment:</strong><ul>{a.changes_since.map((c) => <li key={c}>{c}</li>)}</ul>
      What is shown below is what the decision rested on.</Notice> : <Notice kind="ok">Nothing it rested on has changed since.</Notice>}
    {s.clause && <Card title={`Clause as assessed: ${s.clause.doc_id}${s.clause.authority === "challenge_workbook" ? "" : ` §${s.clause.clause_id}, revision ${s.clause.revision}`}`}>
      <blockquote className="bg-clause">{s.clause.text}</blockquote>
      <p className="muted small">{s.clause.authority_label}{s.clause.version && ` · version ${s.clause.version}`}{s.clause.effective_from && ` · effective from ${s.clause.effective_from}`}</p></Card>}
    <Card title="Matching facts"><ul className="bp-plain">{s.facts.map((f, i) => <li key={i}>{f.text}</li>)}</ul>
      {s.checks.map((c) => <p key={c.id} className="small">{c.id} v{c.version}: {c.text}</p>)}
      <p className="muted small">Owner at the time: {s.owner ? `${s.owner.name} ${s.owner.id}` : "none"}</p></Card>
    <Card title="Evidence as cited"><ul className="bg-evs">{s.evidence.map((e) => <li key={e.id} className="bg-ev"><strong>{e.label}</strong>
      <div className="bg-meta"><Authority label={e.authority_label} /> <Locator e={e} /></div>
      <details><summary className="small">Values at the time</summary><pre className="bg-original">{JSON.stringify(e.value, null, 2)}</pre></details></li>)}</ul></Card>
  </>;
}
