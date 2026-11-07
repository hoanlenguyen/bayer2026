import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, streamPost } from "../api/client";
import type { CatalogMeta, DecisionType, Health, PipelineEvent, Preset, StageEvent, StageId } from "../api/types";
import { FlowPanel, RUNNING_COPY } from "../components/ask/FlowPanel";
import { VerdictCard } from "../components/ask/VerdictCard";
import { Icon } from "../components/Icon";

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
  const [dept, setDept] = useState("All");

  const [convId, setConvId] = useState<string | null>(null);
  const [convState, setConvState] = useState<ConvState>("idle");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [stages, setStages] = useState<Partial<Record<StageId, StageEvent>>>({});
  const [decision, setDecision] = useState<DecisionType | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const nextId = useRef(1);
  const listRef = useRef<HTMLDivElement>(null);

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
    try {
      await streamPost(path, body, handleEvent);
      setOffline(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setOffline(true);
    } finally {
      setBusy(false);
    }
  }, [handleEvent]);

  const send = useCallback((text: string, presetId?: string) => {
    if (convState !== "clarifying") {
      setStages({});
      setDecision(null);
    }
    setMessages((m) => [...m, { id: nextId.current++, role: "user", content: text }]);
    void run("/api/chat", { conversation_id: convId, message: text, preset_id: presetId ?? null });
  }, [convId, convState, run]);

  const approve = (approved: boolean) => {
    const approver = stages.approval?.data?.approver ?? "Report owner";
    setMessages((m) => [...m, { id: nextId.current++, role: "user", content: approved ? `Approved as ${approver}` : "Rejected" }]);
    void run("/api/approve", { conversation_id: convId, approved, approver });
  };

  const newChat = () => {
    setConvId(null); setConvState("idle"); setMessages([]); setStages({}); setDecision(null); setError(null);
  };

  const departments = useMemo(() => ["All", ...new Set(presets.map((p) => p.department))], [presets]);
  const shownPresets = useMemo(() => presets.filter((p) => dept === "All" || p.department === dept), [presets, dept]);
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
        {offlineBanner}
        <h1>What do you need to decide?</h1>
        <Composer onSend={(t) => send(t)} disabled={busy} autoFocus placeholder="Describe the decision or the numbers you need, in your own words" />
        <section className="starters" aria-labelledby="starters-title">
          <div className="starters-head">
            <h2 id="starters-title">Common questions</h2>
            <div className="dept-filter" role="group" aria-label="Filter questions by department">
              {departments.map((d) => (
                <button key={d} type="button" aria-pressed={dept === d} onClick={() => setDept(d)}>{d}</button>
              ))}
            </div>
          </div>
          <div className="preset-grid">
            {shownPresets.map((p) => (
              <button key={p.id} type="button" className="preset" onClick={() => send(p.prompt, p.id)} disabled={busy}>
                <span className="preset-title">{p.title}</span>
                <span className="preset-prompt">{p.prompt}</span>
                {dept === "All" && <span className="preset-dept">{p.department}</span>}
              </button>
            ))}
          </div>
        </section>
        <p className="fineprint">The AI sees catalog metadata only, never raw production data.</p>
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
          {messages.map((m) => (
            <div key={m.id} className={`msg msg-${m.role}`}>
              <p><RichText text={m.content} /></p>
              {m.id === lastId && !busy && m.suggestions && m.suggestions.length > 0 && (
                <div className="chips">
                  {m.suggestions.map((s) => <button key={s} type="button" onClick={() => send(s)}>{s}</button>)}
                </div>
              )}
            </div>
          ))}
          {busy && !hasVerdict && (
            <p className="working"><span className="spinner" aria-hidden="true" />{runningStage ? RUNNING_COPY[runningStage] : "Reading your question"}</p>
          )}
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
