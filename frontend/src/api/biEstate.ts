import { actorHeaders } from "../lib/actor";

export type IssueCode = "needs_owner" | "refresh" | "definition" | "scope" | "consolidation" | "retirement" | "chronology" | "signal";
export type Origin = "workbook" | "app_report" | "generated";
export interface Person { id: string; name: string; role?: string; status?: string; evidence?: string;
  via?: "imported" | "assignment"; assigned_at?: string; assigned_by?: string; reason?: string }
export interface Dated { value: string | null; precision: "day" | "timestamp" | null; source: string }
export interface Creator { name: string | null; id?: string; source: string; recorded: boolean }
export interface Row {
  id: string; title: string; original_title: string; alias: boolean; origin: Origin; type: string; platform: string;
  product: string | null; market: string | null; market_name: string | null; owner: Person | null;
  owner_state: "active" | "inactive" | "absent"; creator: Creator; created: Dated; lifecycle: string; issues: IssueCode[];
  finding: string; app_opens: { count: number; last_at: string | null }; case_ids: string[]; data_through: string | null;
  last_view_month: string | null; last_view_count: number | null; refresh: string; model_id: string | null; pair_ids: string[];
}
export interface EstatePage {
  rows: Row[]; total: number; matching: number; page: number; size: number; pages: number; sort: string; direction: "asc" | "desc";
  counts: Record<IssueCode, { assets: number; pairs?: number }>; pairs_in_view: number;
  issue_labels: Record<IssueCode, string>; origin_labels: Record<Origin, string>;
  facets: { platform: string[]; lifecycle: string[]; product: string[]; market: string[] };
  sources: { origins: Record<Origin, number>; workbook: { file: string; sha256: string; observation_window: string[] }; note: string; store: string; as_of: string };
}
export interface Kpi { id: string; name: string | null; family?: string; unit?: string; definition_status?: string; approval_status?: string;
  approved_canonical?: boolean; steward?: Person | null; evidence?: string; binding?: string | null; usage_role?: string | null; known: boolean }
export interface Edge { id: string; title: string | null; edge_type: string; relationship: string; evidence: string; class: string }
export interface Scope { product: string; geography: string; report_region: string | null; model_product: string | null; model_region: string | null;
  mismatch: boolean; rule: Rule }
export interface Rule { id: string; version: number; text: string }
export interface Model { id: string; name: string | null; product: string | null; region: string | null; refresh_status: string | null;
  cadence: string | null; endorsement: string | null; row: number | null }
export interface Usage { window: string[]; months: number; views: number | null; exports?: number; subscriptions?: number;
  unique_users_monthly_sum?: number; last_view_month: string | null; last_view_row?: number | null; last_view_count?: number | null;
  last_activity_month?: string | null; source: string }
export interface Side { id: string; title: string; original_title: string; platform: string; type: string; product: string | null; market: string | null;
  market_name: string | null; owner: Person | null; owner_state: Row["owner_state"]; lifecycle: string; model: Model | null; scope: Scope | null;
  kpi_ids: string[]; usage: Usage; app_opens: Row["app_opens"]; downstream: Edge[]; upstream: Edge[]; evidence: (string | null)[] }
export interface Pair { id: string; a: Side; b: Side; shared: Kpi[]; shared_approved_ids: string[]; only_a: Kpi[]; only_b: Kpi[];
  same_scope: boolean; same_model: boolean; same_owner: boolean; qualifies: boolean; rule: Rule; blockers: string[]; question: string; note: string;
  cases?: Case[] }
export interface CaseResponse { actor_id: string; actor_name: string; at: string; proposal: string; purpose: string; consumers: string;
  essential_kpis: string[]; blockers: string; asset_id: string }
export interface CaseEventRecord { seq: number; kind: "opened" | "response" | "decision"; actor_name: string; at: string; [key: string]: unknown }
export interface Case { id: string; pair_key: string; assets: string[]; generation: number;
  status: "awaiting_responses" | "ready_for_decision" | "ownership_needed" | "closed"; status_label: string; question: string; note: string;
  due: string | null; coordinator: string; created_at: string; owners: { asset_id: string; owner: Person | null; owner_state: string }[];
  same_owner: boolean; responses: Record<string, CaseResponse>; seq: number; needs_reassessment: boolean;
  decision: (CaseEventRecord & { outcome: string; outcome_label: string; reason: string; owner_disagreement: boolean; execution: string;
    plan: null | { survivor: string; affected: string; validation: string; accountable_owner: { id: string; name: string }; checkpoint: string } }) | null;
  events: CaseEventRecord[]; reopened_from: string | null; changed_since_previous: string[] | null; brief: string }
export interface Detail extends Omit<Row, "refresh"> {
  workspace: { id: string | null; name: string | null }; endorsement: string | null; modified: Dated; imported_owner: Person | null;
  model: Model | null; refresh: { status: string; cadence: string | null; last_success: string | null; overdue: string; note: string };
  usage: Usage; scope: Scope | null; kpis: Kpi[]; variant_kpi_ids: string[]; nonstandard_kpi_ids: string[];
  usage_series: { month: string; views: number; unique_users: number; exports: number; subscriptions: number; row: number }[];
  upstream: Edge[]; downstream: Edge[]; siblings_on_model: { count: number; ids: string[]; class: string } | null;
  signals: { id: string; code: string; severity: string; status: string; evidence: string }[];
  quality: { id: string; record: string; field: string; severity: string; impact: string; evidence: string }[];
  sources: (string | null)[]; downstream_coverage: string; pairs: Pair[]; opens: { at: string; source: string; kind: string; view_id: string }[];
  owner_history: { seq: number; owner_id: string; owner_name: string; reason: string; actor_name: string; at: string }[];
  cases: Case[]; links: { dashboard: string | null; register: string | null; explorer: string | null }; teams: string[];
  decision_goal?: string; conversation_id?: string;
}
export interface Persona { id: string; name: string; role: "bi_steward" | "employee" | "owner" | "governance_reviewer" | "auditor"; label: string }

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { ...init, headers: { "Content-Type": "application/json", ...actorHeaders(), ...(init?.headers || {}) } });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(typeof body.detail === "string" ? body.detail : `The request failed (${res.status}).`);
  }
  return res.json();
}

export const bi = {
  list: (params: URLSearchParams, signal?: AbortSignal) => call<EstatePage>(`/api/bi-estate?${params}`, { signal }),
  detail: (id: string, signal?: AbortSignal) => call<Detail>(`/api/bi-estate/${encodeURIComponent(id)}`, { signal }),
  pair: (a: string, b: string, signal?: AbortSignal) => call<Pair>(`/api/bi-estate/pairs/${encodeURIComponent(a)}/${encodeURIComponent(b)}`, { signal }),
  personas: () => call<{ personas: Persona[]; note: string }>("/api/bi-identity"),
  assignOwner: (id: string, body: { owner_id: string; reason: string; expected_seq: number }) =>
    call<Detail>(`/api/bi-estate/${encodeURIComponent(id)}/owner`, { method: "POST", body: JSON.stringify(body) }),
  startReview: (body: { asset_a: string; asset_b: string; question: string; note: string; due: string | null }) =>
    call<Case>("/api/bi-reviews", { method: "POST", body: JSON.stringify(body) }),
  caseEvent: (id: string, body: Record<string, unknown>) =>
    call<Case>(`/api/bi-reviews/${encodeURIComponent(id)}/events`, { method: "POST", body: JSON.stringify(body) }),
  recordOpen: (id: string, viewId: string, source: "dashboard" | "workbook_view" = "dashboard") =>
    call<{ recorded: boolean }>(`/api/bi-estate/${encodeURIComponent(id)}/opens`, { method: "POST", body: JSON.stringify({ view_id: viewId, source }) }),
};
