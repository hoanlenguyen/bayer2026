import { useCallback, useEffect, useRef, useState } from "react";
import { api, streamPost } from "../api/client";
import type { CatalogMeta, DecisionType, Health, PipelineEvent, Preset, StageEvent, StageId } from "../api/types";
import { FlowPanel, RUNNING_COPY } from "../components/ask/FlowPanel";
import { TriageStrip } from "../components/ask/TriageStrip";
import { VerdictCard } from "../components/ask/VerdictCard";
import { Icon } from "../components/Icon";
import { addUserMessage, applyEvent, beginQuestion, continueQuestion, findSavedAnswer, finishQuestion, getHistoryEntry, moveToTop, OPEN_ENTRY_EVENT, restartLatestQuestion, takePendingEntry, type QuestionEntry } from "../lib/history";

interface ChatMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
  kind?: "question" | "result" | "approval";
  suggestions?: string[];
}

type ConvState = "idle" | "clarifying" | "awaiting_approval";

/** Each matches a preset's prompt in the backend, so a click also sends that preset's certified measures. */
const STARTER_QUESTIONS = [
  "Please create a Power BI replacement for our legacy Tableau Xarelto commercial workbook.",
  "Please build a new report for market access coverage and reimbursement status by product.",
  "We need a monthly supply-risk dashboard by medicine and country.",
  "I need a new Kerendia management report for monthly performance in EMEA and North America.",
  "Can we have a new finance dashboard for net sales, gross-to-net and budget variance by product?",
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
  const [convState, setConvState] = useState<ConvState>("idle");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [stages, setStages] = useState<Partial<Record<StageId, StageEvent>>>({});
  const [decision, setDecision] = useState<DecisionType | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const nextId = useRef(1);
  const listRef = useRef<HTMLDivElement>(null);
  const entryId = useRef<string | null>(null); // the saved History entry for what is on screen
  const [savedAt, setSavedAt] = useState<string | null>(null); // set while showing a saved answer rather than a new one

  const showSaved = useCallback((entry: QuestionEntry) => {
    entryId.current = entry.id;
    setMessages(entry.result.messages.map((m) => ({ ...m, id: nextId.current++ })));
    setStages(entry.result.stages);
    setDecision(entry.result.decision);
    setError(entry.result.error);
    setConvId(entry.request.conversation_id);
    setConvState(entry.status === "needs_answer" ? "clarifying" : entry.status === "awaiting_approval" ? "awaiting_approval" : "idle");
    setSavedAt(entry.status === "needs_answer" ? null : entry.updated_at); // a follow-up question isn't an answer yet
  }, []);

  useEffect(() => {
    // A question picked from History. While an answer is streaming it waits, so the two don't mix.
    if (busy) return;
    const open = () => {
      const entry = takePendingEntry();
      if (entry) showSaved(entry);
    };
    open();
    window.addEventListener(OPEN_ENTRY_EVENT, open);
    return () => window.removeEventListener(OPEN_ENTRY_EVENT, open);
  }, [busy, showSaved]);

  useEffect(() => {
    document.title = "Analytics Manager";
    api.health().then(setHealth).catch(() => setOffline(true));
    api.presets().then(setPresets).catch(() => setOffline(true));
    api.catalog().then(setCatalog).catch(() => undefined);
  }, []);

  useEffect(() => {
    // Works in both layouts: the list scrolls on desktop, the page scrolls on narrow screens.
    listRef.current?.lastElementChild?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [messages, busy, stages]);

  const handleEvent = useCallback((e: PipelineEvent) => {
    if (entryId.current) applyEvent(entryId.current, e);
    switch (e.type) {
      case "conversation":
        setConvId(e.id);
        break;
      case "stage":
        setStages((s) => ({ ...s, [e.stage]: e }));
        if (e.stage === "decision" && e.status === "done") setDecision(e.data.decision);
        break;
      case "message":
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
    setError(null);
    setSavedAt(null);
    const entry = entryId.current;
    try {
      await streamPost(path, body, handleEvent);
      setOffline(false);
      if (entry) finishQuestion(entry);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
      setOffline(true);
      if (entry) finishQuestion(entry, message);
    } finally {
      setBusy(false);
    }
  }, [handleEvent]);

  const send = useCallback((text: string, presetId?: string, isSuggestion = false) => {
    // Asked before, even with a follow-up open: show the saved answer at once, with no call to the backend or the model.
    // A suggestion chip is always a reply to the follow-up, and a question can't be answered by itself.
    const saved = isSuggestion ? undefined : findSavedAnswer(text);
    if (saved && saved.id !== entryId.current) {
      moveToTop(saved.id);
      showSaved(saved);
      return;
    }
    if (convState === "clarifying" && entryId.current) {
      addUserMessage(entryId.current, text); // an answer to a follow-up question continues the same entry
    } else {
      if (saved) { // the question already on screen, asked again
        moveToTop(saved.id);
        showSaved(saved);
        return;
      }
      // Typed inside an open entry: it continues that entry. Only a fresh start makes a new one.
      if (entryId.current && getHistoryEntry(entryId.current)) continueQuestion(entryId.current, text);
      else entryId.current = beginQuestion(text, presetId ?? null);
    }
    if (convState !== "clarifying") {
      setStages({});
      setDecision(null);
    }
    setMessages((m) => [...m, { id: nextId.current++, role: "user", content: text }]);
    void run("/api/chat", { conversation_id: convId, message: text, preset_id: presetId ?? null });
  }, [convId, convState, run, showSaved]);

  /** Asks the latest question again, replacing its saved answer in the same entry. */
  const refresh = () => {
    const restarted = entryId.current ? restartLatestQuestion(entryId.current) : null;
    if (!restarted) return;
    setStages({}); setDecision(null); setConvState("idle");
    setMessages(restarted.messages.map((m) => ({ ...m, id: nextId.current++ })));
    void run("/api/chat", { conversation_id: convId, message: restarted.text, preset_id: restarted.presetId });
  };

  const approve = (approved: boolean) => {
    const approver = stages.approval?.data?.approver ?? "Report owner";
    const said = approved ? `Approved as ${approver}` : "Rejected";
    if (entryId.current) addUserMessage(entryId.current, said);
    setMessages((m) => [...m, { id: nextId.current++, role: "user", content: said }]);
    void run("/api/approve", { conversation_id: convId, approved, approver });
  };

  const newChat = () => {
    entryId.current = null;
    setSavedAt(null);
    setConvId(null); setConvState("idle"); setMessages([]); setStages({}); setDecision(null); setError(null);
  };

  const lastId = messages.length ? messages[messages.length - 1].id : -1;
  const runningStage = (Object.values(stages) as StageEvent[]).find((s) => s.status === "running")?.stage;
  const hasVerdict = stages.decision?.status === "done";

  const offlineBanner = offline && (
    <div className="banner" role="status">
      The backend is not reachable. Start it with <code>uvicorn app.main:app --reload --port 8000</code> in <code>backend/</code>, then reload.
    </div>
  );

  if (messages.length === 0) {
    return (
      <div className="ask-empty">
        <div className="ask-empty-above">
          {offlineBanner}
          <h1>What do you need to decide?</h1>
        </div>
        <Composer onSend={(t) => send(t)} disabled={busy} autoFocus placeholder="Describe the decision or the numbers you need, in your own words" />
        <div className="ask-empty-below">
          <div className="starter-chips" role="group" aria-label="Example questions">
            {STARTER_QUESTIONS.map((q) => (
              <button key={q} type="button" onClick={() => send(q, presets.find((p) => p.prompt === q)?.id)} disabled={busy}>{q}</button>
            ))}
          </div>
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
          {savedAt && <p className="saved-note">Saved answer from {new Date(savedAt).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}</p>}
          <div className="pane-actions">
            {savedAt && <button type="button" className="btn-outline" onClick={refresh}>Get a fresh answer</button>}
            <button type="button" className="btn-outline" onClick={newChat} disabled={busy}><Icon name="plus" />New question</button>
          </div>
        </div>
        {offlineBanner}
        <div className="messages" ref={listRef} aria-live="polite" aria-busy={busy}>
          {messages.map((m) => (
            <div key={m.id} className={`msg msg-${m.role}`}>
              <p><RichText text={m.content} /></p>
              {m.id === lastId && !busy && m.suggestions && m.suggestions.length > 0 && (
                <div className="chips">
                  {m.suggestions.map((s) => <button key={s} type="button" onClick={() => send(s, undefined, true)}>{s}</button>)}
                </div>
              )}
            </div>
          ))}
          {busy && !hasVerdict && (
            <p className="working"><span className="spinner" aria-hidden="true" />{runningStage ? RUNNING_COPY[runningStage] : "Reading your question"}</p>
          )}
          <TriageStrip stages={stages} />
          <VerdictCard stages={stages} catalog={catalog} busy={busy} onApprove={approve} />
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
