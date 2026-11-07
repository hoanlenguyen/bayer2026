import { useEffect, useId, useState, type MouseEvent, type ReactNode } from "react";
import { bi, type Persona, type Row } from "../api/biEstate";

/* Small pieces shared by the BI Portfolio tracker and its Evidence & governance views. */

export const month = (m: string | null) => m ? new Date(m.slice(0, 7) + "-01T00:00:00Z").toLocaleDateString("en-GB", { month: "short", year: "numeric", timeZone: "UTC" }) : "Unknown";
export const when = (iso: string | null) => iso ? new Date(iso).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" }) : "Never";
export const day = (v: string | null, precision: string | null) => !v ? "Unknown"
  : precision === "day" ? new Date(v.slice(0, 10) + "T00:00:00Z").toLocaleDateString("en-GB", { dateStyle: "medium", timeZone: "UTC" }) : when(v);
export const ownerState = { active: "Active", inactive: "Owner inactive", absent: "Unassigned" } as const;

export function go(url: string, replace = false) {
  if (url === location.pathname + location.search) return;
  history[replace ? "replaceState" : "pushState"](null, "", url);
  window.dispatchEvent(new PopStateEvent("popstate"));
}
export function link(event: MouseEvent<HTMLAnchorElement>) {
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return;
  event.preventDefault();
  const to = new URL(event.currentTarget.href);
  go(to.pathname + to.search);
  window.scrollTo(0, 0);
}
export function useLoad<T>(load: (signal: AbortSignal) => Promise<T>, deps: unknown[]) {
  const [state, setState] = useState<{ data: T | null; error: string; loading: boolean }>({ data: null, error: "", loading: true });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const ctl = new AbortController();
    setState((s) => ({ ...s, error: "", loading: true }));
    load(ctl.signal).then((data) => setState({ data, error: "", loading: false }))
      .catch((e: Error) => { if (!ctl.signal.aborted) setState((s) => ({ ...s, error: e.message, loading: false })); });
    return () => ctl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, attempt]);
  return { ...state, retry: () => setAttempt((n) => n + 1), set: (data: T) => setState({ data, error: "", loading: false }) };
}
export const roleOf = (personas: Persona[], actor: string) => personas.find((p) => p.id === actor)?.role;
export function usePersonas() {
  const [personas, setPersonas] = useState<Persona[]>([]);
  useEffect(() => { bi.personas().then((p) => setPersonas(p.personas)).catch(() => undefined); }, []);
  return personas;
}
export function OwnerCell({ owner, state }: { owner: Row["owner"]; state: Row["owner_state"] }) {
  if (!owner) return <span className="text-warn">Unassigned</span>;
  return <span>{owner.name} <span className="muted mono small">{owner.id}</span>
    {state !== "active" && <span className="text-bad small"> · {ownerState[state]}</span>}
    {owner.via === "assignment" && <span className="muted small"> · assigned</span>}</span>;
}
export function Notice({ kind, children }: { kind: "error" | "info" | "ok"; children: ReactNode }) {
  return <div className={`bp-notice bp-notice-${kind}`} role={kind === "error" ? "alert" : "status"}>{children}</div>;
}
export function Card({ title, children }: { title: string; children: ReactNode }) {
  const id = useId();
  return <section className="bp-card" aria-labelledby={id}><h3 id={id}>{title}</h3>{children}</section>;
}
