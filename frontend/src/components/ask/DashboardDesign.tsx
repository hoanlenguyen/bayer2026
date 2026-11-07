import { useEffect, useRef, useState, type FormEvent } from "react";
import { builderPath, dashboardUrl, type BuildAnswer, type BuildErrorEvent, type BuildEvent, type BuildResultEvent, type DesignState } from "../../api/dashboardBuilder";
import { readEvents } from "../../api/client";
import { readHandoff } from "../../api/handoff";
import { navigate } from "../../lib/navigation";
import { Icon } from "../Icon";
import { BuildHandoff, type BuildSession } from "./BuildHandoff";
import "./dashboard-design.css";

function Brief({ state }: { state: DesignState }) {
  return <div className="db-brief"><p className="db-label">Interpreted brief</p>
    <ul>{state.summary.map((line, i) => {
      const m = /^(Purpose|Product|KPIs|Months|Source|Visuals): (.*)$/.exec(line);
      return <li key={i}>{m ? <><strong>{m[1]}:</strong> {m[2]}</> : line}</li>;
    })}</ul></div>;
}

function DesignQuestion({ state, pending, submit }: {
  state: DesignState; pending: boolean; submit: (answer: BuildAnswer) => void;
}) {
  const question = state.question!;
  const [problem, setProblem] = useState("");
  const [choices, setChoices] = useState<string[]>([]);
  const prompt = useRef<HTMLLegendElement>(null);
  useEffect(() => { prompt.current?.focus({ preventScroll: true }); }, []);
  function answer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    let value: BuildAnswer;
    if (question.kind === "period") {
      const start = String(form.get("start") || ""), end = String(form.get("end") || "");
      if (!start || !end || start > end) { setProblem("Choose a start month on or before the end month."); return; }
      value = { start, end };
    } else if (question.kind === "multi") {
      value = form.getAll("choice").map(String);
      if (!value.length) { setProblem("Select at least one option."); return; }
    } else {
      value = String(form.get("choice") || "").trim();
      if (!value) { setProblem("Enter an answer to continue."); return; }
    }
    setProblem(""); submit(value);
  }
  return <form className="db-question" onSubmit={answer}><fieldset disabled={pending}>
    <legend ref={prompt} tabIndex={-1}>{question.prompt}</legend>
    {question.kind === "text" && <textarea aria-label={question.prompt} name="choice" rows={2} required minLength={5} maxLength={240}/>}
    {question.kind === "single" && <select aria-label={question.prompt} name="choice" defaultValue="" required>
      <option value="" disabled>Choose an option</option>
      {question.options.map(option => <option value={option.value} key={option.value}>{option.label}</option>)}
    </select>}
    {question.kind === "multi" && <div className="db-options">{question.options.map(option => <label key={option.value}>
      <input type="checkbox" name="choice" value={option.value} checked={choices.includes(option.value)} onChange={e => {
        const checked = e.target.checked;
        setChoices(prior => !checked ? prior.filter(v => v !== option.value)
          : option.value === "all" ? ["all"] : [...prior.filter(v => v !== "all"), option.value]);
      }}/><span>{option.label}</span></label>)}</div>}
    {question.kind === "period" && <>
      {(question.min_period || question.max_period) && <p className="db-caption">Workbook coverage · {question.min_period} to {question.max_period}</p>}
      <div className="db-months"><label>Start month<input name="start" type="month" min={question.min_period} max={question.max_period} defaultValue={question.min_period} required /></label>
        <label>End month<input name="end" type="month" min={question.min_period} max={question.max_period} defaultValue={question.max_period} required /></label></div></>}
    {problem && <p className="text-bad" role="alert">{problem}</p>}
    <button type="submit" className="btn">{pending ? "Saving…" : "Continue"}<Icon name="arrowRight" size={14}/></button>
  </fieldset></form>;
}

export function DashboardDesign({ conversationId, runId, onBuilt }: {
  conversationId: string; runId: string; onBuilt: (runId: string, reused: boolean) => void;
}) {
  const path = builderPath(conversationId, runId);
  const [state, setState] = useState<DesignState | null>(null);
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  // The final build: one submission at a time, blocked synchronously against double clicks.
  const [session, setSession] = useState<BuildSession | null>(null);
  const submitting = useRef(false);
  const sessions = useRef(0);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => {
    let active = true;
    readHandoff<DesignState>(path).then(result => { if (active) { setState(result); setError(""); } })
      .catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [path, attempt]);
  // The parent learns about the build ("Your dashboard is ready") only once the hand-off has finished,
  // so nothing outside the workflow claims success or shows a saved link early.
  const [finishedSession, setFinishedSession] = useState<number | null>(null);
  const handoffActive = !!session && session.id !== finishedSession;
  useEffect(() => {
    if (state?.status === "built" && state.dashboard_id && !handoffActive) onBuilt(runId, !!state.reused);
  }, [state, onBuilt, runId, handoffActive]);
  // A guided example goes straight to its reviewable brief.
  const guidedReady = !!state?.guided && state.status === "ready";
  useEffect(() => { if (guidedReady) setOpen(true); }, [guidedReady]);

  /** Final Build: one POST per explicit approval, sent at once, asking for the live checkpoints. Each checkpoint is shown
   *  as the server reports it; only a committed result marks the dashboard saved. A server that answers with JSON gets
   *  one pending operation. An uncertain outcome is checked once against the run, never posted again. */
  async function buildNow(reviewed: DesignState) {
    if (submitting.current || !reviewed.review_token) return;
    submitting.current = true;
    const id = ++sessions.current;
    const body = { version: reviewed.version, review_token: reviewed.review_token };
    const live = () => mounted.current && sessions.current === id;  // a newer attempt or an unmount makes this one stale
    const patch = (fn: (s: BuildSession) => Partial<BuildSession>) => { if (live()) setSession(s => s && s.id === id ? { ...s, ...fn(s) } : s); };
    const update = (phase: BuildSession["phase"]) => patch(s => ({
      phase,
      // a failure stops the checkpoint that was running; completed ones keep their evidence
      steps: phase.kind === "failed" ? Object.fromEntries(Object.entries(s.steps).map(([k, v]) => [k, v?.status === "running" ? { ...v, status: "failed" } : v])) : s.steps,
    }));
    setSession({ id, startedAt: performance.now(), brief: reviewed, phase: { kind: "saving" }, mode: "live", steps: {} });
    setError("");
    const built = (r: unknown): boolean =>
      !!r && typeof r === "object" && (r as DesignState).status === "built" && typeof (r as DesignState).dashboard_id === "string" && !!(r as DesignState).dashboard_id;
    const succeed = (result: DesignState, replayed = false) => {
      window.dispatchEvent(new Event("dashboards-changed"));
      if (!live()) return;
      setState(result);
      // Every approved run saves its own dashboard; a same-run retry returns that same one.
      update({ kind: "saved", dashboardId: result.dashboard_id!, replayed });
    };
    const reconcile = async (why: string) => {
      try {
        const latest = await readHandoff<DesignState>(path);
        if (built(latest)) { succeed(latest, true); return; }  // only the committed binding counts, never a record alone
        const unchanged = latest.status === "ready" && latest.review_token === reviewed.review_token;
        update(unchanged
          ? { kind: "failed", message: `${why} The save could not be confirmed. Your reviewed brief is unchanged.`, recovery: "retry", uncertain: true }
          : { kind: "failed", message: `${why} The save could not be confirmed, and the brief has changed since you approved it.`, recovery: "reload", uncertain: true });
      } catch {
        update({ kind: "failed", message: `${why} The save could not be confirmed, and the brief could not be checked.`, recovery: "reload", uncertain: true });
      }
    };
    try {
      let response: Response | null = null;
      try {
        response = await fetch(path + "/build", { method: "POST", body: JSON.stringify(body),
          headers: { "Content-Type": "application/json", Accept: "text/event-stream" } });
      } catch {
        response = null; // lost: the save may still have committed
      }
      if (!response) { await reconcile("The connection dropped."); return; }
      if (response.ok && response.body && (response.headers.get("content-type") ?? "").startsWith("text/event-stream")) {
        let terminal: "result" | "error" | "invalid" | null = null;
        let failure: BuildErrorEvent | null = null;
        let result: BuildResultEvent | null = null;
        try {
          await readEvents<BuildEvent>(response.body, (e) => {
            if (terminal) return;  // one terminal per attempt: anything after it is ignored
            if (e.type === "build_stage") patch(s => ({ steps: { ...s.steps, [e.phase]: { status: e.status, facts: e.facts } } }));
            else if (e.type === "build_result") { terminal = built(e.state) ? "result" : "invalid"; result = e; }
            else if (e.type === "build_error") { terminal = "error"; failure = e; }
          });
        } catch {
          if (!terminal) { await reconcile("The connection dropped during the build."); return; }
        }
        // A confirmed terminal stays the outcome even if the connection closed afterwards.
        const done = result as BuildResultEvent | null, failed = failure as BuildErrorEvent | null;
        if (terminal === "result" && done) succeed(done.state, done.replayed);
        else if (terminal === "error" && failed) {
          if (failed.kind === "retry") await reconcile(failed.message);  // an unexpected server error: the save may have committed
          else update({ kind: "failed", message: failed.message, recovery: failed.kind, uncertain: false });
        } else await reconcile(terminal === "invalid" ? "The server's answer could not be read." : "The connection closed before the build finished.");
        return;
      }
      // An older server answers with JSON: one operation, no milestones.
      patch(() => ({ mode: "single" }));
      if (response.ok) {
        const answer = await response.json().catch(() => null);
        if (built(answer)) succeed(answer as DesignState);
        else await reconcile("The server's answer could not be read.");
        return;
      }
      const data = await response.json().catch(() => ({}));
      const detail = typeof data.detail === "string" ? data.detail : "";
      if (response.status === 409) { update({ kind: "failed", message: detail || "The brief changed. Review it again.", recovery: "review", uncertain: false }); return; }
      if (response.status >= 500) { await reconcile(`The server reported an error (${response.status}).`); return; }
      update({ kind: "failed", message: detail || `The build was refused (${response.status}).`, recovery: "reload", uncertain: false });
    } finally {
      submitting.current = false;
    }
  }

  /** A design answer: the versioned POST starts at once and its result shows as soon as it returns. */
  const [answering, setAnswering] = useState<{ id: number; label: string } | null>(null);
  const answerIds = useRef(0);
  async function send(part: "answers", body: object, label: string) {
    if (answering) return;
    const id = ++answerIds.current;
    setAnswering({ id, label });
    setPending(true); setError("");
    try {
      const result = await readHandoff<DesignState>(path + "/" + part, "POST", body);
      if (mounted.current) { setState(result); setAnswering(a => (a && a.id === id ? null : a)); }
    } catch (e) {
      if (mounted.current) { setAnswering(null); setError(e instanceof Error ? e.message : "Could not save the dashboard design."); }
    } finally { if (mounted.current) setPending(false); }
  }
  const answerLabel = (value: BuildAnswer): string => {
    const q = state?.question;
    if (typeof value === "string") return q?.options.find(o => o.value === value)?.label ?? value;
    if (Array.isArray(value)) return value.map(v => q?.options.find(o => o.value === v)?.label ?? v).join(", ");
    return `${value.start} to ${value.end}`;
  };

  const refresh = () => setAttempt(previous => previous + 1);
  // A changed or unconfirmed brief must be loaded afresh: the old version and token are gone until it arrives.
  const reloadBrief = () => { setSession(null); setState(null); setOpen(true); refresh(); };
  if (session && state) return <section className="db-design" aria-label="Dashboard build">
    <BuildHandoff key={session.id} session={session} conversationId={conversationId}
      onRetry={() => void buildNow(session.brief)}
      onReviewUpdated={reloadBrief} onReload={reloadBrief}
      onFinished={() => setFinishedSession(session.id)} />
    {session.phase.kind === "saved" && session.brief.storage_mode === "memory" && <p className="db-caption">Demo storage · The saved dashboard is available until the server restarts.</p>}
  </section>;
  if (!state) return <section className="db-design" aria-label="Dashboard design">{error
    ? <><p role="alert">{error}</p><button type="button" className="btn-outline" onClick={refresh}>Reload design</button></>
    : <p role="status">Checking which workbook views can be built…</p>}</section>;
  if (state.status === "blocked") return <section className="db-design"><strong>{state.reuse_url ? "Report found for the clarified scope" : "Dashboard design needs review"}</strong><p>{state.reason}</p>
    {state.reuse_url && <a href={state.reuse_url} onClick={navigate} className="btn">{state.reuse_url.includes("?view=") ? "Open employee report" : "Inspect report record"}<Icon name="arrowRight" size={15}/></a>}</section>;
  if (state.status === "built" && state.dashboard_id) return <section className="db-design"><p className="db-label">{state.reused ? "Existing dashboard matches this brief" : "Saved dashboard"}</p>
    <a className="btn" href={dashboardUrl(state.dashboard_id)} onClick={navigate}>Open saved dashboard<Icon name="arrowRight" size={15}/></a></section>;
  const openLabel = state.status === "ready" ? "Review and build dashboard" : state.version > 0 ? "Continue dashboard design" : "Design dashboard";
  if (!open) return <section className="db-design"><p className="db-label">Next step</p>
    <h3>Build a dashboard for this request</h3><p>Confirm the business question, scope and workbook measures before opening the dashboard.</p>
    <button type="button" className="btn" onClick={() => setOpen(true)}>{openLabel}<Icon name="arrowRight" size={15}/></button>
  </section>;
  return <section className="db-design" aria-label="Dashboard design"><div className="db-design-head"><p className="db-label">Dashboard design</p>
    <button type="button" className="db-text-link" disabled={pending} onClick={() => setOpen(false)}>Close design</button></div>
    {state.status === "ready" ? <><h3>Review your dashboard brief</h3><Brief state={state} />
      {state.guided && <p className="db-caption">Nothing is saved until you choose Build dashboard. To change the product, countries or KPIs, choose New question.</p>}
      <button type="button" className="btn" disabled={pending} onClick={() => void buildNow(state)}>
        Build dashboard<Icon name="arrowRight" size={15}/></button></> :
      answering ? <div className="proc" aria-live="off">
        <p className="proc-status"><span className="spinner" aria-hidden="true" />Checking your answer against the workbook…</p>
        <p className="proc-fact">{answering.label}</p>
      </div> :
      state.question && <><DesignQuestion key={state.question.key} state={state} pending={pending}
        submit={value => void send("answers", { version: state.version, key: state.question!.key, value }, answerLabel(value))}/>
        {state.summary.length > 0 && <details className="db-progress"><summary>What’s in the brief so far</summary><Brief state={state}/></details>}</>}
    {state.status === "ready" && state.storage_mode === "memory" && <p className="db-caption">Demo storage · The saved dashboard will be available until the server restarts.</p>}
    {error && <div className="db-error" role="alert"><p>{error}</p><button type="button" className="db-text-link" onClick={refresh}>Reload saved design</button></div>}
  </section>;
}
