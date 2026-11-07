import { useEffect, useState, useSyncExternalStore } from "react";
import { api } from "../api/client";
import type { ConversationDetail, ConversationSummary, StageEvent, StageId } from "../api/types";

/**
 * Chat history. Conversations live in the backend (MongoDB), so reopening one continues it with its context,
 * from any browser. This browser only remembers which conversation was open.
 */
const CURRENT_KEY = "am.chat.current";
try {
  // The earlier browser-only history: it stays deleted.
  localStorage.removeItem("analytics-manager.history");
  localStorage.removeItem("analytics-manager.history.v2");
} catch {
  // storage is blocked: nothing was saved there either
}

function readCurrent(): string | null {
  try { return localStorage.getItem(CURRENT_KEY); } catch { return null; }
}

let current = readCurrent();
const currentListeners = new Set<() => void>();

export function setCurrentConversation(id: string | null): void {
  if (id === current) return;
  current = id;
  try {
    if (id) localStorage.setItem(CURRENT_KEY, id);
    else localStorage.removeItem(CURRENT_KEY);
  } catch { /* it only lasts this visit */ }
  currentListeners.forEach((l) => l());
}

export const getCurrentConversation = () => current;

export function useCurrentConversation(): string | null {
  return useSyncExternalStore((l) => { currentListeners.add(l); return () => currentListeners.delete(l); }, () => current);
}

// While an answer streams, its conversation can't be deleted: the final save would bring it back.
let answering = false;
export function setAnswerInProgress(value: boolean): void {
  if (value === answering) return;
  answering = value;
  currentListeners.forEach((l) => l());
}

export function useAnswerInProgress(): boolean {
  return useSyncExternalStore((l) => { currentListeners.add(l); return () => currentListeners.delete(l); }, () => answering);
}

const CHANGED_EVENT = "conversations-changed";
export const conversationsChanged = () => window.dispatchEvent(new Event(CHANGED_EVENT));

/** Most recent first. Refreshes whenever a conversation is created or finishes. */
export function useConversations(): ConversationSummary[] {
  const [items, setItems] = useState<ConversationSummary[]>([]);
  useEffect(() => {
    let alive = true;
    const load = () => { api.conversations().then((data) => { if (alive) setItems(data); }).catch(() => undefined); };
    load();
    window.addEventListener(CHANGED_EVENT, load);
    return () => { alive = false; window.removeEventListener(CHANGED_EVENT, load); };
  }, []);
  return items;
}

// A conversation picked from the list waits here until the Ask page is free to open it, so two answers never mix.
let pending: string | null = null;
export const OPEN_CONVERSATION_EVENT = "open-conversation";

export function openConversation(id: string): void {
  pending = id;
  window.dispatchEvent(new Event(OPEN_CONVERSATION_EVENT));
}

export function takePendingConversation(): string | null {
  const id = pending;
  pending = null;
  return id;
}

export const CURRENT_REMOVED_EVENT = "current-conversation-removed";

/** Deletes a conversation for good. If it is the one on screen, the Ask page starts fresh. */
export async function removeConversation(id: string): Promise<void> {
  await api.deleteConversation(id);
  if (pending === id) pending = null;
  if (current === id) {
    setCurrentConversation(null);
    window.dispatchEvent(new Event(CURRENT_REMOVED_EVENT));
  }
  conversationsChanged();
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
