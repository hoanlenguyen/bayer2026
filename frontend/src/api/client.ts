import type { CatalogMeta, ConversationDetail, Health, PipelineEvent, Preset } from "./types";

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) throw Object.assign(new Error(`${path} returned ${res.status}`), { status: res.status });
  return res.json() as Promise<T>;
}

async function deleteJSON(path: string): Promise<void> {
  const res = await fetch(path, { method: "DELETE" });
  if (!res.ok && res.status !== 404) throw new Error(`${path} returned ${res.status}`); // 404: already gone
}

export const api = {
  health: () => getJSON<Health>("/api/health"),
  presets: () => getJSON<Preset[]>("/api/presets"),
  catalog: () => getJSON<CatalogMeta>("/api/catalog"),
  deleteConversation: (id: string) => deleteJSON(`/api/conversations/${encodeURIComponent(id)}`),
  conversation: (id: string) => getJSON<ConversationDetail>(`/api/conversations/${encodeURIComponent(id)}`),
};

/** Read a Server-Sent Events body and hand each event's JSON data to `onEvent`, in order, as frames arrive. Handles
 *  frames split across chunks, several frames in one chunk, CRLF line ends, comments and multi-line data. Unreadable
 *  data throws, so a caller never treats a damaged stream as complete. */
export async function readEvents<E>(body: ReadableStream<Uint8Array>, onEvent: (e: E) => void): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const flush = (block: string) => {
    const data = block.split("\n").filter((l) => l.startsWith("data:")).map((l) => l.slice(l.startsWith("data: ") ? 6 : 5)).join("\n");
    if (!data) return;
    let parsed: E;
    try { parsed = JSON.parse(data) as E; } catch { throw new Error("The server's answer could not be read."); }
    onEvent(parsed);
  };
  for (;;) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done }).replace(/\r\n?/g, "\n");
    let cut: number;
    while ((cut = buffer.indexOf("\n\n")) >= 0) {
      flush(buffer.slice(0, cut));
      buffer = buffer.slice(cut + 2);
    }
    if (done) break;
  }
  if (buffer.trim()) flush(buffer);  // a last frame without its blank line
}

/** POST a JSON body and read the Server-Sent Events stream it returns. */
export async function streamPost<E = PipelineEvent>(path: string, body: unknown, onEvent: (e: E) => void): Promise<void> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok || !res.body) {
    const detail = await res.text().catch(() => "");
    throw new Error(`The server returned ${res.status}. ${detail}`.trim());
  }
  await readEvents(res.body, onEvent);
}
