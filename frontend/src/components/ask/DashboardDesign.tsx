import { useEffect, useRef, useState, type FormEvent } from "react";
import { builderPath, dashboardUrl, type BuildAnswer, type DesignState } from "../../api/dashboardBuilder";
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
  useEffect(() => {
    if (state?.status === "built" && state.dashboard_id) onBuilt(runId, !!state.reused);
  }, [state, onBuilt, runId]);
  // A guided example goes straight to its reviewable brief.
  const guidedReady = !!state?.guided && state.status === "ready";
  useEffect(() => { if (guidedReady) setOpen(true); }, [guidedReady]);

  /** Final Build: send at once, show the reviewed facts while saving, then the hand-off. Clarification answers use send(). */
  async function buildNow(reviewed: DesignState) {
    if (submitting.current) return;
    submitting.current = true;
    const id = ++sessions.current;
    const startedAt = performance.now();
    const body = { version: reviewed.version, review_token: reviewed.review_token };
    const update = (phase: BuildSession["phase"]) => { if (mounted.current) setSession(s => s && s.id === id ? { ...s, phase } : s); };
    setSession({ id, startedAt, brief: reviewed, phase: { kind: "saving" } });
    setError("");
    const succeed = (result: DesignState) => {
      window.dispatchEvent(new Event("dashboards-changed"));
      if (!mounted.current) return;
      setState(result);
      if (result.reused && !result.guided) { setSession(null); return; }  // an existing dashboard: its link, no new-build sequence
      // A guided review that resolved to an identical saved dashboard is still this run's approved build: say so and open it.
      update({ kind: "ready", dashboardId: result.dashboard_id!, savedAfterMs: performance.now() - startedAt, exactReuse: !!result.exact_reuse });
    };
    try {
      let response: Response | null = null;
      try {
        response = await fetch(path + "/build", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      } catch {
        response = null; // lost: the save may still have committed
      }
      if (response?.ok) {
        const result = await response.json() as DesignState;
        if (result.status === "built" && result.dashboard_id) succeed(result);
        else update({ kind: "failed", message: result.reason || "The dashboard was not saved.", stale: true });
        return;
      }
      if (response) {
        const data = await response.json().catch(() => ({}));
        const message = typeof data.detail === "string" ? data.detail : `The server returned ${response.status}. Your brief is kept.`;
        update({ kind: "failed", message, stale: response.status === 409 });
        return;
      }
      // No answer: ask the run whether the save committed before saying anything.
      try {
        const latest = await readHandoff<DesignState>(path);
        if (latest.status === "built" && latest.dashboard_id) { succeed(latest); return; }
        update({ kind: "failed", message: "The connection dropped before the save was confirmed, and nothing was saved. Your brief is kept.", stale: false });
      } catch {
        update({ kind: "failed", message: "The connection dropped and the result could not be checked. Your brief is kept; try again.", stale: false });
      }
    } finally {
      submitting.current = false;
    }
  }

  async function send(part: "answers", body: object) {
    setPending(true); setError("");
    try { setState(await readHandoff<DesignState>(path + "/" + part, "POST", body)); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not save the dashboard design."); }
    finally { setPending(false); }
  }
  const refresh = () => setAttempt(previous => previous + 1);
  if (session && state) return <section className="db-design" aria-label="Dashboard build">
    <BuildHandoff key={session.id} session={session} conversationId={conversationId}
      onRetry={() => void buildNow(session.brief)}
      onReviewUpdated={() => { setSession(null); setOpen(true); refresh(); }}
      onStay={() => undefined} />
    {session.phase.kind === "ready" && session.brief.storage_mode === "memory" && <p className="db-caption">Demo storage · The saved dashboard is available until the server restarts.</p>}
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
      {state.matches_saved && <p className="db-caption">An identical dashboard was saved earlier. Building records your review and opens that saved version.</p>}
      {state.guided && <p className="db-caption">Nothing is saved until you choose Build dashboard. To change the product, countries or KPIs, choose New question.</p>}
      <button type="button" className="btn" disabled={pending} onClick={() => void buildNow(state)}>
        Build dashboard<Icon name="arrowRight" size={15}/></button></> :
      state.question && <><DesignQuestion key={state.question.key} state={state} pending={pending}
        submit={value => void send("answers", { version: state.version, key: state.question!.key, value })}/>
        {state.summary.length > 0 && <details className="db-progress"><summary>What’s in the brief so far</summary><Brief state={state}/></details>}</>}
    {state.status === "ready" && state.storage_mode === "memory" && <p className="db-caption">Demo storage · The saved dashboard will be available until the server restarts.</p>}
    {error && <div className="db-error" role="alert"><p>{error}</p><button type="button" className="db-text-link" onClick={refresh}>Reload saved design</button></div>}
  </section>;
}
