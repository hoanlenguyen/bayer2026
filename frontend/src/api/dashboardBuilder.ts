export interface BuildPeriod { start: string; end: string }
export type BuildAnswer = string | string[] | BuildPeriod;

export interface DesignState {
  status: "blocked" | "clarifying" | "ready" | "built";
  version: number;
  verdict: string;
  request: string;
  requirements: Record<string, BuildAnswer>;
  question: {
    key: string; prompt: string; kind: "text" | "single" | "multi" | "period";
    options: { value: string; label: string }[]; min_period?: string; max_period?: string;
  } | null;
  reason: string | null;
  review_token?: string;
  reused?: boolean;
  reuse_url?: string | null;
  dashboard_id: string | null;
  summary: string[];
  storage_mode: string;
}

export interface DashboardObservation {
  period: string;
  values: Record<string, number>;
  source_rows: number[];
  value_types: string[];
}

export interface SourceRecord extends Record<string, string | number> { row: number; product_id: string; market_id: string; month: string; value_type: string }

export interface SavedDashboard {
  id: string;
  title: string;
  created_at: string;
  storage_mode?: string;
  conversation_id: string;
  run_id: string;
  request: string;
  decision_goal: string;
  period: BuildPeriod;
  scope: { products: string[]; markets: string[] };
  dimensions: string[];
  columns: { id: string; name: string; unit: string; field: string; kpi_id: string; aggregation: string; lower_is_better: boolean }[];
  groups: { label: string; points: DashboardObservation[] }[];
  omitted_measures: string[];
  requested_measures: string[];
  source: string;
  source_records: SourceRecord[];
  synthetic: boolean;
}

export function builderPath(conversationId: string, runId: string) {
  return `/api/conversations/${encodeURIComponent(conversationId)}/runs/${encodeURIComponent(runId)}/dashboard`;
}

export const dashboardUrl = (id: string) => `/dashboards/${encodeURIComponent(id)}`;
export const workbookViewUrl = (conversationId: string, runId: string) =>
  `/workbook-view/${encodeURIComponent(conversationId)}/${encodeURIComponent(runId)}`;
