import { readHandoff } from "../api/handoff";

/* The build hand-off may start the destination's one canonical read early, once the server confirmed the dashboard ID.
   The saved-dashboard page takes that same pending or finished read instead of starting another. A retry on the page
   always reads again. Keyed by the exact dashboard path. A taken read stays available for a few seconds, so a
   development Strict Mode remount takes the same read instead of starting a second one, then it is dropped. */
const reads = new Map<string, Promise<unknown>>();

export const dashboardPath = (id: string) => `/api/dashboards/${encodeURIComponent(id)}`;

export function prefetchDashboard(id: string): void {
  const path = dashboardPath(id);
  if (reads.has(path)) return;
  const read = readHandoff(path);
  read.catch(() => undefined);  // a failed early read becomes the page's opening error, not an unhandled rejection
  reads.set(path, read);
}

export function takePrefetched<T>(path: string): Promise<T> | undefined {
  const read = reads.get(path);
  if (read) window.setTimeout(() => { if (reads.get(path) === read) reads.delete(path); }, 5000);
  return read as Promise<T> | undefined;
}
