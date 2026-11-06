import { StageDetail } from "../components/ask/StageDetail";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, streamPost, getJSON, ensureSession, type DemoActor } from "../api/client";
import type {
  ActionProposal,
  CatalogMeta,
  DecisionType,
  Health,
  PipelineEvent,
  Preset,
  StageEvent,
  StageId,
} from "../api/types";
import { FlowPanel } from "../components/ask/FlowPanel";
import { ProposedActions } from "../components/ask/ProposedActions";
import { Workbench, decisionLabel } from "../components/ask/Workbench";

interface ChatMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
  kind?: "question" | "result" | "approval";
  suggestions?: string[];
}

type ConvState = "idle" | "clarifying" | "awaiting_approval";

/** Renders **bold** segments; everything else is plain text. */
function RichText({ text }: { text: string }) {
  const parts = text.split(/\*\*(.+?)\*\*/g);
  return (
    <>
      {parts.map((p, i) =>
        i % 2 ? <strong key={i}>{p}</strong> : <span key={i}>{p}</span>,
      )}
    </>
  );
}

function Composer({
  onSend,
  disabled,
  autoFocus,
  placeholder,
}: {
  onSend: (text: string) => void;
  disabled: boolean;
  autoFocus?: boolean;
  placeholder: string;
}) {
  const [text, setText] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 200) + "px";
  }, [text]);
  const submit = () => {
    const t = text.trim();
    if (!t || disabled) return;
    onSend(t);
    setText("");
  };
  return (
    <form
      className="composer"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <label htmlFor="ask-input" className="sr-only">
        Dashboard request
      </label>
      <textarea
        id="ask-input"
        ref={ref}
        rows={1}
        disabled={disabled}
        value={text}
        autoFocus={autoFocus}
        placeholder={placeholder}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            submit();
          }
        }}
      />
      <button
        type="submit"
        className="send"
        disabled={disabled || !text.trim()}
        aria-label="Send"
      >
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
          <path
            d="M4 12h13M12 5l7 7-7 7"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>
    </form>
  );
}

export function AskPage({ onActionsChanged }: { onActionsChanged: () => void }) {
  const [health, setHealth] = useState<Health | null>(null);
  const [offline, setOffline] = useState(false);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [catalog, setCatalog] = useState<CatalogMeta | null>(null);
  const [dept, setDept] = useState("All");

  const [question, setQuestion] = useState("");
  const [revision, setRevision] = useState(0);
  const [convId, setConvId] = useState<string | null>(null);
  const [convState, setConvState] = useState<ConvState>("idle");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [stages, setStages] = useState<Partial<Record<StageId, StageEvent>>>(
    {},
  );
  const [decision, setDecision] = useState<DecisionType | null>(null);
  const [proposals, setProposals] = useState<{ runKey: number; items: ActionProposal[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [actor, setActor] = useState<DemoActor | null>(null);
  const [history, setHistory] = useState<{_id: string; title: string; request_state: string}[]>([]);
  const [editText, setEditText] = useState("");
  const nextId = useRef(1);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api
      .health()
      .then(setHealth)
      .catch(() => setOffline(true));
    api
      .presets()
      .then(setPresets)
      .catch(() => setOffline(true));
    api
      .catalog()
      .then(setCatalog)
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    const update = (e: Event) => setActor((e as CustomEvent<DemoActor>).detail);
    ensureSession().then(s => setActor(s.actor)).catch(() => undefined);
    window.addEventListener("demo-actor", update);
    return () => window.removeEventListener("demo-actor", update);
  }, []);
  useEffect(() => {
    if (!busy) getJSON<typeof history>("/api/conversations").then(setHistory).catch(() => undefined);
  }, [busy, actor, convId]);
  const restore = async (id: string) => {
    try {
      const c = await getJSON<any>(`/api/conversations/${id}`);
      setConvId(id); setRevision(c.revision ?? 1); setConvState(c.state); setQuestion(c.intent?.question ?? c.title);
      setMessages(c.messages.map((m: ChatMessage) => ({ ...m, id: nextId.current++ })));
      const events: StageEvent[] = (c.runs.at(-1)?.events ?? []).filter((e: PipelineEvent) => e.type === "stage");
      const restored: Partial<Record<StageId, StageEvent>> = {};
      events.forEach(e => { restored[e.stage] = e; });
      setStages(restored); setDecision(restored.decision?.data?.decision ?? null);
      setProposals(restored.actions?.data ? {runKey: Date.now(), items: restored.actions.data.proposals} : null);
      setError(null);
    } catch (e) { setError(String(e)); }
  };
  const savedRequests = <label className="request-history">Saved requests
    <select aria-label="Saved requests" value={convId ?? ""} disabled={busy} onChange={e => { if (e.target.value) void restore(e.target.value); }}>
      <option value="">Select a request to resume</option>
      {history.map(c => <option key={c._id} value={c._id}>{c.title} · {c.request_state.replaceAll("_", " ")}</option>)}
    </select>
  </label>;

  useEffect(() => {
    listRef.current?.scrollTo({
      top: listRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages, busy]);

  const handleEvent = useCallback((e: PipelineEvent) => {
    switch (e.type) {
      case "conversation":
        setConvId(e.id);
        if (e.revision !== undefined) setRevision(e.revision);
        break;
      case "stage":
        setStages((s) => ({ ...s, [e.stage]: e }));
        if (e.stage === "decision" && e.status === "done")
          setDecision(e.data.decision);
        if (e.stage === "actions" && e.status === "done")
          setProposals({ runKey: Date.now(), items: e.data.proposals });
        break;
      case "message":
        setMessages((m) => [
          ...m,
          {
            id: nextId.current++,
            role: "assistant",
            content: e.content,
            kind: e.kind,
            suggestions: e.suggestions,
          },
        ]);
        break;
      case "done":
        setConvState(e.state);
        break;
      case "error":
        setError(e.message);
        break;
    }
  }, []);

  const run = useCallback(
    async (path: string, body: unknown) => {
      setBusy(true);
      setError(null);
      try {
        await streamPost(path, body, handleEvent);
        setOffline(false);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
        setOffline(err instanceof TypeError);
      } finally {
        setBusy(false);
      }
    },
    [handleEvent],
  );

  const send = useCallback(
    (text: string, presetId?: string) => {
      if (convState !== "clarifying") {
        setQuestion(text);
        setStages({});
        setDecision(null);
        setProposals(null);
      }
      setMessages((m) => [
        ...m,
        { id: nextId.current++, role: "user", content: text },
      ]);
      void run("/api/chat", {
        conversation_id: convId,
        expected_revision: convId ? revision : null,
        submission_id: crypto.randomUUID(),
        message: text,
        preset_id: presetId ?? null,
      });
    },
    [convId, convState, run, revision],
  );

  const approve = (approved: boolean) => {
    const approver = actor?.name ?? "Reviewer";
    setMessages((m) => [
      ...m,
      {
        id: nextId.current++,
        role: "user",
        content: approved ? `Approved as ${approver}` : "Rejected",
      },
    ]);
    void run("/api/approve", { conversation_id: convId, approved, spec_hash: stages.approval?.data?.spec_hash });
  };

  const newChat = () => {
    setQuestion("");
    setConvId(null);
    setRevision(0);
    setConvState("idle");
    setMessages([]);
    setStages({});
    setDecision(null);
    setError(null);
    setProposals(null);
  };

  const departments = useMemo(
    () => ["All", ...Array.from(new Set(presets.map((p) => p.department)))],
    [presets],
  );
  const shownPresets = useMemo(
    () => presets.filter((p) => dept === "All" || p.department === dept),
    [presets, dept],
  );
  const requestPresets = shownPresets.filter((p) => !p.scenario);
  const scenarioPresets = shownPresets.filter((p) => p.scenario);
  const lastId = messages.length ? messages[messages.length - 1].id : -1;

  const offlineBanner = offline && (
    <div className="banner" role="status">
      The backend is not reachable. Start it with{" "}
      <code>uvicorn app.main:app --reload --port 8000</code> in{" "}
      <code>backend/</code>, then reload.
    </div>
  );

  if (messages.length === 0) {
    return (
      <div className="ask-empty">
        {offlineBanner}
        {savedRequests}
        {error && <p role="alert">{error}</p>}
        <div className="entry-heading">
          <span className="folio">ANALYTICS WORKBENCH / DASHBOARD REQUEST</span>
          <span className="folio">01</span>
        </div>
        <div className="hello">
          <h1>
            What dashboard
            <br />
            does your team need?
          </h1>
          <p>
            Describe what you need to track. We will check existing dashboards and prepare any necessary changes.
          </p>
        </div>
        <div className="entry-label">
          <span className="folio">YOUR REQUEST</span>
          <span>Tell us the purpose, audience and scope</span>
        </div>
        <Composer
          onSend={(t) => send(t)}
          disabled={busy}
          autoFocus
          placeholder="Build a dashboard of Eylea net sales and digital engagement in Japan, with monthly trends."
        />
        <div className="preset-heading">
          <h2>Or start with a dashboard request</h2>
          <span className="folio">DEPARTMENT INDEX</span>
        </div>
        <div
          className="dept-filter"
          role="group"
          aria-label="Filter suggestions by department"
        >
          {departments.map((d) => (
            <button
              key={d}
              type="button"
              aria-pressed={dept === d}
              onClick={() => setDept(d)}
            >
              {d}
            </button>
          ))}
        </div>
        {requestPresets.length > 0 && (
          <div className="preset-subheading">
            <h3>Business requests from Bayer's data pack</h3>
            <span className="folio">BUSINESS_REQUESTS</span>
          </div>
        )}
        <div className="preset-grid">
          {requestPresets.map((p, index) => (
            <button
              key={p.id}
              type="button"
              className="preset"
              onClick={() => send(p.prompt, p.id)}
              disabled={busy}
            >
              <span className="preset-number folio">
                {String(index + 1).padStart(2, "0")}
              </span>
              <span className="preset-dept">
                {p.department}
                {p.requests ? ` · asked ${p.requests}×` : ""}
              </span>
              <span className="preset-title">{p.title}</span>
              <span className="preset-prompt">{p.prompt}</span>
            </button>
          ))}
        </div>
        {scenarioPresets.length > 0 && (
          <div className="preset-subheading">
            <h3>Demo scenarios grounded in workbook records</h3>
            <span className="folio">SCENARIOS</span>
          </div>
        )}
        <div className="preset-grid">
          {scenarioPresets.map((p, index) => (
            <button
              key={p.id}
              type="button"
              className="preset"
              onClick={() => send(p.prompt, p.id)}
              disabled={busy}
            >
              <span className="preset-number folio">
                {String(requestPresets.length + index + 1).padStart(2, "0")}
              </span>
              <span className="preset-dept">
                {p.department} · expect {p.scenario?.replace("_", " ")}
              </span>
              <span className="preset-title">{p.title}</span>
              <span className="preset-prompt">{p.prompt}</span>
            </button>
          ))}
        </div>
        <p className="fineprint">
          Synthetic Bayer Pharmaceuticals × Since AI 2026 data pack: 360
          reports, 75 semantic models, 56 KPIs. No patient or HCP data. The AI
          sees catalog metadata only.
        </p>
      </div>
    );
  }

  return (
    <main className="investigation">
      <header className="question-strip">
        <span className="folio">DASHBOARD REQUEST</span>
        <h1>{question || messages[0]?.content}</h1>
        <button
          type="button"
          className="btn-ghost"
          disabled={busy}
          onClick={newChat}
        >
          New request ↗
        </button>
      </header>
      {savedRequests}
      <section className="request-brief" aria-label="Request brief">
        <div><span className="folio">CURRENT BRIEF</span><h2>{stages.intent?.data?.decision || "Clarifying the dashboard requirements"}</h2></div>
        <p>KPIs: {(stages.intent?.data?.measures ?? []).map((id: string) => catalog?.measures[id]?.name ?? id).join(", ") || "Not yet specified"}</p>
        <p>Scope: {Object.entries(stages.intent?.data?.filters ?? {}).map(([k,v]) => `${k}: ${(v as string[]).join(", ")}`).join(" · ") || (stages.intent?.data?.scope_global ? "All products" : "To confirm")}{stages.intent?.data?.scope_global ? " · All markets" : ""}</p>
        <p>Period: January–October 2026 · monthly synthetic workbook data. Other periods require a revised binding.</p>
        <p>Requester: {stages.intent?.data?.requester_id ?? actor?.id} · Version {stages.intent?.data?.request_revision ?? 1} · {(stages.intent?.data?.dimensions ?? []).join(", ") || "No breakdown selected"}</p>
        {!!stages.intent?.data?.unmatched_terms?.length && <p className="bad-text">Unresolved: {stages.intent.data.unmatched_terms.join(", ")}</p>}
        <details><summary onClick={() => { if (!editText) setEditText(question); }}>Edit requirements and reassess</summary>
          <label>Describe the full revised request<textarea aria-label="Revised dashboard request" value={editText} onChange={e => setEditText(e.target.value)} /></label>
          <button className="btn" type="button" disabled={busy || !editText.trim()} onClick={() => { send(editText); setEditText(""); }}>Reassess this request</button>
          <p className="muted small">A new assessment supersedes the previous pending specification and requires a fresh review.</p>
        </details>
      </section>
      <div className="processing-strip" aria-label="Processing status" aria-live="polite">
        {Object.values(stages).filter(e => ["intent", "discovery", "governance", "evidence", "spec", "render"].includes(e.stage)).map(e => <span key={e.stage} className={`process-${e.status}`}>{e.status === "running" ? "◌" : e.status === "waiting" ? "!" : "✓"} {e.title}{e.data?.agent ? ` · ${e.data.agent.mode === "llm" ? "Live model" : "Offline rules"}` : ""}</span>)}
      </div>
      {stages.render?.status === "done" && <section className="request-brief"><h2>{stages.render.summary}</h2><StageDetail stage="render" data={stages.render.data} catalog={catalog} /></section>}
      <Workbench
        key={question}
        stages={stages}
        decision={decision}
        catalog={catalog}
      >
        <section className="chat" aria-label="Conversation">
          <div className="conversation-label">
            <h2>Request notes</h2>
            <span className="folio">
              {busy
                ? "PROCESSING"
                : convState === "clarifying"
                  ? "YOUR INPUT NEEDED"
                  : "LIVE RECORD"}
            </span>
          </div>
          {offlineBanner}
          <div className="messages" ref={listRef} aria-live="polite">
            {messages.map((m) => (
              <div key={m.id} className={`msg msg-${m.role}`}>
                <span className="note-author">
                  {m.role === "user" ? "YOU" : "WORKBENCH"}
                </span>
                <div className="msg-body">
                  <p>
                    <RichText text={m.content} />
                  </p>
                  {m.id === lastId &&
                    !busy &&
                    m.suggestions &&
                    m.suggestions.length > 0 && (
                      <div className="chips">
                        {m.suggestions.map((s) => (
                          <button key={s} type="button" onClick={() => send(s)}>
                            {s}
                          </button>
                        ))}
                      </div>
                    )}
                </div>
              </div>
            ))}
            {proposals && proposals.items.length > 0 && !busy && (
              <details className="follow-up-drawer"><summary>{proposals.items.length} proposed follow-up actions</summary><ProposedActions
                key={proposals.runKey}
                proposals={proposals.items}
                conversationId={convId}
                onAdded={onActionsChanged}
              /></details>
            )}
            {busy && (
              <div className="msg msg-assistant">
                <span className="note-author">LIVE</span>
                <div className="msg-body">
                  <p className="muted">Working on it…</p>
                </div>
              </div>
            )}
            {error && <p className="bad-text small">{error}</p>}
          </div>
          <div className="chat-composer">
            <Composer
              onSend={(t) => send(t)}
              disabled={busy}
              placeholder={
                convState === "awaiting_approval"
                  ? "Add a clarification to reassess the request"
                  : convState === "clarifying"
                    ? "Answer the question, or pick a suggestion"
                    : "Describe a revised dashboard request"
              }
            />
          </div>
        </section>
      </Workbench>
      <div className="decision-dock" aria-label="Decision and next action">
        <span className="folio">DECISION PATH</span>
        <div className="dock-outcome">
          <strong>{decisionLabel(decision)}</strong>
          <span>
            {stages.decision?.data?.reason ??
              (busy
                ? "Checking the catalog and your requirements…"
                : "Clarify the dashboard requirements to continue.")}
          </span>
        </div>
        {convState === "awaiting_approval" ? (
          <div className="approve-row">
            {!actor?.can_review && <span className="small">Switch to the demo reviewer to review this plan.</span>}
            <button
              type="button"
              className="btn-ghost"
              disabled={busy || !actor?.can_review}
              onClick={() => approve(false)}
              title="Reviewer permission is checked on the server"
            >
              Reject
            </button>
            <button
              type="button"
              className="btn"
              disabled={busy || !actor?.can_review}
              onClick={() => approve(true)}
            >
              Approve plan →
            </button>
          </div>
        ) : stages.deliver?.data?.asset ? (
          <button
            type="button"
            className="btn"
            onClick={() =>
              window.dispatchEvent(
                new CustomEvent("open-entity", {
                  detail: stages.deliver!.data.asset.id,
                }),
              )
            }
          >
            Inspect existing report in the asset index ↗
          </button>
        ) : (
          <span className="dock-status">
            {busy
              ? "In progress"
              : stages.register?.status === "done"
                ? "Draft · validation pending"
                : stages.approval?.status === "rejected"
                  ? "Proposal rejected"
                  : convState === "clarifying"
                    ? "Input required"
                    : "Review the investigation"}
          </span>
        )}
      </div>
      <details className="audit-drawer">
        <summary>
          Processing record{" "}
          <span>All stages, agent traces, scores and generated files</span>
        </summary>
        <FlowPanel
          stages={stages}
          decision={decision}
          health={health}
          catalog={catalog}
        />
      </details>
    </main>
  );
}
