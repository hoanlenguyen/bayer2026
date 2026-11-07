import { actorHeaders } from "../lib/actor";
import type { Person } from "./biEstate";

export interface Source { kind: string; label?: string; file?: string; revision?: string; sheet?: string; row?: number; record_id?: string | null;
  fields?: string[]; id?: string; version?: number; text?: string; collection?: string; ref?: string; sha256?: string }
export interface Evidence {
  id: string; kind: string; label: string; value: Record<string, unknown>; source: Source; authority: string; authority_label: string;
  observed_at: string | null; observed_meaning: string | null; collected_at: string; availability: string; links: string[];
  status?: string; submitted_by?: string; finding_id?: string | null; clause_ref?: string | null; supersedes?: string | null;
  superseded_by?: string | null; reviews?: { seq: number; decision: string; note: string; actor_name: string; at: string }[]; seq?: number;
  record?: Record<string, unknown>; linked?: Evidence[]; asset?: { id: string; title: string }; permissions?: Permissions;
  assets?: { id: string; title: string }[]; asset_count?: number;
}
export interface Check { id: string; version: number; text: string }
export interface Clause { doc_id: string; doc_title: string; authority: string; authority_label: string; revision: number; version: string | null;
  effective_from: string | null; effective_to: string | null; clause_id: string; clause_title: string; text: string; source?: Source; priority?: string }
export interface ReviewState { status: string; label: string; assignee: { id: string; name: string } | null; seq: number;
  last_assessment: { id: string; judgment: string; judgment_label: string; actor_name: string; at: string; reason: string } | null;
  evidence_requested: string | null }
export interface Risk {
  id: string; asset_id: string; asset_title: string; code: string; title: string; observation: string; consequence: string; origin: string;
  origin_label: string; evidence_ids: string[]; rule_ids: string[]; checks: Check[]; source_severity: string | null; source_status: string | null;
  signal_id: string | null; next_action: string; impact: string; owner: Person | null; owner_state: string; case_ids: string[]; review: ReviewState;
}
export interface MappingView { id: string; doc_id: string; clause_id: string; asset_id: string; status: string; reason: string; proposed_by: string;
  proposed_at: string; decided_by: string | null; decided_at: string | null; decision_reason: string | null }
export interface ExceptionView { id: string; rule_ref: string; kpi_id: string | null; asset_ids: string[]; rationale: string; expires: string;
  reference: string; status: string; state: string; proposed_by: string; decided_by: string | null }
export interface Assessment {
  doc_id: string; title: string; authority: string; authority_label: string; priority: string | null; status: string; status_label: string;
  result: string | null; result_label: string | null; reason: string; risk_ids: string[]; facts: { text: string; evidence_id: string | null }[];
  clause: Clause | null; mapping: MappingView | null; exception: ExceptionView | null; subject?: string; review?: ReviewState;
}
export interface Permissions { submit_evidence: boolean; review: boolean; steward: boolean; approve: boolean; read_only: boolean }
export interface HistoryEntry { id: string; kind: string; actor_name: string; at: string; text: string; assessment?: string | null; case?: string; subject?: string }
export interface AssetGovernance {
  asset: { id: string; title: string; origin: string; type: string; platform: string; product: string | null; market: string | null;
    market_name: string | null; owner: Person | null; owner_state: string; issues: string[]; lifecycle: string };
  as_of: string; workbook: { file: string; sha: string; collected_at: string }; permissions: Permissions;
  evidence: Evidence[]; risks: Risk[]; policies: Assessment[]; not_applicable: Assessment[];
  missing_evidence: { policy?: string; risk?: string; text: string | null }[]; history: HistoryEntry[]; unavailable: string[];
  finding_map: Record<string, string[]>; mapping_tasks: MappingView[];
}
export interface IndexPage<R> { tab: string; rows: R[]; total: number; page: number; size: number; pages: number; distinct_assets: number;
  scope_assets: number; portfolio_assets: number; as_of: string; permissions: Permissions; mapping_tasks: MappingView[];
  workbook: { file: string; sha: string } }
export interface PolicyRow { id: string; title: string; authority_label: string; priority: string | null; version: string | null; revision: number | null;
  effective_from: string | null; affected: number; with_findings: number; sample: { id: string; title: string; result: string | null }[] }
export interface RiskRow { id: string; asset_id: string; asset_title: string; title: string; observation: string; origin_label: string;
  source_severity: string | null; source_status: string | null; rule_ids: string[]; review: ReviewState; owner: Person | null; owner_state: string;
  rule_priority: string | null; action_priority: string; signal_id: string | null }
export interface RiskDetail extends Risk { evidence: Evidence[]; guidance: Clause[]; assessments: Assessment[]; as_of: string;
  rule_priority: string | null; action_priority: string; history: HistoryEntry[]; permissions: Permissions;
  cases: { id: string; status_label: string; assets: string[] }[]; pair_ids: string[] }
export interface Revision { revision: number; version: string | null; effective_from: string | null; effective_to: string | null; status?: string;
  clauses: Record<string, { title: string; text: string }>; source?: Source; registered_by?: string; registered_at?: string;
  supersedes?: string | null; source_ref?: string; workbook_revision?: string }
export interface DocumentDetail { id: string; title: string; authority: string; authority_label: string; issuer: string | null; owner: string | null;
  accountable_team: string | null; priority: string | null; note: string | null; as_of: string; current: (Revision & { status: string | null }) | null;
  revisions: Revision[]; why: Assessment | null; affected: { id: string; title: string; owner: string | null; result: string | null; result_label: string | null }[];
  affected_count: number; mappings: MappingView[]; exceptions: ExceptionView[]; permissions: Permissions }
export interface AssessmentRecord { id: string; subject: string; asset: { id: string; title: string }; judgment: string; judgment_label: string;
  reason: string; actor_name: string; at: string; changes_since: string[];
  snapshot: { evidence: Evidence[]; clause: Clause | null; facts: { text: string; evidence_id?: string | null; evidence_ids?: string[] }[];
    checks: Check[]; rule_ids: string[]; owner: { id: string; name: string } | null; workbook: { file: string; sha: string }; acknowledged_changes: boolean } }
export interface PermittedSource { ref: string; doc_id: string; title: string; authority: string; issuer: string; accountable_team: string;
  owner: string; version: string; effective_from: string; status: string; clauses: Record<string, { title: string; text: string }> }

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { ...init, headers: { "Content-Type": "application/json", ...actorHeaders(), ...(init?.headers || {}) } });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw Object.assign(new Error(typeof body.detail === "string" ? body.detail : `The request failed (${res.status}).`), { status: res.status });
  }
  return res.json();
}
const G = "/api/bi-governance";
const e = encodeURIComponent;
const post = <T,>(path: string, body: unknown) => call<T>(path, { method: "POST", body: JSON.stringify(body) });

export const gov = {
  index: <R,>(params: URLSearchParams, signal?: AbortSignal) => call<IndexPage<R>>(`${G}?${params}`, { signal }),
  asset: (id: string, at?: string, signal?: AbortSignal) => call<AssetGovernance>(`${G}/assets/${e(id)}${at ? `?at=${at}` : ""}`, { signal }),
  evidence: (id: string, asset: string, signal?: AbortSignal) => call<Evidence>(`${G}/evidence/${e(id)}?asset=${e(asset)}`, { signal }),
  risk: (id: string, signal?: AbortSignal) => call<RiskDetail>(`${G}/risks/${e(id)}`, { signal }),
  document: (id: string, asset?: string | null, signal?: AbortSignal) =>
    call<DocumentDetail>(`${G}/documents/${e(id)}${asset ? `?asset=${e(asset)}` : ""}`, { signal }),
  original: (id: string, revision: number) => call<{ title: string; text: string | null; availability: string; sha256?: string }>(`${G}/documents/${e(id)}/revisions/${revision}/original`),
  assessment: (id: string, signal?: AbortSignal) => call<AssessmentRecord>(`${G}/assessments/${e(id)}`, { signal }),
  sources: () => call<{ sources: PermittedSource[] }>(`${G}/sources`),
  register: (body: Record<string, unknown>) => post<{ document: string; revision: number; created: boolean }>(`${G}/documents`, body),
  proposeMapping: (doc: string, body: { asset_id: string; clause_id: string; reason: string }) => post<MappingView>(`${G}/documents/${e(doc)}/mappings`, body),
  decideMapping: (id: string, body: { decision: "accepted" | "rejected"; reason: string }) => post<MappingView>(`${G}/mappings/${e(id)}/decision`, body),
  submitEvidence: (asset: string, body: Record<string, unknown>) => post<Evidence>(`${G}/assets/${e(asset)}/evidence`, body),
  reviewEvidence: (id: string, body: { decision: string; note: string; expected_reviews: number }) => post<Evidence>(`${G}/evidence/${e(id)}/reviews`, body),
  riskEvent: (id: string, body: Record<string, unknown>) => post<HistoryEntry>(`${G}/risks/${e(id)}/events`, body),
  clauseEvent: (doc: string, clause: string, asset: string, body: Record<string, unknown>) =>
    post<HistoryEntry>(`${G}/documents/${e(doc)}/clauses/${e(clause)}/assets/${e(asset)}/events`, body),
  proposeException: (body: Record<string, unknown>) => post<ExceptionView>(`${G}/exceptions`, body),
  decideException: (id: string, body: { decision: "accepted" | "rejected"; reason: string }) => post<ExceptionView>(`${G}/exceptions/${e(id)}/decision`, body),
};
