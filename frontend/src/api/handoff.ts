import type { Candidate, DecisionType } from "./types";

export interface WorkbookRef {
  sheet: string;
  row: number;
  id: string;
  detail: string;
}

export interface HandoffPreview {
  month: string;
  previous_month: string | null;
  by: string;
  columns: { id: string; name: string; unit: string }[];
  rows: { label: string; values: Record<string, number>; previous: Record<string, number> }[];
  not_previewed: string[];
  source: string;
  description: string;
  fields: string[];
  source_rows: number[];
}

export interface MetricSeries {
  source: string;
  product: string;
  market: string;
  display_mode: "chart" | "table";
  columns: { id: string; name: string; unit: string; field: string }[];
  points: { period: string; row: number; value_type: string; values: Record<string, number> }[];
}

export interface AssignedWork {
  _id: string;
  title: string;
  owner: string;
  owner_id: string;
  due_date: string;
  status: string;
  outcome?: string;
  created_by?: string;
  created_by_id?: string;
}

export interface DecisionHandoff {
  conversation_id: string;
  run_id: string;
  question: string;
  verdict: DecisionType;
  handoff_verdict?: DecisionType;
  current_review?: { reason: string; scope_evidence: Candidate["scope_evidence"] | null } | null;
  reason: string;
  action_title: string;
  plan_steps: string[];
  intent: {
    measures: string[]; dimensions: string[]; filters: Record<string, string[]>; grain: string | null;
    unmatched_terms?: string[]; other_markets?: string[]; scope_global?: boolean; migration?: boolean;
  };
  candidate: Candidate | null;
  candidates: Candidate[];
  target_model: { id: string; name: string } | null;
  evidence: { stage: string; summary: string; sheets: string[]; findings: string[];
    data?: { assets?: { id: string; name: string; recommendation: string; reason: string }[] } }[];
  source_refs: WorkbookRef[];
  preview: HandoffPreview | null;
  metric_series?: MetricSeries | null;
  employee_report: { report_id: string; view_id: string; url: string; label: string; title?: string; owner?: string; revision?: number } | null;
  estate_assessment?: { decision: string; reason: string } | null;
  owners: { id: string; name: string; role: string }[];
  suggested_owner_id: string | null;
  actor: { id: string; name: string; role: string };
  storage_mode: string;
  action: AssignedWork | null;
  related_actions: AssignedWork[];
  covering_actions?: AssignedWork[];
}

export function handoffPath(conversationId: string, runId: string) {
  return `/api/conversations/${encodeURIComponent(conversationId)}/runs/${encodeURIComponent(runId)}/handoff`;
}

export async function readHandoff<T>(path: string, method = "GET", body?: object): Promise<T> {
  const response = await fetch(path, {
    method, headers: body && { "Content-Type": "application/json" }, body: body && JSON.stringify(body),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(typeof data.detail === "string" ? data.detail : `The request failed (${response.status}). Try again.`);
  }
  return response.json() as Promise<T>;
}
