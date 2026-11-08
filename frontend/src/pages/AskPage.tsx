import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { api, streamPost } from "../api/client";
import type { CatalogMeta, DecisionType, GuidedChoice, GuidedExample, GuidedFacts, Health, PipelineEvent, Preset, StageEvent, StageId } from "../api/types";
import { GUIDED_EXAMPLES } from "../lib/guidedExamples";
import { FlowPanel, RUNNING_COPY } from "../components/ask/FlowPanel";
import { TriageStrip } from "../components/ask/TriageStrip";
import { VerdictCard } from "../components/ask/VerdictCard";
import { Icon } from "../components/Icon";
import { LiveSteps, type TurnPhase } from "../components/ask/LiveSteps";
import { cancelPendingConversation, CURRENT_REMOVED_EVENT, forgetConversation, getCurrentConversation, inSession, OPEN_CONVERSATION_EVENT, recordConversation, setAnswerInProgress, setCurrentConversation, stagesOf, stagesOfRun, takePendingConversation } from "../lib/conversations";
import { scrollWithin } from "../lib/scrollWithin";

interface ChatMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
  kind?: "question" | "result" | "retry";
  suggestions?: string[];
  choices?: GuidedChoice[];
  /** The run this assistant message answers: an earlier run's answer card stays under its last message. */
  runId?: string;
  facts?: GuidedFacts;
}

type Stages = Partial<Record<StageId, StageEvent>>;
/** One submission and its real progress. Its new messages and recommendation show once the stream settled with `done`. */
interface Turn {
  id: number; kind: "guided" | "typed" | "choice"; label: string; msgFrom: number; stagesBefore: Stages;
  phase: TurnPhase; newRun: boolean; settled: boolean; failed: boolean; rejected: boolean; timelineBefore: number | null;
}

const withoutOutcome = (s: Stages): Stages => { const { decision: _d, actions: _a, deliver: _v, ...rest } = s; return rest; };

/** The discovery step completes the classification shown under Understand the request (model, existing report). */
export function withClassification(s: Stages, e: StageEvent): Stages {
  const extra = e.stage === "discovery" && e.status === "done" ? e.data?.classification : null;
  if (!extra || !s.intent) return { ...s, [e.stage]: e };
  return { ...s, [e.stage]: e, intent: { ...s.intent, data: { ...s.intent.data, classification: { ...(s.intent.data?.classification ?? {}), ...extra } } } };
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

  const [convId, setConvId] = useState<string | null>(null);
  const [restoredRunId, setRestoredRunId] = useState<string | null>(null);
  const [convState, setConvState] = useState<ConvState>("idle");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [stages, setStages] = useState<Partial<Record<StageId, StageEvent>>>({});
  const stagesRef = useRef(stages);
  stagesRef.current = stages;
  // Earlier runs' completed steps, by run ID: their answer cards stay in the chat when a new question starts.
  const [pastRuns, setPastRuns] = useState<Record<string, Partial<Record<StageId, StageEvent>>>>({});
  const [decision, setDecision] = useState<DecisionType | null>(null);
  const [busy, setBusy] = useState(false);
  const [checking, setChecking] = useState(false); // sent, and the backend has not said yet if it accepts the message
  const [error, setError] = useState<string | null>(null);
  const nextId = useRef(1);
  const listRef = useRef<HTMLDivElement>(null);
  const restoreAttempt = useRef(0);
  const [turn, setTurn] = useState<Turn | null>(null);
  const turnRef = useRef<Turn | null>(null);
  const turnIds = useRef(0);
  // The user message whose steps show under it: the latest accepted submission, or the restored conversation's last one.
  const [timelineAt, setTimelineAt] = useState<number | null>(null);
  const updateTurn = useCallback((id: number, patch: Partial<Turn>) => setTurn((t) => {
    const next = t && t.id === id ? { ...t, ...patch } : t;
    turnRef.current = next;
    return next;
  }), []);
  const endTurn = useCallback(() => {  // reset, conversation change or unmount: no late update may repaint Ask
    turnRef.current = null;
    setTurn(null);
  }, []);
  const streamId = useRef<string | null>(null);
  const [restoring, setRestoring] = useState(() => getCurrentConversation() !== null);

  /** Brings a conversation of this tab back as it was. Sending next continues it, with its context, in the backend.
   *  Only the latest selection may change the screen: an older answer, error or loading end is ignored. */
  const restore = useCallback(async (id: string) => {
    if (!inSession(id)) return;
    endTurn();
    const attempt = ++restoreAttempt.current;
    const latest = () => attempt === restoreAttempt.current;
    setRestoring(true);
    setError(null);
    try {
      const conv = await api.conversation(id);
      if (!latest()) return; // another conversation was picked, or New question, meanwhile
      const restored = stagesOf(conv);
      const restoredMessages: ChatMessage[] = conv.messages.map((m) => ({ id: nextId.current++, role: m.role, content: m.content, kind: m.kind, suggestions: m.suggestions, choices: m.choices, runId: m.run_id }));
      setPastRuns(Object.fromEntries(conv.runs.slice(0, -1).map((r) => [r.id, stagesOfRun(r)] as const)
        .filter(([, s]) => s.decision?.status === "done")));
      setMessages(restoredMessages);
      // A saved run comes back as completed evidence under its last accepted message; nothing is replayed.
      const accepted = conv.messages.map((m, i) => (m.role === "user" && !(m as { rejected?: boolean }).rejected ? i : -1)).filter((i) => i >= 0);
      setTimelineAt(Object.keys(restored).length && accepted.length ? restoredMessages[accepted.at(-1)!].id : null);
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
  }, [endTurn]);

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
    const last = listRef.current?.lastElementChild;
    if (!last) return;
    // Open a finished dashboard at its headline. Keep following messages while the request runs.
    const result = !busy && last.classList.contains("verdict");
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    scrollWithin(last, result ? "start" : "nearest", result || reducedMotion ? "instant" : "smooth");
    // Desktop Ask fits the window and never scrolls as a page: undo any shift something else caused.
    if (window.scrollY && window.matchMedia("(min-width: 961px)").matches) window.scrollTo(0, 0);
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
      case "processing": {
        const t = turnRef.current;
        if (t) updateTurn(t.id, { phase: e.phase });
        break;
      }
      case "stage":
        setChecking(false);
        // The first step starting means the message was accepted as a new question: only now does the last answer go.
        if (e.stage === "intent" && e.status === "running") {
          if (turnRef.current) updateTurn(turnRef.current.id, { newRun: true });
          setRestoredRunId(null);
          // Keep the finished answer of the run that ends here, so its card stays in the conversation.
          const previous = stagesRef.current;
          const previousRun = previous.decision?.status === "done" ? previous.decision.data?.run_id : null;
          if (previousRun) setPastRuns((p) => ({ ...p, [previousRun]: previous }));
          setStages({ intent: e });
          setDecision(null);
          break;
        }
        setStages((s) => withClassification(s, e));
        if (e.stage === "decision" && e.status === "done") setDecision(e.data.decision);
        break;
      case "message":
        setChecking(false);
        if (e.kind === "retry" && turnRef.current) updateTurn(turnRef.current.id, { rejected: true });  // shown as soon as it settles
        setMessages((m) => [...m, { id: nextId.current++, role: "assistant", content: e.content, kind: e.kind, suggestions: e.suggestions, choices: e.choices, facts: e.facts, runId: e.run_id }]);
        break;
      case "done":
        setConvState(e.state);
        break;
      case "error":
        setError(e.message);
        break;
    }
  }, [updateTurn]);

  /** One stream per submission, applied in order as events arrive. A turn ends cleanly only with `done` and no error. */
  const run = useCallback(async (path: string, body: unknown, turnId: number) => {
    setBusy(true);
    setAnswerInProgress(true);
    setError(null);
    let gotDone = false, failed = false;
    try {
      await streamPost(path, body, (e) => { if (e.type === "done") gotDone = true; if (e.type === "error") failed = true; handleEvent(e); });
      setOffline(false);
    } catch (err) {
      failed = true;
      setError(err instanceof Error ? err.message : String(err));
      setOffline(true);
    } finally {
      if (!failed && !gotDone) { failed = true; setError("The answer was cut off before it finished. Try sending it again."); }
      updateTurn(turnId, { settled: true, failed });
      setBusy(false);
      setChecking(false);
      setAnswerInProgress(false);
    }
  }, [handleEvent, updateTurn]);

  // The turn's outcome shows as soon as the stream settled with `done`. A failed or interrupted stream never reveals a
  // success: the screen goes back to the last valid outcome. A rejected message leaves the earlier steps where they were.
  useEffect(() => {
    if (!turn || !turn.settled) return;
    if (turn.failed) {
      setStages(turn.stagesBefore);
      setDecision(turn.stagesBefore.decision?.data?.decision ?? null);
      setMessages((m) => m.slice(0, turn.msgFrom));
      setTimelineAt(turn.timelineBefore);
    } else if (turn.rejected) {
      setTimelineAt(turn.timelineBefore);
    }
    endTurn();
  }, [turn, endTurn]);

  const send = useCallback((text: string, presetId?: string, guided?: { guided_id?: string; choice_id?: string }) => {
    if (turnRef.current) return;  // one request per action: a repeated click or Enter is ignored until this turn ends
    const id = ++turnIds.current;
    // A reply to an open question (typed, a suggestion or an offered choice) is an answer, not a new request.
    const kind = guided?.guided_id ? "guided" : guided?.choice_id || convState === "clarifying" ? "choice" : "typed";
    const t: Turn = { id, kind, label: text,
      msgFrom: messages.length + 1, stagesBefore: stages, phase: "sent", newRun: false, settled: false, failed: false,
      rejected: false, timelineBefore: timelineAt };
    turnRef.current = t;
    setTurn(t);
    setChecking(true);
    const messageId = nextId.current++;
    setMessages((m) => [...m, { id: messageId, role: "user", content: text }]);
    setTimelineAt(messageId);
    // A guided example starts a fresh conversation; its answers continue the current one.
    const conversation = guided?.guided_id ? null : convId;
    void run("/api/chat", { conversation_id: conversation, message: guided?.guided_id ? "" : text, preset_id: presetId ?? null,
      guided_id: guided?.guided_id ?? null, choice_id: guided?.choice_id ?? null }, id);
  }, [convId, convState, run, messages.length, stages, timelineAt]);

  /** Clear the screen and the open selection; History keeps every earlier conversation. */
  const newChat = () => {
    endTurn();
    restoreAttempt.current++; // a restore still loading must not repaint Ask afterwards
    cancelPendingConversation();
    setRestoring(false);
    setCurrentConversation(null);
    setRestoredRunId(null);
    setConvId(null); setConvState("idle"); setMessages([]); setStages({}); setPastRuns({}); setDecision(null); setError(null); setTimelineAt(null);
    requestAnimationFrame(() => document.getElementById("ask-input")?.focus());
  };

  useEffect(() => {
    // The chat on screen was deleted from the list.
    const cleared = () => {
      endTurn();
      restoreAttempt.current++;
      setRestoring(false);
      setRestoredRunId(null);
      setConvId(null); setConvState("idle"); setMessages([]); setStages({}); setPastRuns({}); setDecision(null); setError(null); setTimelineAt(null);
    };
    window.addEventListener(CURRENT_REMOVED_EVENT, cleared);
    return () => window.removeEventListener(CURRENT_REMOVED_EVENT, cleared);
  }, [endTurn]);

  // While a turn is open, only what was on screen before it plus the sent message shows; its replies and recommendation
  // come with `done`. The steps under the message show the turn's real progress meanwhile.
  const shownMessages = turn ? messages.slice(0, turn.msgFrom) : messages;
  const shownStages = turn ? (turn.newRun ? {} : turn.stagesBefore) : stages;
  // A new request has no steps of its own until its first stage arrives (the previous run's stay in the side panel).
  const turnStages: Stages = turn && !turn.newRun && turn.kind !== "choice" ? {} : stages;
  const lastId = shownMessages.length ? shownMessages[shownMessages.length - 1].id : -1;
  const runningStage = (Object.values(stages) as StageEvent[]).find((s) => s.status === "running")?.stage;
  const hasVerdict = shownStages.decision?.status === "done";

  // Messages rejected after an answer come below its verdict card, which stays because nothing new has started.
  let tailStart = shownMessages.length;
  if (hasVerdict) {
    if ((checking || turn) && shownMessages[tailStart - 1]?.role === "user") tailStart--;
    while (tailStart >= 2 && shownMessages[tailStart - 1].kind === "retry" && shownMessages[tailStart - 2].role === "user") tailStart -= 2;
  }
  // An earlier run's answer card sits under that run's last message (never the run still on screen as the current answer).
  const currentRun = shownStages.decision?.data?.run_id ?? (turn ? null : restoredRunId);
  const pastAnchors = new Map<string, number>();
  for (const m of shownMessages) if (m.runId && m.runId !== currentRun && pastRuns[m.runId]) pastAnchors.set(m.runId, m.id);
  const renderMessage = (m: ChatMessage) => (<Fragment key={m.id}>
    <div className={`msg msg-${m.role}`}>
      <p><RichText text={m.content} /></p>
      {m.id === lastId && !busy && !turn && m.choices && m.choices.length > 0 && (
        <div className="chips guided-choices" role="group" aria-label="Choose an answer">
          {m.choices.map((c) => <button key={c.id} type="button" onClick={() => send(c.label, undefined, { choice_id: c.id })}>
            {c.label}{c.detail && <span className="choice-detail">{c.detail}</span>}</button>)}
        </div>
      )}
      {m.id === lastId && !busy && !turn && !m.choices?.length && m.suggestions && m.suggestions.length > 0 && (
        <div className="chips">
          {m.suggestions.map((s) => <button key={s} type="button" onClick={() => send(s, presets.find((p) => p.prompt === s)?.id)}>{s}</button>)}
        </div>
      )}
    </div>
    {m.runId && pastAnchors.get(m.runId) === m.id && pastRuns[m.runId] && <div className="past-answer">
      <TriageStrip stages={pastRuns[m.runId]} />
      <VerdictCard stages={pastRuns[m.runId]} catalog={catalog} busy={false}
        handoff={convId ? { conversationId: convId, runId: m.runId } : undefined} />
    </div>}
    {m.id === timelineAt && (turn || Object.keys(stages).length > 0) && !(turn?.settled && turn.rejected)
      && <LiveSteps stages={turnStages} active={!!turn && !turn.settled} phase={turn?.phase ?? null} />}
  </Fragment>);
  const working = turn ? null
    : busy && (!hasVerdict || checking) && (
      <p className="working"><span className="spinner" aria-hidden="true" />{runningStage ? RUNNING_COPY[runningStage] : "Reading your question"}</p>);
  const runId = shownStages.decision?.data?.run_id ?? (turn ? null : restoredRunId);
  const handoff = convId && runId && !busy && !turn && !restoring ? { conversationId: convId, runId } : undefined;
  const answerCards = <><TriageStrip stages={shownStages} /><VerdictCard stages={shownStages} catalog={catalog} busy={busy} handoff={handoff} /></>;

  const offlineBanner = offline && (
    <div className="banner" role="status">
      The backend is not reachable. Start it with <code>uvicorn app.main:app --reload --port 8000</code> in <code>backend/</code>, then reload.
    </div>
  );

  if (messages.length === 0 && restoring) {
    return <div className="ask-empty"><p className="working"><span className="spinner" aria-hidden="true" />Opening your conversation</p></div>;
  }

  if (messages.length === 0) {
    const starter = (e: GuidedExample) => <button key={e.id} type="button" onClick={() => send(e.text)} disabled={busy}>{e.text}</button>;
    const visible = GUIDED_EXAMPLES.filter((e) => e.placement === "visible");
    const more = GUIDED_EXAMPLES.filter((e) => e.placement === "more");
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
          {shownMessages.slice(0, tailStart).map(renderMessage)}
          {tailStart < shownMessages.length
            ? <>{answerCards}{shownMessages.slice(tailStart).map(renderMessage)}{working}</>
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
      {/* While a turn is open the panel shows the checks as they complete, but not the recommendation they lead to. */}
      <FlowPanel stages={turn ? withoutOutcome(stages) : stages} decision={turn ? null : decision} health={health} catalog={catalog} />
    </div>
  );
}
