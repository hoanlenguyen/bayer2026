import { useSyncExternalStore } from "react";
import { api } from "../api/client";
import type { ConversationDetail, ConversationSummary, StageEvent, StageId } from "../api/types";

/**
 * Ask history for this tab. Conversations themselves live in the backend; this tab only keeps an index of the ones it
 * started (ID, title, last update) and which one is open, in sessionStorage. So a refresh or moving around the app keeps
 * the list, and a tab opened on its own starts empty. Nothing here lists other visitors' conversations, and closing
 * the tab deletes nothing on the server. Older localStorage keys are ignored.
 */
const KEY = "analytiq.ask.session.v1";

interface SessionState { current: string | null; items: ConversationSummary[] }

function valid(value: unknown): value is SessionState {
  if (!value || typeof value !== "object") return false;
  const v = value as SessionState;
  return (v.current === null || typeof v.current === "string") && Array.isArray(v.items)
    && v.items.every((i) => i && typeof i._id === "string" && typeof i.updated_at === "string" && (i.title === null || typeof i.title === "string"));
}

function read(): SessionState {
  try {
    const parsed = JSON.parse(sessionStorage.getItem(KEY) ?? "null");
    if (valid(parsed)) return { current: parsed.items.some((i) => i._id === parsed.current) ? parsed.current : null, items: parsed.items };
  } catch { /* unavailable or invalid: start empty */ }
  return { current: null, items: [] };
}

let state = read();
const listeners = new Set<() => void>();

function commit(next: SessionState): void {
  state = next;
  try { sessionStorage.setItem(KEY, JSON.stringify(state)); } catch { /* storage full or blocked: this page keeps it in memory */ }
  listeners.forEach((l) => l());
}
const subscribe = (l: () => void) => { listeners.add(l); return () => { listeners.delete(l); }; };

/** True when this tab started (or continued) the conversation. Only these can be opened, continued or deleted here. */
export const inSession = (id: string | null | undefined): boolean => !!id && state.items.some((i) => i._id === id);

/** The server confirmed it saved an accepted message: add the conversation, or move it to the top with its original title. */
export function recordConversation(summary: ConversationSummary): void {
  const existing = state.items.find((i) => i._id === summary._id);
  const row = { _id: summary._id, title: existing?.title ?? summary.title, updated_at: summary.updated_at };
  commit({ current: summary._id, items: [row, ...state.items.filter((i) => i._id !== summary._id)] });
}

/** Most recent first, one row per conversation, every conversation this tab holds. */
export function useConversations(): ConversationSummary[] {
  return useSyncExternalStore(subscribe, () => state.items);
}

export function setCurrentConversation(id: string | null): void {
  if (id === state.current || (id !== null && !inSession(id))) return;  // only a conversation of this tab can be the open one
  commit({ ...state, current: id });
}

export const getCurrentConversation = () => state.current;

export function useCurrentConversation(): string | null {
  return useSyncExternalStore(subscribe, () => state.current);
}

/** Drop one entry the server confirmed is gone (404). Other entries and the server stay as they are. */
export function forgetConversation(id: string): void {
  if (!inSession(id)) return;
  if (pending === id) pending = null;
  commit({ current: state.current === id ? null : state.current, items: state.items.filter((i) => i._id !== id) });
}

// While an answer streams, its conversation can't be deleted: the final save would bring it back.
let answering = false;
const answerListeners = new Set<() => void>();
export function setAnswerInProgress(value: boolean): void {
  if (value === answering) return;
  answering = value;
  answerListeners.forEach((l) => l());
}

export function useAnswerInProgress(): boolean {
  return useSyncExternalStore((l) => { answerListeners.add(l); return () => { answerListeners.delete(l); }; }, () => answering);
}

// A conversation picked from the list waits here until the Ask page is free to open it, so two answers never mix.
let pending: string | null = null;
export const OPEN_CONVERSATION_EVENT = "open-conversation";

/** Open a conversation of this tab in Ask. Anything else (another tab's, a shared dashboard's source) is ignored. */
export function openConversation(id: string): void {
  if (!inSession(id)) return;
  pending = id;
  window.dispatchEvent(new Event(OPEN_CONVERSATION_EVENT));
}

export function takePendingConversation(): string | null {
  const id = pending;
  pending = null;
  return id;
}

/** Forget a queued open, so New question is never followed by a late restore. */
export function cancelPendingConversation(): void {
  pending = null;
}

export const CURRENT_REMOVED_EVENT = "current-conversation-removed";

/** Deletes a conversation of this tab for good. If it is the one on screen, the Ask page starts fresh. */
export async function removeConversation(id: string): Promise<void> {
  if (!inSession(id)) return;
  // An already missing conversation counts as deleted. Any other failure throws: the row and selection stay for a retry.
  await api.deleteConversation(id);
  const wasCurrent = state.current === id;
  forgetConversation(id);
  if (wasCurrent) window.dispatchEvent(new Event(CURRENT_REMOVED_EVENT));
}

/** The steps of the latest question. A step left running means the answer was cut off, so it is not shown as running. */
export function stagesOf(conv: ConversationDetail): Partial<Record<StageId, StageEvent>> {
  const stages: Partial<Record<StageId, StageEvent>> = {};
  for (const event of conv.runs[conv.runs.length - 1]?.events ?? []) {
    if (event.type !== "stage") continue;
    if (event.status === "running") delete stages[event.stage];
    else stages[event.stage] = event;
  }
  return stages;
}
