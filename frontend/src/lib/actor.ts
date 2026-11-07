import { useSyncExternalStore } from "react";

/** The demo identity this browser acts as in the BI Portfolio. The server decides what that identity may do. */
const KEY = "analytiq.actor";
const listeners = new Set<() => void>();
let current = (() => { try { return localStorage.getItem(KEY) || ""; } catch { return ""; } })();

export function getActor() { return current; }
export function setActor(id: string) {
  current = id;
  try { if (id) localStorage.setItem(KEY, id); else localStorage.removeItem(KEY); } catch { /* lasts this visit only */ }
  listeners.forEach((l) => l());
}
export function useActor() {
  return useSyncExternalStore((l) => { listeners.add(l); return () => listeners.delete(l); }, getActor);
}
export function actorHeaders(): Record<string, string> {
  return current ? { "X-AnalytIQ-Actor": current } : {};
}
