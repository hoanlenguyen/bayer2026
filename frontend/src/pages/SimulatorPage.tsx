import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, streamPost } from "../api/client";
import type { CatalogMeta, DecidedBy, DecisionType, GateLabel, Health, SimulatorEvent, SimulatorMessage, StageEvent, StageId, TokenUsage } from "../api/types";
import { FlowPanel, type FlowGroup } from "../components/ask/FlowPanel";
import { RecommendationChip } from "../components/ask/RecommendationChip";
import { VerdictCard } from "../components/ask/VerdictCard";
import { Icon } from "../components/Icon";

type Speaker = "A" | "B";

/** Who is talking. The API keeps the short codes; people only ever see these names. */
const NAMES: Record<SimulatorMessage["speaker"], string> = { A: "SinceAI", B: "Brainrot", C: "Analytics Manager" };

/** Greetings and business talk stay quiet, a vague request waits for details, and two real requests get two different answers. */
const SAMPLE: { speaker: Speaker; text: string }[] = [
  { speaker: "A", text: "Hello, how are you?" },
  { speaker: "B", text: "Good thanks, you?" },
  { speaker: "A", text: "Not bad, busy week. Did you watch the game last night?" },
  { speaker: "B", text: "Ha, no. Eylea looks strong in Japan this quarter by the way." },
  { speaker: "A", text: "We should build a new dashboard for the team." },
  { speaker: "B", text: "Yes, for Eylea net sales and digital engagement in Japan." },
  { speaker: "A", text: "Oh nice, thanks." },
  { speaker: "B", text: "Great, that saves us a week." },
  { speaker: "A", text: "One more thing, we also need a monthly supply-risk dashboard by medicine and country." },
  { speaker: "B", text: "Okay, good to know." },
  { speaker: "A", text: "Lunch on Friday?" },
];

const LABEL_TEXT: Record<GateLabel, string> = {
  off_topic: "Off topic, stays quiet",
  business_talk: "Business talk, stays quiet",
  needs_decision: "Needs a decision",
  needs_context: "Not enough detail yet, keeps listening",
  already_answered: "Already answered, stays quiet",
};
const DECIDED_BY: Record<DecidedBy, string> = { jev: "Jev", llm: "GPT", rules: "Rules" };

const tokens = (u?: TokenUsage | null) => (u ? u.input_tokens + u.output_tokens : 0);
const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

function stageMap(stages?: StageEvent[]): Partial<Record<StageId, StageEvent>> {
  return Object.fromEntries((stages ?? []).map((s) => [s.stage, s]));
}

function Sentence({ m }: { m: SimulatorMessage }) {
  const meta = [m.confidence != null ? `${Math.round(m.confidence * 100)}% sure` : null,
                m.ms != null ? `${m.ms.toLocaleString()} ms` : null,
                m.decided_by ? DECIDED_BY[m.decided_by] : null].filter(Boolean).join(" · ");
  return (
    <div className={`sim-line sim-line-${m.speaker}`}>
      <span className="sim-name">{NAMES[m.speaker]}</span>
      <p className="sim-bubble">{m.text}</p>
      {m.failed ? (
        <span className="sim-verdict sim-verdict-failed">Could not check this sentence</span>
      ) : m.label ? (
        <span className={`sim-verdict sim-verdict-${m.label}`}>{LABEL_TEXT[m.label]}{meta && <span className="sim-meta"> · {meta}</span>}</span>
      ) : (
        <span className="sim-verdict working"><span className="spinner" aria-hidden="true" />Checking the sentence</span>
      )}
      {m.searching && <span className="sim-verdict working"><span className="spinner" aria-hidden="true" />Checking the catalog</span>}
    </div>
  );
}

function Answer({ m, n, catalog, onSelect }: { m: SimulatorMessage; n: number; catalog: CatalogMeta | null; onSelect: () => void }) {
  const [open, setOpen] = useState(false); // the chat stays readable; the full card is one click away
  const cardId = `sim-verdict-${m.id}`;
  return (
    <div className="sim-answer">
      <div className="sim-answer-bubble">
        <div className="sim-answer-head">
          <span className="sim-name">{NAMES.C}</span>
          <button type="button" className="sim-steps-link" aria-label={`Open analysis ${n} in How this was decided`} title="Open its analysis" onClick={onSelect}>({n})</button>
        </div>
        <p className="sim-answer-text">{m.text}</p>
      </div>
      <div className={`sim-verdict-box${open ? " open" : ""}`}>
        <button type="button" className="sim-verdict-toggle" aria-expanded={open} aria-controls={cardId} onClick={() => setOpen((o) => !o)}>
          {m.decision && <RecommendationChip value={m.decision} />}
          <span>{open ? "Hide the recommendation" : "Show the recommendation"}</span>
          <span className={`flow-chevron${open ? " open" : ""}`}><Icon name="chevron" size={14} /></span>
        </button>
        {open && <div id={cardId}><VerdictCard stages={stageMap(m.stages)} catalog={catalog} busy={false} /></div>}
      </div>
    </div>
  );
}

function Stats({ messages }: { messages: SimulatorMessage[] }) {
  const checked = messages.filter((m) => m.speaker !== "C" && m.decided_by);
  const count = (by: DecidedBy) => checked.filter((m) => m.decided_by === by).length;
  const ms = checked.reduce((sum, m) => sum + (m.ms ?? 0), 0);
  const rows: [string, string][] = [
    ["Sentences checked", String(checked.length)],
    ["Analytics Manager spoke", String(messages.filter((m) => m.speaker === "C").length)],
    ["Jev / GPT / rules", `${count("jev")} / ${count("llm")} / ${count("rules")}`],
    ["Tokens", (checked.reduce((sum, m) => sum + tokens(m.usage), 0) + messages.reduce((sum, m) => sum + tokens(m.search_usage), 0)).toLocaleString()],
    ["Jev cost", `$${checked.reduce((sum, m) => sum + (m.cost ?? 0), 0).toFixed(6)}`],
    ["Average check", checked.length ? `${Math.round(ms / checked.length).toLocaleString()} ms` : "None yet"],
  ];
  return (
    <dl className="sim-stats" aria-label="This chat">
      {rows.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}
    </dl>
  );
}

/** Two people chat. Jev reads each sentence, and Analytics Manager speaks only when one needs a decision. */
export function SimulatorPage() {
  const [messages, setMessages] = useState<SimulatorMessage[]>([]);
  const [speaker, setSpeaker] = useState<Speaker>("A");
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [health, setHealth] = useState<Health | null>(null);
  const [catalog, setCatalog] = useState<CatalogMeta | null>(null);
  const [jevOff, setJevOff] = useState(false);
  const [selected, setSelectedId] = useState<number | null>(null);
  const [focusTick, setFocusTick] = useState(0);
  const setSelected = (id: number | null) => { setSelectedId(id); setFocusTick((t) => t + 1); };
  const list = useRef<SimulatorMessage[]>([]);
  const stop = useRef(false);
  const nextId = useRef(0);
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.health().then((h) => { setHealth(h); setJevOff(!h.jev); }).catch(() => { /* the first sentence will say so */ });
    api.catalog().then(setCatalog).catch(() => { /* names fall back to IDs */ });
  }, []);
  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight });
  }, [messages]);

  const commit = (next: SimulatorMessage[]) => { list.current = next; setMessages(next); };
  const patch = (id: number, change: Partial<SimulatorMessage>) => commit(list.current.map((m) => (m.id === id ? { ...m, ...change } : m)));

  const send = async (who: Speaker, text: string) => {
    const history = list.current.filter((m) => !m.failed).map(({ speaker: s, text: t, label, kind, answer_key }) => ({ speaker: s, text: t, label, kind, answer_key }));
    const id = nextId.current++;
    commit([...list.current, { id, speaker: who, text }]);
    setBusy(true);
    try {
      await streamPost<SimulatorEvent>("/api/simulator/turn", { speaker: who, text, history }, (ev) => {
        if (ev.type === "gate") {
          setJevOff(!ev.jev_on);
          patch(id, { label: ev.label, confidence: ev.confidence, ms: ev.ms, decided_by: ev.decided_by, usage: ev.usage, cost: ev.cost });
        } else if (ev.type === "searching") {
          patch(id, { searching: true });
        } else if (ev.type === "needs_context") {
          patch(id, { label: "needs_context", searching: false, search_usage: ev.usage });
        } else if (ev.type === "already_answered") {
          patch(id, { label: "already_answered", searching: false, search_usage: ev.usage });
        } else if (ev.type === "reply") {
          patch(id, { searching: false, search_usage: ev.usage });
          const answerId = nextId.current++;
          commit([...list.current, { id: answerId, speaker: "C", text: ev.text, kind: ev.kind, answer_key: ev.answer_key,
                                     decision: ev.decision, recommendation: ev.recommendation, report: ev.report, stages: ev.stages,
                                     request: list.current.find((x) => x.id === id)?.text }]);
        } else if (ev.type === "error") {
          patch(id, { failed: true, searching: false });
        }
      });
    } catch {
      patch(id, { failed: true, searching: false });
    } finally {
      setBusy(false);
    }
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const text = draft.trim();
    if (!text || busy) return;
    setDraft("");
    setSpeaker(speaker === "A" ? "B" : "A");
    void send(speaker, text);
  };

  const play = async () => {
    stop.current = false;
    commit([]);
    setSelected(null);
    setPlaying(true);
    for (const line of SAMPLE) {
      if (stop.current) break;
      await send(line.speaker, line.text);
      await wait(700);
    }
    setPlaying(false);
  };

  const clear = () => {
    stop.current = true;
    commit([]);
    setSelected(null);
  };

  const answers = messages.filter((m) => m.speaker === "C");
  const groups: FlowGroup[] = answers.map((m) => {
    const stages = stageMap(m.stages);
    return { key: String(m.id), title: m.request ?? m.text, stages, decision: (stages.decision?.data?.decision as DecisionType | undefined) ?? null };
  });

  return (
    <main className="sim-page">
      <div className="sim-chat">
        <header className="sim-head">
          <div>
            <h1>Conversation simulation</h1>
            <p>{NAMES.A} and {NAMES.B} talk. Jev reads each sentence, and {NAMES.C} speaks only when one needs a decision.</p>
          </div>
          <div className="sim-actions">
            {playing
              ? <button type="button" className="btn" onClick={() => { stop.current = true; }}>Stop</button>
              : <button type="button" className="btn" disabled={busy} onClick={() => void play()}>Play sample</button>}
            <button type="button" className="btn btn-outline" disabled={busy || messages.length === 0} onClick={clear}>Clear</button>
          </div>
        </header>
        <Stats messages={messages} />
        {jevOff && <p className="sim-warning" role="status"><Icon name="alert" size={14} /> Jev is off, so GPT or the rules decide here, not Jev. Set TYPESAFE_API_KEY to use it.</p>}
        <div className="messages sim-messages" ref={scroller} aria-live="polite">
          {messages.length === 0 && <p className="sim-empty">Type as {NAMES.A} or {NAMES.B} below, or play the sample chat. Nothing here is saved.</p>}
          {messages.map((m) => (m.speaker === "C"
            ? <Answer key={m.id} m={m} n={answers.indexOf(m) + 1} catalog={catalog} onSelect={() => setSelected(m.id)} />
            : <Sentence key={m.id} m={m} />))}
        </div>
        <form className="chat-composer" onSubmit={submit}>
          <div className="composer">
            <div className="sim-speaker" role="group" aria-label="Who is speaking">
              {(["A", "B"] as const).map((s) => (
                <button key={s} type="button" aria-pressed={speaker === s} onClick={() => setSpeaker(s)}>{NAMES[s]}</button>
              ))}
            </div>
            <textarea rows={1} maxLength={2000} value={draft} disabled={playing} aria-label={`Message as ${NAMES[speaker]}`} placeholder={`Message as ${NAMES[speaker]}`}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) submit(e); }} />
            <button type="submit" className="send" aria-label="Send" disabled={busy || playing || !draft.trim()}><Icon name="arrowUp" /></button>
          </div>
        </form>
      </div>
      <FlowPanel stages={{}} decision={null} health={health} catalog={catalog} groups={groups} focusGroup={selected === null ? null : String(selected)} focusTick={focusTick} />
    </main>
  );
}
