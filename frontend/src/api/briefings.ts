export type Team = "commercial" | "supply";
export type ViewId = "sales" | "shipments" | "otif";

export interface Evidence {
  sheet: string;
  rows: number[];
  filters: { product_id: string; market_id: string };
  fields: string[];
  records: Record<string, string | number | null>[];
}

export interface ReportHistory {
  sheet: string;
  filters: Evidence["filters"];
  unit: "€m" | "units" | "%";
  start_period: string;
  end_period: string;
  fields: string[];
  points: {
    row: number; period: string; value: number; forecast?: number;
    value_type: "actual_like_synthetic" | "forecast_like_synthetic";
  }[];
}

export interface ReportView {
  id: ViewId;
  title: string;
  report_id: string;
  report: string;
  display_mode: "chart" | "table";
  revision: number;
  kpi_id: string;
  unit: "€m" | "units" | "%";
  current: number;
  previous: number;
  forecast: number | null;
  change_pct: number | null;
  change_pp: number | null;
  forecast_variance_pct: number | null;
  evidence: Evidence;
  history?: ReportHistory;
}

export interface Snapshot {
  team: Team;
  product: string;
  market: string;
  period: string;
  previous_period: string;
  version: string;
  synthetic: boolean;
  views: ReportView[];
  selected_view_ids: ViewId[];
  scope_view_id: ViewId | null;
  route: { source: string; mode: string; evidence: Evidence } | null;
}

export interface FollowUp {
  _id: string;
  title: string;
  owner: string;
  owner_id: string;
  due_date: string;
  status: string;
  outcome?: string | null;
  created_by: string;
  created_by_id: string;
  history: { at: string; by: string; by_id?: string; change: string; to?: string; note?: string }[];
  allowed: string[];
  briefing_snapshot: Snapshot;
}

export interface Briefing extends Omit<Snapshot, "scope_view_id"> {
  /** The market shown, one of `markets`: the newest Ask dashboard's markets, or Germany when there is none. */
  market_id: string;
  markets: { id: string; name: string }[];
  /** The newest dashboard built in Ask that set this scope, or null for the default Nubeqa in Germany. */
  scope_source: { id: string; title: string; url: string; created_at?: string } | null;
  /** Two or more markets: each market's monthly history, drawn side by side. Empty for one market. */
  market_trends: { market_id: string; market: string;
    views: { id: ViewId; title: string; unit: ReportView["unit"]; display_mode: ReportView["display_mode"]; points: ReportHistory["points"] }[] }[];
  views: (ReportView & { action: FollowUp | null })[];
  suggested_action: string;
  action: FollowUp | null;
  recent_actions: FollowUp[];
  actor: { id: string; name: string; role: string };
  owners: { id: string; name: string; role: string }[];
  storage_mode: "memory" | "mongodb";
}

export async function briefingRequest<T>(team: Team, path = "", method = "GET", data?: object): Promise<T> {
  return request<T>(`/api/briefings/${team}${path}`, method, data);
}

export function completeAction(team: Team, id: string, outcome: string) {
  return briefingRequest<FollowUp>(team, `/actions/${encodeURIComponent(id)}`, "PATCH", { status: "done", outcome });
}

async function request<T>(path: string, method: string, data?: object): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: data && { "Content-Type": "application/json" },
    body: data && JSON.stringify(data),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    const detail = typeof error.detail === "string" ? error.detail : `The request failed (${response.status}). Please try again.`;
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}
