import { useEffect, useRef, useState, type FormEvent } from "react";
import { builderPath, dashboardUrl, type BuildAnswer, type DesignState } from "../../api/dashboardBuilder";
import { readHandoff } from "../../api/handoff";
import { navigate } from "../../lib/navigation";
import { Icon } from "../Icon";
import "./dashboard-design.css";

function Brief({ state }: { state: DesignState }) {
  return <div className="db-brief"><p className="db-label">Interpreted brief</p>
    <ul>{state.summary.map((line, i) => <li key={i}>{line}</li>)}</ul></div>;
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
  useEffect(() => {
    let active = true;
    readHandoff<DesignState>(path).then(result => { if (active) { setState(result); setError(""); } })
      .catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [path, attempt]);
  useEffect(() => {
    if (state?.status === "built" && state.dashboard_id) onBuilt(runId, !!state.reused);
  }, [state, onBuilt, runId]);

  async function send(part: "answers" | "build", body: object) {
    const previousLocation = window.location.href;
    setPending(true); setError("");
    try {
      const result = await readHandoff<DesignState>(path + "/" + part, "POST", body);
      setState(result);
      if (part === "build" && result.status === "built" && result.dashboard_id) {
        window.dispatchEvent(new Event("dashboards-changed"));
        if (previousLocation !== window.location.href) return;
        history.pushState(null, "", dashboardUrl(result.dashboard_id));
        window.scrollTo(0, 0); window.dispatchEvent(new PopStateEvent("popstate"));
      }
    } catch (e) { setError(e instanceof Error ? e.message : "Could not save the dashboard design."); }
    finally { setPending(false); }
  }
  const refresh = () => setAttempt(previous => previous + 1);
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
      <button type="button" className="btn" disabled={pending} onClick={() => void send("build", { version: state.version, review_token: state.review_token })}>
        {pending ? "Building…" : "Build dashboard"}<Icon name="arrowRight" size={15}/></button></> :
      state.question && <><DesignQuestion key={state.question.key} state={state} pending={pending}
        submit={value => void send("answers", { version: state.version, key: state.question!.key, value })}/>
        {state.summary.length > 0 && <details className="db-progress"><summary>What’s in the brief so far</summary><Brief state={state}/></details>}</>}
    {state.status === "ready" && state.storage_mode === "memory" && <p className="db-caption">Demo storage · The saved dashboard will be available until the server restarts.</p>}
    {error && <div className="db-error" role="alert"><p>{error}</p><button type="button" className="db-text-link" onClick={refresh}>Reload saved design</button></div>}
  </section>;
}
