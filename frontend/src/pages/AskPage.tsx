import { useCallback, useEffect, useRef, useState } from "react";
import { api, streamPost } from "../api/client";
import type { CatalogMeta, DecisionType, GuidedChoice, GuidedExample, Health, PipelineEvent, Preset, StageEvent, StageId } from "../api/types";
import { FlowPanel, RUNNING_COPY } from "../components/ask/FlowPanel";
import { TriageStrip } from "../components/ask/TriageStrip";
import { VerdictCard } from "../components/ask/VerdictCard";
import { Icon } from "../components/Icon";
import { cancelPendingConversation, CURRENT_REMOVED_EVENT, forgetConversation, getCurrentConversation, inSession, OPEN_CONVERSATION_EVENT, recordConversation, setAnswerInProgress, setCurrentConversation, stagesOf, takePendingConversation } from "../lib/conversations";

interface ChatMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
  kind?: "question" | "result" | "retry";
  suggestions?: string[];
  choices?: GuidedChoice[];
}

type ConvState = "idle" | "clarifying" | "awaiting_approval"; // awaiting_approval only exists in older saved conversations

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
  /** Grow with the text, up to 200px. While the page is hidden (e.g. under /introduction) there is nothing to measure:
   *  scrollHeight is 0 and would fix the box at 0px, so leave the height to rows={1} until it shows. */
  const fit = () => {
    const el = ref.current;
    if (!el) return;
    if (!el.getClientRects().length) { el.style.height = ""; return; }
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 200) + "px";
  };
  useEffect(fit, [text]);
  useEffect(() => {
    // Measure again when the box appears or its width changes (a page switch, a wider window).
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    let width = -1;
    const observer = new ResizeObserver(([entry]) => {
      const w = entry!.contentRect.width;
      if (w !== width) { width = w; fit(); } // height changes come from fit() itself; ignore them
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
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
  const [examples, setExamples] = useState<GuidedExample[] | null>(null);

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
  const streamId = useRef<string | null>(null);
  const [restoring, setRestoring] = useState(() => getCurrentConversation() !== null);

  /** Brings a conversation of this tab back as it was. Sending next continues it, with its context, in the backend.
   *  Only the latest selection may change the screen: an older answer, error or loading end is ignored. */
  const restore = useCallback(async (id: string) => {
    if (!inSession(id)) return;
    const attempt = ++restoreAttempt.current;
    const latest = () => attempt === restoreAttempt.current;
    setRestoring(true);
    setError(null);
    try {
      const conv = await api.conversation(id);
      if (!latest()) return; // another conversation was picked, or New question, meanwhile
      const restored = stagesOf(conv);
      setMessages(conv.messages.map((m) => ({ id: nextId.current++, role: m.role, content: m.content, kind: m.kind, suggestions: m.suggestions, choices: m.choices })));
      setStages(restored);
      setRestoredRunId(conv.runs.at(-1)?.id ?? null);
      setDecision(restored.decision?.data?.decision ?? null);
      setConvId(conv._id);
      setConvState(conv.state === "clarifying" ? "clarifying" : "idle");
      setCurrentConversation(conv._id);
      setOffline(false);
    } catch (err) {
      if ((err as { status?: number }).status === 404) {
        forgetConversation(id); // confirmed gone (e.g. a restart without MongoDB): drop only this entry
      } else if (latest()) {
        setOffline(true); // a passing failure: the entry stays, and picking it again retries
      }
    } finally {
      if (latest()) setRestoring(false);
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
    api.guidedExamples().then((g) => setExamples(g.examples)).catch(() => setExamples([]));
  }, []);

  useEffect(() => {
    const last = listRef.current?.lastElementChild;
    if (!last) return;
    // Open a finished dashboard at its headline. Keep following messages while the request runs.
    const result = !busy && last.classList.contains("verdict");
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    last.scrollIntoView({ block: result ? "start" : "nearest", behavior: result || reducedMotion ? "instant" : "smooth" });
  }, [messages, busy, stages]);

  const handleEvent = useCallback((e: PipelineEvent) => {
    switch (e.type) {
      case "conversation":
        streamId.current = e.id; // identifies the working stream only; it joins History once the server saves it
        setConvId(e.id);
        break;
      case "user_message":
        // The server saved this accepted message: the conversation belongs to this tab's History from now on.
        if (e.history && e.history._id === streamId.current) recordConversation(e.history);
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
        setMessages((m) => [...m, { id: nextId.current++, role: "assistant", content: e.content, kind: e.kind, suggestions: e.suggestions, choices: e.choices }]);
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
    }
  }, [handleEvent]);

  const send = useCallback((text: string, presetId?: string, guided?: { guided_id?: string; choice_id?: string }) => {
    setChecking(true);
    setMessages((m) => [...m, { id: nextId.current++, role: "user", content: text }]);
    // A guided example starts a fresh conversation; its answers continue the current one.
    const conversation = guided?.guided_id ? null : convId;
    void run("/api/chat", { conversation_id: conversation, message: guided?.guided_id ? "" : text, preset_id: presetId ?? null,
      guided_id: guided?.guided_id ?? null, choice_id: guided?.choice_id ?? null });
  }, [convId, run]);

  /** Clear the screen and the open selection; History keeps every earlier conversation. */
  const newChat = () => {
    restoreAttempt.current++; // a restore still loading must not repaint Ask afterwards
    cancelPendingConversation();
    setRestoring(false);
    setCurrentConversation(null);
    setRestoredRunId(null);
    setConvId(null); setConvState("idle"); setMessages([]); setStages({}); setDecision(null); setError(null);
    requestAnimationFrame(() => document.getElementById("ask-input")?.focus());
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
      {m.id === lastId && !busy && m.choices && m.choices.length > 0 && (
        <div className="chips guided-choices" role="group" aria-label="Choose an answer">
          {m.choices.map((c) => <button key={c.id} type="button" onClick={() => send(c.label, undefined, { choice_id: c.id })}>
            {c.label}{c.detail && <span className="choice-detail">{c.detail}</span>}</button>)}
        </div>
      )}
      {m.id === lastId && !busy && !m.choices?.length && m.suggestions && m.suggestions.length > 0 && (
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
    const starter = (e: GuidedExample) => <button key={e.id} type="button" onClick={() => send(e.text, undefined, { guided_id: e.id })} disabled={busy}>{e.text}</button>;
    const visible = (examples ?? []).filter((e) => e.placement === "visible");
    const more = (examples ?? []).filter((e) => e.placement === "more");
    return (
      <div className="ask-empty">
        <div className="ask-empty-above">
          {offlineBanner}
          <h1>What do you need to decide?</h1>
        </div>
        <Composer onSend={(t) => send(t)} disabled={busy} autoFocus placeholder="Describe the decision or the numbers you need, in your own words" />
        <div className="ask-empty-below">
          {visible.length > 0 && <div className="starter-chips" role="group" aria-label="Example dashboards to build">
            {visible.map(starter)}
          </div>}
          {more.length > 0 && <details className="rh-examples"><summary>More example questions</summary>
            <div className="starter-chips" role="group" aria-label="More example dashboards">{more.map(starter)}</div>
          </details>}
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
