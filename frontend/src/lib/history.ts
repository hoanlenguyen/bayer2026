import { useSyncExternalStore } from "react";
import type { DecisionType, PipelineEvent, StageEvent, StageId } from "../api/types";

/**
 * Every question with its result, most recently used first, as structured JSON in this browser's localStorage.
 * Nothing goes to the backend, so history stays on this browser and device.
 */
export type HistoryStatus = "running" | "needs_answer" | "awaiting_approval" | "completed" | "rejected" | "failed" | "interrupted";

export interface HistoryMessage {
  role: "user" | "assistant";
  content: string;
  kind?: "question" | "result" | "approval";
  suggestions?: string[];
}

/** One entry is one conversation: further questions asked inside it continue it. */
export interface QuestionEntry {
  id: string;
  kind: "question";
  created_at: string;
  updated_at: string;
  status: HistoryStatus;
  request: {
    text: string; // the first question, shown as the entry's name
    latest_question?: string; // the question the result below answers
    preset_id: string | null;
    conversation_id: string | null;
  };
  result: {
    decision: DecisionType | null;
    summary: string | null;
    report: { id: string; name: string } | null;
    scores: { coverage: number; freshness: number; governance: number } | null;
    messages: HistoryMessage[]; // the whole conversation
    stages: Partial<Record<StageId, StageEvent>>;
    error: string | null;
    earlier?: EarlierAnswer[]; // answers to the questions before the latest one
  };
}

export interface EarlierAnswer {
  question: string;
  decision: DecisionType | null;
  summary: string | null;
  report: { id: string; name: string } | null;
  scores: { coverage: number; freshness: number; governance: number } | null;
  answered_at: string;
}

const latestQuestion = (e: QuestionEntry) => e.request.latest_question ?? e.request.text;

const STORAGE_KEY = "analytics-manager.history.v2";
try {
  localStorage.removeItem("analytics-manager.history"); // the earlier format: history starts empty with this one
} catch {
  // storage is blocked: read() below copes with that too
}
const MAX_ENTRIES = 50; // a question's result is about 40 KB, so this stays well inside the browser's limit

function read(): QuestionEntry[] {
  try {
    const data: unknown = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "[]");
    if (!Array.isArray(data)) return [];
    return (data as QuestionEntry[])
      .filter((e) => e.kind === "question") // earlier versions also saved searches
      // An answer still running when the page last closed will never finish.
      .map((e) => (e.status === "running" ? { ...e, status: "interrupted" as const } : e));
  } catch {
    return [];
  }
}

let entries: QuestionEntry[] = read();
const listeners = new Set<() => void>();

function commit(next: QuestionEntry[]) {
  entries = next.slice(0, MAX_ENTRIES);
  // If the browser is out of room, give up the oldest entries rather than the newest answer.
  for (let keep = entries.length; keep > 0; keep = Math.floor(keep / 2)) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(entries.slice(0, keep)));
      break;
    } catch {
      if (keep === 1) console.warn("History could not be saved in this browser");
    }
  }
  listeners.forEach((l) => l());
}

export function useHistoryEntries(): QuestionEntry[] {
  return useSyncExternalStore((l) => { listeners.add(l); return () => listeners.delete(l); }, () => entries);
}

export const getHistoryEntry = (id: string): QuestionEntry | undefined => entries.find((e) => e.id === id);

const now = () => new Date().toISOString();

/** Same question despite different capitals or spacing. */
const sameQuestion = (a: string, b: string) => {
  const normal = (s: string) => s.trim().replace(/\s+/g, " ").toLowerCase();
  return normal(a) === normal(b);
};

// Polite and filler words that don't change what is being asked. Words like "not", "without" and "to" do, so they stay.
const FILLER = new Set(("a an the please can could would will we i you me my our us need want like have get give show "
  + "new some is are of for by in on at per with and").split(" "));
const SAME_WORD: Record<string, string> = { daily: "day", weekly: "week", monthly: "month", quarterly: "quarter", yearly: "year", annual: "year" };

function singular(word: string): string {
  if (word.length > 4 && word.endsWith("ies")) return `${word.slice(0, -3)}y`;
  return word.length > 3 && word.endsWith("s") && !word.endsWith("ss") ? word.slice(0, -1) : word;
}

/**
 * The words that decide what a question means, in any order. Every one must match, so "net sales by month"
 * finds "monthly net sales" but never "net sales by quarter" or "net sales in Finland".
 */
function meaningKey(text: string): string {
  const words = text.toLowerCase().match(/[\p{L}\p{N}]+(?:-[\p{L}\p{N}]+)*/gu) ?? [];
  const kept = words.filter((w) => !FILLER.has(w))
    .map((w) => SAME_WORD[w] ?? singular(w));
  return [...new Set(kept)].sort().join(" ") || text.trim().toLowerCase();
}

/**
 * Looks through all of history for this question. Finished answers win, newest first. A question still waiting
 * on a follow-up is reopened only if there is no finished answer. Failed, interrupted and rejected ones are asked again.
 */
export function findSavedAnswer(text: string): QuestionEntry | undefined {
  const key = meaningKey(text);
  // Only the latest question: its answer is the one saved in full, so an earlier question can't get a later answer.
  const matches = entries.filter((e) => meaningKey(latestQuestion(e)) === key);
  return matches.find((e) => e.status === "completed" || e.status === "awaiting_approval")
    ?? matches.find((e) => e.status === "needs_answer");
}

/** Moves an entry to the top of the list. Its saved time stays the time of the answer. */
export function moveToTop(id: string): void {
  commit([...entries.filter((e) => e.id === id), ...entries.filter((e) => e.id !== id)]);
}

/**
 * Saves a new conversation and returns its id. It replaces an earlier single attempt at the same question, such as
 * a failed one, but never a conversation that has gone on to other questions.
 */
export function beginQuestion(text: string, presetId: string | null): string {
  const at = now();
  const id = crypto.randomUUID();
  commit([
    { id, kind: "question", created_at: at, updated_at: at, status: "running",
      request: { text, latest_question: text, preset_id: presetId, conversation_id: null },
      result: { decision: null, summary: null, report: null, scores: null, messages: [{ role: "user", content: text }], stages: {}, error: null } },
    ...entries.filter((e) => !(sameQuestion(latestQuestion(e), text) && !e.result.earlier?.length && sameQuestion(e.request.text, text))),
  ]);
  return id;
}

function updateQuestion(id: string, change: (entry: QuestionEntry) => QuestionEntry): void {
  commit(entries.map((e) => (e.id === id ? { ...change(e), updated_at: now() } : e)));
}

const emptyAnswer = { decision: null, summary: null, report: null, scores: null, stages: {}, error: null };

/** Asks another question inside an existing entry, keeping a short record of the answer it replaces. */
export function continueQuestion(id: string, text: string): void {
  updateQuestion(id, (e) => {
    const { decision, summary, report, scores, messages, earlier = [] } = e.result;
    const previous: EarlierAnswer = { question: latestQuestion(e), decision, summary, report, scores, answered_at: e.updated_at };
    return {
      ...e, status: "running",
      request: { ...e.request, latest_question: text, preset_id: null },
      result: { ...emptyAnswer, messages: [...messages, { role: "user", content: text }], earlier: [...earlier, previous] },
    };
  });
  moveToTop(id);
}

/** Clears the latest answer so its question can be asked again in the same entry. Returns that question. */
export function restartLatestQuestion(id: string): { text: string; presetId: string | null; messages: HistoryMessage[] } | null {
  const entry = getHistoryEntry(id);
  if (!entry) return null;
  const text = latestQuestion(entry);
  const all = entry.result.messages;
  let start = all.length - 1;
  while (start >= 0 && !(all[start].role === "user" && all[start].content === text)) start--;
  const messages = start >= 0 ? all.slice(0, start + 1) : [...all, { role: "user" as const, content: text }];
  updateQuestion(id, (e) => ({ ...e, status: "running", result: { ...emptyAnswer, messages, earlier: e.result.earlier } }));
  moveToTop(id);
  return { text, presetId: entry.request.preset_id, messages };
}

/** Adds what the person said next: an answer to a follow-up question, or an approval. */
export function addUserMessage(id: string, content: string): void {
  updateQuestion(id, (e) => ({
    ...e, status: "running",
    result: { ...e.result, messages: [...e.result.messages, { role: "user", content }] },
  }));
  moveToTop(id);
}

/** Folds one pipeline event into the saved result. */
export function applyEvent(id: string, event: PipelineEvent): void {
  updateQuestion(id, (e) => {
    const result = e.result;
    switch (event.type) {
      case "conversation":
        return { ...e, request: { ...e.request, conversation_id: event.id } };
      case "stage": {
        const stages = { ...result.stages, [event.stage]: event };
        if (event.stage !== "decision" || event.status !== "done") return { ...e, result: { ...result, stages } };
        const candidate = event.data?.candidate;
        return { ...e, result: { ...result, stages, decision: event.data?.decision ?? null, summary: event.summary,
          report: candidate ? { id: candidate.asset_id, name: candidate.name } : null,
          scores: candidate ? { coverage: candidate.coverage, freshness: candidate.freshness, governance: candidate.governance } : null } };
      }
      case "message": {
        const message: HistoryMessage = { role: "assistant", content: event.content };
        if (event.kind) message.kind = event.kind;
        if (event.suggestions?.length) message.suggestions = event.suggestions;
        return { ...e, result: { ...result, messages: [...result.messages, message] } };
      }
      case "error":
        return { ...e, status: "failed", result: { ...result, error: event.message } };
      case "done":
        return { ...e, status: event.state === "clarifying" ? "needs_answer"
          : event.state === "awaiting_approval" ? "awaiting_approval"
          : result.stages.approval?.status === "rejected" ? "rejected" : "completed" };
      default:
        return e;
    }
  });
}

/** Marks a question whose stream stopped without finishing, such as when the backend could not be reached. */
export function finishQuestion(id: string, error?: string): void {
  updateQuestion(id, (e) => (e.status !== "running" ? e : {
    ...e, status: error ? "failed" : "interrupted",
    result: { ...e.result, error: error ?? e.result.error },
  }));
}

// A question picked from History waits here until the Ask page is on screen and free to open it.
let pendingEntry: string | null = null;
export const OPEN_ENTRY_EVENT = "open-history-entry";

export function openHistoryEntry(id: string): void {
  pendingEntry = id;
  window.dispatchEvent(new Event(OPEN_ENTRY_EVENT));
}

export function takePendingEntry(): QuestionEntry | null {
  const entry = pendingEntry === null ? undefined : getHistoryEntry(pendingEntry);
  pendingEntry = null;
  return entry ?? null;
}
