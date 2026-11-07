import { useEffect, useRef, useState } from "react";
import type { FollowUp, Snapshot } from "../api/briefings";
import { SnapshotEvidence } from "./BriefingReports";
import "./report-register.css";

type Person = { id: string; name: string; status: string; evidence: string };
type Step = "requested" | "prepared" | "approved" | "returned";
type Mode = "chart" | "table";
type Entry = {
  id: string; title: string; baseline_title: string; kind: string; platform: string; origin: "Estate" | "Employee";
  owner: Person | null; product: string; market: string; created: string | null; modified: string | null;
  last_use_month: string | null; usage_window: string[]; views: number | null; model_id: string | null;
  refresh: string | null; cadence: string | null; lifecycle: string; issues: string[];
  model_product: string | null; teams: string[] | null; revision: number; display_mode: Mode | null; published_at: string | null; change_status?: Step | null;
};
type Audit = {
  _id: string; kind: Step; actor_name: string; actor_id: string; requester_id: string; request_id: string; at: string;
  seq: number; note: string; evidence_ref: string; evidence_value: string; base_title: string; title: string | null;
  base_display_mode: Mode | null; display_mode: Mode | null; revision: number;
};
type LinkedAction = Pick<FollowUp, "_id" | "title" | "owner" | "status" | "created_by" | "history"> & {
  owner_id?: string; created_by_id?: string; due_date?: string; created_at: string;
  briefing_snapshot?: Snapshot; sample?: boolean;
};
type Detail = Entry & { evidence: Record<string, string>; history: Audit[]; linked_actions: LinkedAction[] };
type Register = { reports: Entry[]; people: Person[]; store: string };

const base = "/api/report-register";
const progress = { requested: "Awaiting owner edit", prepared: "Awaiting independent review", approved: "Published in app", returned: "Returned for changes" };
const states: Record<Step, string> = { requested: "Change requested", prepared: "Edit prepared", approved: "Revision published", returned: "Edit returned" };
const batch = 8;
function message(error: unknown) { return error instanceof Error ? error.message : "Could not load the register."; }
async function read<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, body === undefined ? undefined : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!response.ok) {
    const failure = await response.json().catch(() => ({}));
    throw new Error(typeof failure.detail === "string" ? failure.detail : `The request failed (${response.status}).`);
  }
  return response.json();
}
const pretty = (text: string) => text.replaceAll("_", " ");
const month = (value: string) => new Date(value + "-01T00:00:00Z").toLocaleDateString("en", { month: "short", year: "numeric", timeZone: "UTC" });
const timestamp = (value: string) => new Date(value).toLocaleString();

export function ReportRegister({ initialReportId }: { initialReportId?: string } = {}) {
  const [data, setData] = useState<Register | null>(null);
  const [id, setId] = useState(initialReportId || "BR-SHIPMENTS");
  const [report, setReport] = useState<Detail | null>(null);
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState("");
  const [issue, setIssue] = useState("");
  const [page, setPage] = useState(0);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  const detailBox = useRef<HTMLElement>(null);
  useEffect(() => {
    let live = true;
    setError("");
    read<Register>(base).then(d => { if (live) setData(d); }).catch(e => { if (live) setError(message(e)); });
    return () => { live = false; };
  }, [reload]);
  useEffect(() => { if (initialReportId) setId(initialReportId); }, [initialReportId]);
  useEffect(() => {
    let live = true;
    setReport(null);
    setError("");
    read<Detail>(`${base}/${encodeURIComponent(id)}`).then(d => { if (live) setReport(d); })
      .catch(e => { if (live) setError(message(e)); });
    return () => { live = false; };
  }, [id, reload]);
  const rows = (data?.reports || []).filter(r =>
    (!scope || r.origin === scope) &&
    (!issue || (issue === "Pending edit" ? !!r.change_status && r.change_status !== "approved" : r.issues.includes(issue))) &&
    `${r.id} ${r.title} ${r.baseline_title} ${r.owner?.name || ""} ${r.product} ${r.market} ${r.platform}`.toLowerCase().includes(query.trim().toLowerCase())
  ).sort((a, b) => a.origin.localeCompare(b.origin) || a.id.localeCompare(b.id));
  const pages = Math.max(1, Math.ceil(rows.length / batch));
  const current = Math.min(page, pages - 1);
  const estateCount = data?.reports.filter(r => r.origin === "Estate").length || 0;
  function saved(d: Detail) {
    setReport(prev => prev?.id === d.id ? d : prev);
    const last = d.history[d.history.length - 1];
    setData(prev => prev && { ...prev, reports: prev.reports.map(r => r.id === d.id ? { ...d, change_status: last.kind } : r) });
    if (last.kind === "approved") window.dispatchEvent(new CustomEvent("report-revision-published", {
      detail: { report_id: d.id, title: d.title, display_mode: d.display_mode, revision: d.revision },
    }));
  }
  return <section className="rr" aria-label="BI report register">
    <header><h2>Report register</h2><p>Look up ownership and usage, investigate maintenance issues, and review shared report changes.</p></header>
    {data && <div className="rr-count"><strong>{estateCount}</strong> workbook assets <span>·</span> <strong>{data.reports.length - estateCount}</strong> employee reports</div>}
    {error && <div role="alert" className="rr-error">{error} <button onClick={() => setReload(x => x + 1)}>Retry</button></div>}
    <div className="rr-grid">
      <section className="rr-card rr-browser" aria-label="Find reports">
        <label>Find a report<input type="search" value={query} placeholder="Search title, owner, market or ID" onChange={e => { setQuery(e.target.value); setPage(0); }} /></label>
        <div className="rr-filters">
          <label>Source<select value={scope} onChange={e => { setScope(e.target.value); setPage(0); }}><option value="">All sources</option><option>Employee</option><option>Estate</option></select></label>
          <label>Maintenance<select value={issue} onChange={e => { setIssue(e.target.value); setPage(0); }}><option value="">All reports</option>{["Ownership", "Product scope mismatch", "Model refresh", "Open governance signal", "Retirement review", "Pending edit"].map(i => <option key={i}>{i}</option>)}</select></label>
        </div>
        <p className="rr-caption" aria-live="polite">{data ? `${rows.length} matching reports` : "Loading reports…"}</p>
        <div className="rr-items">{rows.slice(current * batch, (current + 1) * batch).map(r =>
          <button key={r.id} className="rr-item" aria-pressed={r.id === id} onClick={() => {
            setId(r.id);
            if (window.matchMedia("(max-width: 850px)").matches) detailBox.current?.scrollIntoView({ behavior: "smooth", block: "start" });
          }}><strong>{r.title}</strong><span>{r.id} · {r.platform} · {r.kind}</span>
            {(r.change_status || r.issues.length > 0) && <small>{r.change_status ? progress[r.change_status] : r.issues.join(" · ")}</small>}
          </button>)}</div>
        {data && !rows.length && <p>No reports match these filters.</p>}
        {pages > 1 && <nav className="rr-paging" aria-label="Register pages"><button disabled={!current} onClick={() => setPage(current - 1)}>Previous</button>
          <span>{current + 1} / {pages}</span><button disabled={current === pages - 1} onClick={() => setPage(current + 1)}>Next</button></nav>}
      </section>
      <section className="rr-detail" ref={detailBox} aria-label="Selected report">
        {report && data ? <ReportDetail key={report.id} report={report} people={data.people} store={data.store} onSave={saved}
          onReload={() => setReload(x => x + 1)} /> : <p>{error ? "Report details are unavailable." : "Loading report details…"}</p>}
      </section>
    </div>
  </section>;
}

function ReportDetail({ report: r, people, store, onSave, onReload }: { report: Detail; people: Person[]; store: string;
  onSave: (result: Detail) => void; onReload: () => void }) {
  const last = r.history.at(-1);
  const step: Step = last?.kind === "requested" || last?.kind === "returned" ? "prepared" : last?.kind === "prepared" ? "approved" : "requested";
  const actors = people.filter(p => step === "prepared" ? p.id === r.owner?.id :
    step === "approved" ? p.id !== last?.actor_id && p.id !== last?.requester_id : p.id !== r.owner?.id);
  const [actor, setActor] = useState("");
  const [note, setNote] = useState("");
  const [title, setTitle] = useState(r.title);
  const [mode, setMode] = useState<Mode>(r.display_mode || "chart");
  const [source, setSource] = useState(Object.keys(r.evidence)[0]);
  const [pending, setPending] = useState(false);
  const [problem, setProblem] = useState("");
  useEffect(() => {
    setTitle(last?.kind === "returned" ? last.title || r.title : r.title);
    setMode(last?.kind === "returned" ? last.display_mode || "chart" : r.display_mode || "chart");
    setActor(""); setNote(""); setProblem("");
  }, [last?._id, r.title, r.display_mode]);
  const actorId = actors.some(p => p.id === actor) ? actor : actors[0]?.id || "";
  async function submit(kind: Step) {
    setPending(true); setProblem("");
    try {
      onSave(await read<Detail>(`${base}/${encodeURIComponent(r.id)}/changes`, {
        kind, actor_id: actorId, expected_seq: last?.seq || 0, note, evidence_ref: source,
        ...(kind === "prepared" ? { title, display_mode: r.origin === "Employee" ? mode : null } : {}),
      }));
    } catch (e) { setProblem(message(e)); }
    finally { setPending(false); }
  }
  const employee = r.origin === "Employee";
  const facts = [
    [employee ? "Assigned app steward" : "Workbook owner", r.owner ? `${r.owner.name} · ${r.owner.status}` : "Missing from workbook"],
    ["Product / market", `${r.product} · ${r.market}`],
    ...(employee ? [["Created by", "App-defined view · individual creator unrecorded"], ["Pinned by teams", r.teams?.join(", ") || "No teams currently pin this report"], ["Published display", r.display_mode === "table" ? "Comparison table" : "Chart"],
      ["Reviewed publication", r.published_at ? timestamp(r.published_at) : "Original app view"]] : [
      ["Workbook asset title", r.baseline_title], ["Reviewed register alias", r.revision ? r.title : "No alias published"],
      ["Created", r.created || "Unrecorded"], ["Created by", "Unrecorded in source"],
      ["Last modified", r.modified || "Unrecorded"], ["Latest recorded use", r.last_use_month ? month(r.last_use_month) : "No usage recorded"],
      ["Views in usage window", r.views === null ? "Unrecorded" : `${r.views.toLocaleString()} · ${r.usage_window.map(month).join(" – ")}`],
      ["Model refresh", `${r.model_id} · ${r.refresh} · ${r.cadence}`], ["Last refresh time", "Unrecorded in source"],
      ["Model product scope", r.model_product || "Unrecorded"], ["Lifecycle", pretty(r.lifecycle)],
    ]),
  ];
  return <>
    <article className="rr-card"><div className="rr-kicker">{r.id} · {r.platform} · {r.kind}</div>
      <h3>{r.title}</h3><p className="rr-revision">{r.revision ? `Reviewed revision ${r.revision}` : employee ? "Original app view" : "Workbook baseline"}</p>
      {r.issues.length > 0 && <div className="rr-flags">{r.issues.map(i => <span key={i}>{i}</span>)}</div>}
      <dl className="rr-facts">{facts.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>
      <details className="rr-evidence"><summary>Source evidence ({Object.keys(r.evidence).length})</summary>
        <dl>{Object.entries(r.evidence).map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl></details>
      {!employee && <button className="rr-open" onClick={() => window.dispatchEvent(new CustomEvent("open-entity", { detail: r.id }))}>Open in Estate Explorer</button>}
    </article>
    <section className="rr-card"><div className="rr-kicker">Change control</div>
      <h3>{step === "requested" ? "Request a change" : step === "prepared" ? "Prepare the owner’s edit" : "Review the proposed edit"}</h3>
      <p className="rr-caption">Named demo participants. {employee ? "Approved changes publish to this app’s shared report." : "Approved aliases appear in the BI register. Estate Explorer shows the workbook title."}{store === "memory" ? " In-memory records last until the server restarts." : ""}</p>
      {last && step !== "requested" && <div className="rr-proposal"><strong>{states[last.kind]} · {last.actor_name}</strong>
        <p>{last.note}</p>{last.title && <p>{last.base_title === last.title ? last.title : `${last.base_title} → ${last.title}`}{employee && last.base_display_mode !== last.display_mode ? ` · ${last.base_display_mode} → ${last.display_mode}` : ""}</p>}</div>}
      {problem && <div className="rr-error" role="alert">{problem} <button type="button" onClick={onReload}>Reload report</button></div>}
      {actors.length === 0 ? <p className="rr-proposal">An active report owner is required to prepare this edit. Resolve the ownership issue to proceed.</p> :
      <form onSubmit={e => { e.preventDefault(); void submit(step); }} className="rr-form">
        <label>{step === "requested" ? "Requester" : step === "prepared" ? "Report owner" : "Independent reviewer"}
          <select value={actorId} onChange={e => setActor(e.target.value)}>{actors.map(p => <option value={p.id} key={p.id}>{p.name} · {p.id}</option>)}</select></label>
        {step === "prepared" && <><label>{employee ? "Shared report title" : "Register display alias"}<input required maxLength={150} value={title} onChange={e => setTitle(e.target.value)} /></label>
          {employee && <label>Report display<select value={mode} onChange={e => setMode(e.target.value as Mode)}><option value="chart">Chart</option><option value="table">Comparison table</option></select></label>}</>}
        <label>Supporting evidence<select value={source} onChange={e => setSource(e.target.value)}>{Object.keys(r.evidence).map(k => <option key={k}>{k}</option>)}</select></label>
        <p className="rr-caption rr-source-value">{r.evidence[source]}</p>
        <label>{step === "requested" ? "What should change and why?" : step === "prepared" ? "Owner’s change note" : "Review decision note"}
          <textarea required maxLength={800} rows={2} value={note} placeholder={step === "requested" ? "Describe the change for the report owner" : step === "prepared" ? "Explain how this edit addresses the request" : "Record what you checked"} onChange={e => setNote(e.target.value)} /></label>
        <div className="rr-buttons"><button className="rr-primary" disabled={pending || !note.trim() || (step === "prepared" && (!title.trim() || (title.trim() === r.title && (!employee || mode === r.display_mode))))}>
          {pending ? "Saving…" : step === "requested" ? "Submit change request" : step === "prepared" ? "Send edit for review" : "Approve and publish"}</button>
          {step === "approved" && <button type="button" disabled={pending || !note.trim()} onClick={() => void submit("returned")}>Return to owner</button>}</div>
      </form>}
    </section>
    <section className="rr-card"><h3>Linked follow-ups</h3>
      {r.linked_actions.length ? <><p className="rr-caption">Up to 20 recent actions linked to this report.</p>
        {r.linked_actions.map(a => <details key={a._id} className="rr-linked">
          <summary>{a.title} · {pretty(a.status)}</summary>
          <p>{a.sample ? "Sample action · " : ""}Assigned to {a.owner}{a.owner_id ? ` (${a.owner_id})` : ""}{a.due_date ? ` · Due ${a.due_date}` : ""}</p>
          <p>Created by {a.created_by}{a.created_by_id ? ` (${a.created_by_id})` : ""} · {timestamp(a.created_at)}</p>
          {a.briefing_snapshot && <SnapshotEvidence snapshot={a.briefing_snapshot} />}
          <details><summary>Action history</summary><ol>{a.history.map((e, i) => <li key={i}>{e.by} · {timestamp(e.at)} · {pretty(e.change)}{e.to ? ` → ${pretty(e.to)}` : ""}{e.note ? ` · ${e.note}` : ""}</li>)}</ol></details>
        </details>)}</> : <p className="rr-caption">No follow-ups are linked to this report.</p>}
    </section>
    <section className="rr-card"><h3>Review history</h3>{r.history.length ? <ol className="rr-history">{[...r.history].reverse().map(h =>
      <li key={h._id}><strong>{states[h.kind]}{h.kind === "approved" ? ` · revision ${h.revision}` : ""}</strong><span>{h.actor_name} · {timestamp(h.at)}</span><p>{h.note}</p>
        {h.title && <p>{h.base_title === h.title ? h.title : `${h.base_title} → ${h.title}`}{h.base_display_mode !== h.display_mode ? ` · ${h.base_display_mode} → ${h.display_mode}` : ""}</p>}
        <details><summary>{h.evidence_ref}</summary><p>{h.evidence_value}</p><small>Change {h.request_id.slice(0, 8)} · Event {h.seq}</small></details></li>)}</ol> :
        <p className="rr-caption">Submitted changes and reviewer decisions will appear here.</p>}</section>
  </>;
}
