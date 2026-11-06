import type { Action, ActionSummary, CatalogMeta, Health, PipelineEvent, Preset } from "./types";

/**
 * Backend address. Empty in development: Vite proxies /api to localhost:8000.
 * For a deployed backend (for example the Docker Hub image on a host), build with
 *   VITE_API_BASE=https://your-backend.example.com npm run build
 */
export const API_BASE = (import.meta.env?.VITE_API_BASE ?? "").replace(/\/$/, "");
export const apiUrl = (path: string) => `${API_BASE}${path}`;

export interface DemoActor { id: string; name: string; role: string; can_review: boolean; demo: true }
type Session = { token: string; actor: DemoActor };
let session: Session | null = null;
let pendingSession: Promise<Session> | null = null;
export async function selectActor(id: string): Promise<Session> {
  const response = await fetch(apiUrl("/api/session"), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ actor_id: id }) });
  const result = await response.json();
  if (!response.ok) throw new Error(result.detail ?? "Unable to start demo session");
  session = result;
  localStorage.setItem("bayer-demo-actor", result.actor.id);
  window.dispatchEvent(new CustomEvent("demo-actor", { detail: result.actor }));
  return result;
}
export async function ensureSession(): Promise<Session> {
  if (session) return session;
  if (!pendingSession) pendingSession = selectActor(localStorage.getItem("bayer-demo-actor") ?? "OWN-008").finally(() => { pendingSession = null; });
  return pendingSession;
}
async function authenticated(path: string, init: RequestInit = {}): Promise<Response> {
  const current = await ensureSession();
  const response = await fetch(apiUrl(path), { ...init, headers: { ...init.headers, Authorization: `Bearer ${current.token}` } });
  if (response.status === 401) session = null;
  return response;
}

export async function downloadArtifact(path: string): Promise<void> {
  const response = await authenticated(path);
  if (!response.ok) throw new Error((await response.json()).detail ?? "Download failed");
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url; link.download = response.headers.get("Content-Disposition")?.match(/filename="([^"]+)"/)?.[1] ?? "Bayer-validation.zip";
  link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export async function getJSON<T = any>(path: string): Promise<T> {
  const res = path === "/api/health" || path === "/api/session" ? await fetch(apiUrl(path)) : await authenticated(path);
  if (!res.ok) throw new Error(`${path} returned ${res.status}`);
  return res.json() as Promise<T>;
}

async function sendJSON<T>(method: string, path: string, body: unknown): Promise<T> {
  const res = await authenticated(path, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error((data as { detail?: string }).detail ?? `${path} returned ${res.status}`);
  return data as T;
}

export const api = {
  health: () => getJSON<Health>("/api/health"),
  actions: () => getJSON<{ items: Action[]; summary: ActionSummary }>("/api/actions"),
  createAction: (body: Record<string, unknown>) => sendJSON<Action>("POST", "/api/actions", body),
  updateAction: (id: string, body: Record<string, unknown>) => sendJSON<Action>("PATCH", `/api/actions/${id}`, body),
  presets: () => getJSON<Preset[]>("/api/presets"),
  catalog: () => getJSON<CatalogMeta>("/api/catalog"),
};

/** POST a JSON body and read the Server-Sent Events stream it returns. */
export async function streamPost(path: string, body: unknown, onEvent: (e: PipelineEvent) => void): Promise<void> {
  const res = await authenticated(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok || !res.body) {
    const detail = await res.text().catch(() => "");
    throw new Error(`The server returned ${res.status}. ${detail}`.trim());
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let cut: number;
    while ((cut = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);
      const data = block.split("\n").filter((l) => l.startsWith("data: ")).map((l) => l.slice(6)).join("\n");
      if (data) onEvent(JSON.parse(data) as PipelineEvent);
    }
  }
}
