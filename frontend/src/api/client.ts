import type { Action, ActionSummary, CatalogMeta, Health, PipelineEvent, Preset } from "./types";

export async function getJSON<T = any>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${path} returned ${res.status}`);
  return res.json() as Promise<T>;
}

async function sendJSON<T>(method: string, path: string, body: unknown): Promise<T> {
  const res = await fetch(path, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
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
  const res = await fetch(path, {
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
