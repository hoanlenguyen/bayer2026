import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, streamPost } from "../api/client";
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
        Your question
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
    listRef.current?.scrollTo({
      top: listRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages, busy]);

  const handleEvent = useCallback((e: PipelineEvent) => {
    switch (e.type) {
      case "conversation":
        setConvId(e.id);
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
        setOffline(true);
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
        message: text,
        preset_id: presetId ?? null,
      });
    },
    [convId, convState, run],
  );

  const approve = (approved: boolean) => {
    const approver = stages.approval?.data?.approver ?? "Report owner";
    setMessages((m) => [
      ...m,
      {
        id: nextId.current++,
        role: "user",
        content: approved ? `Approved as ${approver}` : "Rejected",
      },
    ]);
    void run("/api/approve", { conversation_id: convId, approved, approver });
  };

  const newChat = () => {
    setQuestion("");
    setConvId(null);
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
        <div className="entry-heading">
          <span className="folio">ANALYTICS WORKBENCH / NEW INVESTIGATION</span>
          <span className="folio">01</span>
        </div>
        <div className="hello">
          <h1>
            Good decisions start
            <br />
            with the right question.
          </h1>
          <p>
            Find the analysis you need. Reuse what works. Build only what is
            missing.
          </p>
        </div>
        <div className="entry-label">
          <span className="folio">YOUR QUESTION</span>
          <span>Describe the decision you need to make</span>
        </div>
        <Composer
          onSend={(t) => send(t)}
          disabled={busy}
          autoFocus
          placeholder="For example: Nubeqa net sales and market access by country"
        />
        <div className="preset-heading">
          <h2>Or start with a familiar decision</h2>
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
            <h3>Estate scenarios, built from real assets to show each outcome</h3>
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
        <span className="folio">INVESTIGATION</span>
        <h1>{question || messages[0]?.content}</h1>
        <button
          type="button"
          className="btn-ghost"
          disabled={busy}
          onClick={newChat}
        >
          New question ↗
        </button>
      </header>
      <Workbench
        key={question}
        stages={stages}
        decision={decision}
        catalog={catalog}
      >
        <section className="chat" aria-label="Conversation">
          <div className="conversation-label">
            <h2>Investigation notes</h2>
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
                  {m.role === "user" ? "YOU" : "ANALYSIS"}
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
              <ProposedActions
                key={proposals.runKey}
                proposals={proposals.items}
                conversationId={convId}
                onAdded={onActionsChanged}
              />
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
              disabled={busy || convState === "awaiting_approval"}
              placeholder={
                convState === "awaiting_approval"
                  ? "Review the specification, then approve or reject below"
                  : convState === "clarifying"
                    ? "Answer the question, or pick a suggestion"
                    : "Ask another question"
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
                : "Clarify your question to continue.")}
          </span>
        </div>
        {convState === "awaiting_approval" ? (
          <div className="approve-row">
            <button
              type="button"
              className="btn-ghost"
              disabled={busy}
              onClick={() => approve(false)}
            >
              Reject
            </button>
            <button
              type="button"
              className="btn"
              disabled={busy}
              onClick={() => approve(true)}
            >
              Approve as {stages.approval?.data?.approver ?? "owner"} →
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
                ? "Registered in catalog"
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
