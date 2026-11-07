import { useCallback, useEffect, useRef, useState } from "react";
import { api, streamPost } from "../api/client";
import type { CatalogMeta, DecisionType, Health, PipelineEvent, Preset, StageEvent, StageId } from "../api/types";
import { FlowPanel, RUNNING_COPY } from "../components/ask/FlowPanel";
import { TriageStrip } from "../components/ask/TriageStrip";
import { VerdictCard } from "../components/ask/VerdictCard";
import { Icon } from "../components/Icon";
import { conversationsChanged, CURRENT_REMOVED_EVENT, getCurrentConversation, setAnswerInProgress, OPEN_CONVERSATION_EVENT, setCurrentConversation, stagesOf, takePendingConversation } from "../lib/conversations";

interface ChatMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
  kind?: "question" | "result" | "retry";
  suggestions?: string[];
}

type ConvState = "idle" | "clarifying" | "awaiting_approval"; // awaiting_approval only exists in older saved conversations

/** Each matches a preset's prompt in the backend, so a click also sends that preset's certified measures. */
const STARTER_QUESTIONS = [
  "Please create a Power BI replacement for our legacy Tableau Xarelto commercial workbook.",
  "Show monthly inventory coverage and OTIF for Lynkuet in Spain.",
  "How are Eylea net sales and digital engagement developing in Japan?",
  "We need a monthly supply-risk dashboard by medicine and country.",
  "Can we have a new finance dashboard for net sales, gross-to-net and budget variance by product?",
];

const MORE_QUESTIONS = [
  "Please build a new report for market access coverage and reimbursement status by product.",
  "I need a new Kerendia management report for monthly performance in EMEA and North America.",
];

/** Renders **bold** segments; everything else is plain text. */
function RichText({ text }: { text: string }) {
  const parts = text.split(/\*\*(.+?)\*\*/g);
  return <>{parts.map((p, i) => (i % 2 ? <strong key={i}>{p}</strong> : <span key={i}>{p}</span>))}</>;
}

function Composer({ onSend, disabled, autoFocus, placeholder }: {
  onSend: (text: string) => void; disabled: boolean; autoFocus?: boolean; placeholder: string;
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
    <form className="composer" onSubmit={(e) => { e.preventDefault(); submit(); }}>
      <label htmlFor="ask-input" className="sr-only">Your question</label>
      <textarea
        id="ask-input"
        ref={ref}
        rows={1}
        value={text}
        autoFocus={autoFocus}
        placeholder={placeholder}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } }}
      />
      <button type="submit" className="send" disabled={disabled || !text.trim()} aria-label="Send">
        <Icon name="arrowUp" />
      </button>
    </form>
  );
}

export function AskPage() {
  const [health, setHealth] = useState<Health | null>(null);
  const [offline, setOffline] = useState(false);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [catalog, setCatalog] = useState<CatalogMeta | null>(null);

  const [convId, setConvId] = useState<string | null>(null);
  const [restoredRunId, setRestoredRunId] = useState<string | null>(null);
  const [convState, setConvState] = useState<ConvState>("idle");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [stages, setStages] = useState<Partial<Record<StageId, StageEvent>>>({});
  const [decision, setDecision] = useState<DecisionType | null>(null);
  const [busy, setBusy] = useState(false);
  const [checking, setChecking] = useState(false); // sent, and the backend has not said yet if it accepts the message
  const [error, setError] = useState<string | null>(null);
  const nextId = useRef(1);
  const listRef = useRef<HTMLDivElement>(null);
  const restoreAttempt = useRef(0);
  const [restoring, setRestoring] = useState(() => getCurrentConversation() !== null);

  /** Brings a saved conversation back as it was. Sending next continues it, with its context, in the backend. */
  const restore = useCallback(async (id: string) => {
    const attempt = ++restoreAttempt.current;
    setRestoring(true);
    setError(null);
    try {
      const conv = await api.conversation(id);
      if (attempt !== restoreAttempt.current) return; // another conversation was picked meanwhile
      const restored = stagesOf(conv);
      setMessages(conv.messages.map((m) => ({ id: nextId.current++, role: m.role, content: m.content, kind: m.kind, suggestions: m.suggestions })));
      setStages(restored);
      setRestoredRunId(conv.runs.at(-1)?.id ?? null);
      setDecision(restored.decision?.data?.decision ?? null);
      setConvId(conv._id);
      setConvState(conv.state === "clarifying" ? "clarifying" : "idle");
      setCurrentConversation(conv._id);
      setOffline(false);
    } catch (err) {
      if ((err as { status?: number }).status === 404) { // gone, such as after a restart without MongoDB
        if (getCurrentConversation() === id) setCurrentConversation(null);
        conversationsChanged();
      } else {
        setOffline(true);
      }
    } finally {
      setRestoring(false);
    }
  }, []);

  useEffect(() => {
    // A conversation picked from History. While an answer is streaming it waits, so the two don't mix.
    if (busy) return;
    const open = () => {
      const id = takePendingConversation();
      if (id) void restore(id);
    };
    open();
    window.addEventListener(OPEN_CONVERSATION_EVENT, open);
    return () => window.removeEventListener(OPEN_CONVERSATION_EVENT, open);
  }, [busy, restore]);

  useEffect(() => {
    // Coming back: reopen the conversation that was open, unless one was just picked from the list.
    const id = getCurrentConversation();
    if (id) void restore(id);
  }, [restore]);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setOffline(true));
    api.presets().then(setPresets).catch(() => setOffline(true));
    api.catalog().then(setCatalog).catch(() => undefined);
  }, []);

  useEffect(() => {
    // Works in both layouts: the list scrolls on desktop, the page scrolls on narrow screens.
    listRef.current?.lastElementChild?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [messages, busy, stages]);

  const handleEvent = useCallback((e: PipelineEvent) => {
    switch (e.type) {
      case "conversation":
        setConvId(e.id);
        setCurrentConversation(e.id);
        break;
      case "user_message":
        conversationsChanged(); // saved by now, so it can appear in the list
        break;
      case "stage":
        setChecking(false);
        // The first step starting means the message was accepted as a new question: only now does the last answer go.
        if (e.stage === "intent" && e.status === "running") {
          setRestoredRunId(null);
          setStages({ intent: e });
          setDecision(null);
          break;
        }
        setStages((s) => ({ ...s, [e.stage]: e }));
        if (e.stage === "decision" && e.status === "done") setDecision(e.data.decision);
        break;
      case "message":
        setChecking(false);
        setMessages((m) => [...m, { id: nextId.current++, role: "assistant", content: e.content, kind: e.kind, suggestions: e.suggestions }]);
        break;
      case "done":
        setConvState(e.state);
        break;
      case "error":
        setError(e.message);
        break;
    }
  }, []);

  const run = useCallback(async (path: string, body: unknown) => {
    setBusy(true);
    setAnswerInProgress(true);
    setError(null);
    try {
      await streamPost(path, body, handleEvent);
      setOffline(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setOffline(true);
    } finally {
      setBusy(false);
      setChecking(false);
      setAnswerInProgress(false);
      conversationsChanged();
    }
  }, [handleEvent]);

  const send = useCallback((text: string, presetId?: string) => {
    setChecking(true);
    setMessages((m) => [...m, { id: nextId.current++, role: "user", content: text }]);
    void run("/api/chat", { conversation_id: convId, message: text, preset_id: presetId ?? null });
  }, [convId, run]);

  const newChat = () => {
    setCurrentConversation(null);
    setRestoredRunId(null);
    setConvId(null); setConvState("idle"); setMessages([]); setStages({}); setDecision(null); setError(null);
  };

  useEffect(() => {
    // The chat on screen was deleted from the list.
    const cleared = () => {
      restoreAttempt.current++;
      setRestoring(false);
      setRestoredRunId(null);
      setConvId(null); setConvState("idle"); setMessages([]); setStages({}); setDecision(null); setError(null);
    };
    window.addEventListener(CURRENT_REMOVED_EVENT, cleared);
    return () => window.removeEventListener(CURRENT_REMOVED_EVENT, cleared);
  }, []);

  const lastId = messages.length ? messages[messages.length - 1].id : -1;
  const runningStage = (Object.values(stages) as StageEvent[]).find((s) => s.status === "running")?.stage;
  const hasVerdict = stages.decision?.status === "done";

  // Messages rejected after an answer come below its verdict card, which stays because nothing new has started.
  let tailStart = messages.length;
  if (hasVerdict) {
    if (checking && messages[tailStart - 1]?.role === "user") tailStart--;
    while (tailStart >= 2 && messages[tailStart - 1].kind === "retry" && messages[tailStart - 2].role === "user") tailStart -= 2;
  }
  const renderMessage = (m: ChatMessage) => (
    <div key={m.id} className={`msg msg-${m.role}`}>
      <p><RichText text={m.content} /></p>
      {m.id === lastId && !busy && m.suggestions && m.suggestions.length > 0 && (
        <div className="chips">
          {m.suggestions.map((s) => <button key={s} type="button" onClick={() => send(s, presets.find((p) => p.prompt === s)?.id)}>{s}</button>)}
        </div>
      )}
    </div>
  );
  const working = busy && (!hasVerdict || checking) && (
    <p className="working"><span className="spinner" aria-hidden="true" />{runningStage ? RUNNING_COPY[runningStage] : "Reading your question"}</p>
  );
  const runId = stages.decision?.data?.run_id ?? restoredRunId;
  const handoff = convId && runId && !busy && !restoring ? { conversationId: convId, runId } : undefined;
  const answerCards = <><TriageStrip stages={stages} /><VerdictCard stages={stages} catalog={catalog} busy={busy} handoff={handoff} /></>;

  const offlineBanner = offline && (
    <div className="banner" role="status">
      The backend is not reachable. Start it with <code>uvicorn app.main:app --reload --port 8000</code> in <code>backend/</code>, then reload.
    </div>
  );

  if (messages.length === 0 && restoring) {
    return <div className="ask-empty"><p className="working"><span className="spinner" aria-hidden="true" />Opening your conversation</p></div>;
  }

  if (messages.length === 0) {
    const starter = (q: string) => <button key={q} type="button" onClick={() => send(q, presets.find((p) => p.prompt === q)?.id)} disabled={busy || !presets.length}>{q}</button>;
    return (
      <div className="ask-empty">
        <div className="ask-empty-above">
          {offlineBanner}
          <h1>What do you need to decide?</h1>
        </div>
        <Composer onSend={(t) => send(t)} disabled={busy} autoFocus placeholder="Describe the decision or the numbers you need, in your own words" />
        <div className="ask-empty-below">
          <div className="starter-chips" role="group" aria-label="Example questions">
            {STARTER_QUESTIONS.map(starter)}
          </div>
          <details className="rh-examples"><summary>More example questions</summary>
            <div className="starter-chips">{MORE_QUESTIONS.map(starter)}</div>
          </details>
          <p className="fineprint">The AI sees catalog metadata only, never raw production data.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="ask-layout">
      <section className="chat" aria-label="Conversation">
        <div className="pane-head">
          <h1>Ask</h1>
          <button type="button" className="btn-outline" onClick={newChat} disabled={busy}><Icon name="plus" />New question</button>
        </div>
        {offlineBanner}
        <div className="messages" ref={listRef} aria-live="polite" aria-busy={busy}>
          {messages.slice(0, tailStart).map(renderMessage)}
          {tailStart < messages.length
            ? <>{answerCards}{messages.slice(tailStart).map(renderMessage)}{working}</>
            : <>{working}{answerCards}</>}
          {error && <p className="text-bad small">{error}</p>}
        </div>
        <div className="chat-composer">
          <Composer
            onSend={(t) => send(t)}
            disabled={busy}
            placeholder={convState === "clarifying" ? "Answer the question, or pick a suggestion" : "Ask another question"}
          />
        </div>
      </section>
      <FlowPanel stages={stages} decision={decision} health={health} catalog={catalog} />
    </div>
  );
}
