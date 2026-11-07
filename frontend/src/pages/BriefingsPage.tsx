import { useEffect, useId, useLayoutEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { briefingRequest, completeAction, type Briefing, type FollowUp, type Team, type ViewId } from "../api/briefings";
import { Icon } from "../components/Icon";
import { MonthlyHistory } from "./BriefingHistory";
import { amount, comparison, month } from "../lib/briefingFormat";
import { ReportCard, SnapshotEvidence, WorkbookEvidence } from "./BriefingReports";
import { ReportRegister } from "./ReportRegister";
import "../briefings.css";

const metricSubject = { sales: "Net sales were", shipments: "Shipments were", otif: "On-time, in-full delivery was" };
const teamLabel = { commercial: "Commercial", supply: "Supply" };
type Overlay =
  | { kind: "choose" | "meeting" }
  | { kind: "report"; viewId: ViewId }
  | { kind: "propose"; viewId?: ViewId }
  | { kind: "action"; action: FollowUp };

function Modal({ title, meeting, busy, onClose, children }: {
  title: string; meeting?: boolean; busy: boolean; onClose: () => void; children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useLayoutEffect(() => {
    const dialog = ref.current!;
    const opener = document.activeElement;
    dialog.showModal();
    return () => {
      dialog.close();
      if (opener instanceof HTMLElement && opener.isConnected) opener.focus({ preventScroll: true });
    };
  }, []);
  return <dialog ref={ref} className={`bf-dialog${meeting ? " bf-meeting" : ""}`} aria-labelledby={titleId}
    onCancel={e => { e.preventDefault(); if (!busy) onClose(); }}>
    <header className="bf-dialog-head"><h2 id={titleId}>{title}</h2>
      <button type="button" className="bf-btn" disabled={busy} onClick={onClose}>
        {meeting ? "Exit meeting mode" : "Close"} <Icon name="close" size={14} /></button></header>
    {children}
  </dialog>;
}

function TeamBriefing({ team, initialView, onRegister }: { team: Team; initialView?: ViewId; onRegister: (reportId: string) => void }) {
  const [data, setData] = useState<Briefing | null>(null);
  const [overlay, setOverlay] = useState<Overlay | null>(() => initialView ? { kind: "report", viewId: initialView } : null);
  const [loadError, setLoadError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<ViewId[]>([]);
  useEffect(() => {
    let active = true;
    setLoadError("");
    briefingRequest<Briefing>(team).then(result => { if (active) setData(result); })
      .catch(e => { if (active) setLoadError(e.message); });
    return () => { active = false; };
  }, [team, attempt]);

  function open(next: Overlay) { setError(""); setNotice(""); setOverlay(next); }
  async function save(operation: () => Promise<Briefing>, message: string) {
    setBusy(true);
    setError("");
    try { setData(await operation()); setOverlay(null); setNotice(message); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not save. Please try again."); }
    finally { setBusy(false); }
  }

  if (!data) return <div className="bf-loading" role={loadError ? "alert" : "status"}>
    {loadError ? <><p>Could not open the {teamLabel[team]} briefing. {loadError}</p>
      <button type="button" className="bf-btn" onClick={() => setAttempt(n => n + 1)}>Try again</button></> : "Loading the briefing…"}</div>;

  const brief = data;
  const pinned = brief.selected_view_ids.flatMap(id => brief.views.filter(view => view.id === id));
  const activeView = overlay && "viewId" in overlay ? brief.views.find(view => view.id === overlay.viewId) : undefined;
  const recent = brief.recent_actions;
  const activeActions = recent.filter(action => ["open", "in_progress", "blocked"].includes(action.status));
  const meetingAction = activeActions.find(action => action._id === brief.action?._id) ?? activeActions[0];

  function propose(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    const title = String(values.get("title") || "").trim();
    const ownerId = String(values.get("owner_id") || "");
    if (!title || !ownerId) { setError("Enter a follow-up and the name of its owner."); return; }
    void save(async () => {
      await briefingRequest(team, "/actions", "POST", {
        title, owner_id: ownerId, due_date: values.get("due_date"), version: brief.version, view_id: activeView?.id,
      });
      return briefingRequest<Briefing>(team);
    }, "Follow-up saved with its source snapshot.");
  }
  function finish(event: FormEvent<HTMLFormElement>, action: FollowUp) {
    event.preventDefault();
    const outcome = String(new FormData(event.currentTarget).get("outcome") || "").trim();
    if (!outcome) { setError("Describe what was done."); return; }
    void save(async () => {
      await completeAction(team, action._id, outcome);
      return briefingRequest<Briefing>(team);
    }, "Outcome recorded. The follow-up is marked done.");
  }

  const scope = `${brief.product} in ${brief.market}`;
  const meeting = overlay?.kind === "meeting";
  const cards = (wall: boolean) => <div className={`bf-grid bf-grid-${pinned.length}`}>{pinned.map((view, index) =>
    <ReportCard key={view.id} periods={brief} view={view} index={index} onOpen={wall ? undefined : () => open({ kind: "report", viewId: view.id })} />)}</div>;
  const heading = <div className="bf-intro">
    <p className="bf-kicker">{teamLabel[team]} briefing <span> / </span> {month(brief.period)}</p>
    <h1>{scope}</h1>
    <p className="bf-dek">{pinned.map(view => `${metricSubject[view.id]} ${comparison(view, brief.previous_period).replace(/^Unchanged/, "unchanged").replace(/^Compared/, "compared")}`).join(". ")}.</p>
  </div>;
  const followupTitle = activeView ? `Review ${activeView.title.toLowerCase()} for ${brief.product} in ${brief.market}` : brief.suggested_action;
  const current = activeView?.action;
  const existing = overlay?.kind === "action" ? overlay.action : null;

  return <>
    <div className="bf-intro-row">{heading}<button type="button" className="bf-btn" onClick={() => open({ kind: "meeting" })}>
      <Icon name="panel" size={15} /> Meeting mode</button></div>
    {notice && <p role="status" className="bf-notice"><Icon name="check" size={15} /> {notice}</p>}
    <div className="bf-section-head"><div><h2>Reports in this briefing</h2>
      <p>{pinned.length} pinned {pinned.length === 1 ? "view" : "views"} · Compared with {month(brief.previous_period)}</p></div>
      <button type="button" className="bf-btn" onClick={() => { setSelected([...brief.selected_view_ids]); open({ kind: "choose" }); }}>Choose reports</button></div>
    {cards(false)}
    {brief.route && <details className="bf-disclosure bf-route"><summary>Routing reference · {brief.route.source} · {brief.route.mode}</summary>
      <p>Undated routing record. The workbook does not attribute the monthly change to this route.</p>
      <WorkbookEvidence evidence={brief.route.evidence} /></details>}
    <section className="bf-next"><div><span className="bf-kicker">{brief.action ? "Assigned follow-up" : "Proposed follow-up"}</span>
      <h2>{brief.action?.title ?? brief.suggested_action}</h2>
      {brief.action && <p className="bf-origin">{brief.action.owner} · Due {brief.action.due_date} · {brief.action.status.replaceAll("_", " ")}</p>}</div>
      <button type="button" className="bf-btn bf-primary" onClick={() => {
        open(brief.action ? { kind: "action", action: brief.action } : { kind: "propose" });
      }}>{brief.action ? "View follow-up" : "Assign follow-up"}<Icon name="arrowRight" size={15} /></button>
    </section>
    <section className="bf-history"><div className="bf-section-head"><div><h2>From our last briefing</h2>
      <p>{activeActions.length} open {activeActions.length === 1 ? "follow-up" : "follow-ups"} · {teamLabel[team]} team</p></div></div>
      {recent.length === 0 ? <p className="bf-empty">This team has no saved follow-ups yet.</p> :
        <ul className="bf-action-list">{recent.map(action => <li key={action._id}><button type="button" onClick={() => open({ kind: "action", action })}>
          <span><strong>{action.title}</strong><small>{action.owner} · Due {action.due_date}</small></span>
          <span className="bf-status">{action.status.replaceAll("_", " ")}</span><Icon name="chevron" size={14} /></button></li>)}</ul>}
    </section>
    <footer className="bf-footnote">Demo participant · {brief.actor.name} ({brief.actor.id}) · {brief.actor.role}<br />
      {brief.storage_mode === "mongodb" ? "Shared MongoDB storage" : "Session storage · resets when the demo server restarts"}</footer>
    {overlay && <Modal key={overlay.kind} title={meeting ? "Meeting mode" : overlay.kind === "choose" ? "Choose reports" :
      overlay.kind === "report" ? (activeView?.report ?? "Report") : overlay.kind === "propose" ? "Assign follow-up" : "Follow-up details"}
      meeting={meeting} busy={busy} onClose={() => setOverlay(null)}>
      {error && <p className="bf-error" role="alert">{error} <button type="button" className="bf-text-btn" onClick={() => {
        setOverlay(null); setData(null); setAttempt(n => n + 1);
      }}>Reload briefing</button></p>}
      {meeting && <div className="bf-wall">{heading}{cards(true)}
        <div className="bf-wall-agenda"><span className="bf-kicker">{meetingAction ? "Open follow-up" : "Meeting agenda"}</span><h2>{meetingAction?.title ?? brief.suggested_action}</h2>
        <p>{meetingAction ? `${meetingAction.owner} · Due ${meetingAction.due_date} · ${meetingAction.status.replaceAll("_", " ")}` : "Proposed for discussion"}</p>
        {activeActions.length > 1 && <p>{activeActions.length - 1} more open {activeActions.length === 2 ? "follow-up" : "follow-ups"} for {teamLabel[team]}</p>}</div>
        <p className="bf-origin">Synthetic workbook · {month(brief.previous_period)} and {month(brief.period)}</p>
      </div>}
      {overlay.kind === "choose" && <>
        <p className="bf-dialog-copy">Pin the views the {teamLabel[team]} team needs for its briefing. Keep at least one.</p>
        <div className="bf-choices">{brief.views.map(view => <label key={view.id}>
          <input type="checkbox" checked={selected.includes(view.id)} disabled={busy}
            onChange={e => { const checked = e.target.checked; setSelected(ids => checked ? [...ids, view.id] : ids.filter(id => id !== view.id)); }} />
          <span><strong>{view.title}</strong><small>{view.report}</small></span></label>)}</div>
        <div className="bf-dialog-foot"><span>{selected.length} selected</span><button type="button" className="bf-btn bf-primary" disabled={busy || !selected.length}
          onClick={() => void save(() => briefingRequest<Briefing>(team, "/selection", "PUT", { view_ids: selected }), `Saved the ${teamLabel[team]} briefing.`)}>
          {busy ? "Saving…" : "Save selection"}</button></div>
      </>}
      {overlay.kind === "report" && activeView && <div className="bf-report-detail">
        <p className="bf-kicker">Employee report · {activeView.report_id} · {activeView.revision ? `Revision ${activeView.revision}` : "Workbook baseline"}</p>
        <p className="bf-dialog-copy">{scope} · {month(brief.period)} · Synthetic workbook</p>
        <div className="bf-report-value"><strong>{amount(activeView.current, activeView.unit)}</strong>
          <span>{activeView.title}<small>{comparison(activeView, brief.previous_period)}</small></span></div>
        <MonthlyHistory view={activeView} />
        <h3>Source and filters</h3><WorkbookEvidence evidence={activeView.evidence} />
        <div className="bf-dialog-foot"><button type="button" className="bf-text-btn" onClick={() => onRegister(activeView.report_id)}>View in BI register</button>
          <button type="button" className="bf-btn bf-primary" onClick={() => open(current
            ? { kind: "action", action: current }
            : { kind: "propose", viewId: activeView.id })}>{current ? "View follow-up" : "Propose follow-up"}</button></div>
      </div>}
      {overlay.kind === "propose" && <form className="bf-form" onSubmit={propose}>
        <p className="bf-dialog-copy">{teamLabel[team]} · {activeView?.report ?? scope} · {month(brief.period)}</p>
        <p className="bf-origin">Recorded by {brief.actor.name} ({brief.actor.id})</p>
        <label><span id="brief-title-label">Follow-up</span><textarea aria-labelledby="brief-title-label" name="title" defaultValue={followupTitle} required minLength={3} maxLength={200} rows={2} /></label>
        <div className="bf-form-row"><label><span id="brief-owner-label">Owner</span><select aria-labelledby="brief-owner-label" name="owner_id" defaultValue={brief.actor.id} required>
          {brief.owners.map(person => <option key={person.id} value={person.id}>{person.name} · {person.role}</option>)}</select></label>
          <label>Due date<input type="date" name="due_date" required /></label></div>
        <p className="bf-origin">The source values and workbook rows from this briefing will be saved with the action.</p>
        <div className="bf-dialog-foot"><button type="submit" className="bf-btn bf-primary" disabled={busy}>{busy ? "Saving…" : "Save follow-up"}</button></div>
      </form>}
      {existing && <div className="bf-action-detail"><h3>{existing.title}</h3>
        <p className="bf-origin">{existing.owner} ({existing.owner_id}) · Due {existing.due_date} · {existing.status.replaceAll("_", " ")}</p>
        {existing.outcome && <p><strong>Recorded outcome</strong><br />{existing.outcome}</p>}
        <p className="bf-origin">Created by {existing.created_by} ({existing.created_by_id})</p>
        <SnapshotEvidence snapshot={existing.briefing_snapshot} />
        <details className="bf-disclosure"><summary>Action history</summary><ol className="bf-audit">{existing.history.map((event, i) =>
          <li key={i}>{event.by}{event.by_id && ` (${event.by_id})`} · {event.change === "created" ? "Created" : event.to?.replaceAll("_", " ") || event.change}
            <small>{new Date(event.at).toLocaleString()} {event.note && `· ${event.note}`}</small></li>)}</ol></details>
        {existing.allowed.includes("done") && <form onSubmit={e => finish(e, existing)} className="bf-form">
          <p className="bf-origin">Updating as {brief.actor.name} ({brief.actor.id})</p>
          <label>What was done?<textarea name="outcome" rows={3} maxLength={1000} required /></label>
          <div className="bf-dialog-foot"><button className="bf-btn bf-primary" disabled={busy}>{busy ? "Saving…" : "Mark done"}</button></div>
        </form>}
      </div>}
    </Modal>}
  </>;
}

export function BriefingsPage() {
  const [initialView, setInitialView] = useState<ViewId | undefined>(() => {
    const id = new URLSearchParams(window.location.search).get("view");
    return id === "sales" || id === "shipments" || id === "otif" ? id : undefined;
  });
  const [team, setTeam] = useState<Team>(initialView === "otif" ? "supply" : "commercial");
  const [reportId, setReportId] = useState(() => new URLSearchParams(window.location.search).get("report") || undefined);
  const [register, setRegister] = useState(Boolean(reportId));
  return <main className="bf-page">
    <nav className="bf-tabs" aria-label="Briefings workspace">
      <button type="button" aria-current={!register ? "page" : undefined} onClick={() => setRegister(false)}>Team briefings</button>
      <button type="button" aria-current={register ? "page" : undefined} onClick={() => { setInitialView(undefined); setReportId(undefined); setRegister(true); }}>BI report register</button>
    </nav>
    {register ? <ReportRegister initialReportId={reportId} /> : <div className="bf-body">
      <div className="bf-toolbar"><div className="bf-teams" role="group" aria-label="Briefing team">{(["commercial", "supply"] as const).map(t =>
        <button type="button" key={t} aria-pressed={team === t} onClick={() => { setInitialView(undefined); setTeam(t); }}>{teamLabel[t]}</button>)}</div>
        <span className="bf-sample">Synthetic workbook</span></div>
      <TeamBriefing key={team} team={team} initialView={initialView}
        onRegister={id => { setInitialView(undefined); setReportId(id); setRegister(true); }} />
    </div>}
  </main>;
}
