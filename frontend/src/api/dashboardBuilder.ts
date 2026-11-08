export interface BuildPeriod { start: string; end: string }
export type BuildAnswer = string | string[] | BuildPeriod;

/** What the dashboard holds and how it opens, computed by the server from the assembled or saved artifact. Absent on older records. */
export interface BuildReceipt {
  products: string[]; markets: string[]; period: BuildPeriod | null;
  measures: { id: string; kpi_id: string | null; name: string; unit: string }[];
  charted_measures: number; groups: number; group_labels: string[];
  months: number; first_month: string | null; last_month: string | null;
  observations: number; rows: { first: number; last: number } | null;
  actual_like: number; forecast_like: number; source: string | null; omitted_measures: string[]; arrangement: string; lead_measure?: string | null; presentation?: string | null; layout?: string | null; decision_goal?: string | null;
}

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
  receipt?: BuildReceipt;
  /** A guided example run: its fixed choices. */
  guided?: { id: string; purpose: string; period: string } | null;
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
  /** One approved month only: the months leading up to it, for the trend (as in the team briefings). Not approved figures. */
  context?: { period: BuildPeriod; groups: { label: string; points: DashboardObservation[] }[] };
  omitted_measures: string[];
  requested_measures: string[];
  source: string;
  source_records: SourceRecord[];
  synthetic: boolean;
  receipt?: BuildReceipt;
  presentation?: "market_comparison";
  lead_measure?: string;
  market_order?: string[];
  guided?: { id: string; purpose: string; period: string };
  created_by?: { name: string; source?: string };
  display_mode?: string;
}

export function builderPath(conversationId: string, runId: string) {
  return `/api/conversations/${encodeURIComponent(conversationId)}/runs/${encodeURIComponent(runId)}/dashboard`;
}

export const dashboardUrl = (id: string) => `/dashboards/${encodeURIComponent(id)}`;
export const workbookViewUrl = (conversationId: string, runId: string) =>
  `/workbook-view/${encodeURIComponent(conversationId)}/${encodeURIComponent(runId)}`;

/* The approved build, streamed. Each checkpoint is announced before its work and completed with that work's facts;
   the stream ends with one build_result (the committed state) or build_error. */
export type BuildStepId = "brief" | "source" | "calculate" | "save";
export interface BuildStageEvent { type: "build_stage"; phase: BuildStepId; status: "running" | "complete"; facts?: Record<string, unknown> }
export interface BuildResultEvent { type: "build_result"; state: DesignState; replayed: boolean }
export interface BuildErrorEvent { type: "build_error"; kind: "review" | "retry" | "reload"; status: number; message: string }
export type BuildEvent = BuildStageEvent | BuildResultEvent | BuildErrorEvent;
