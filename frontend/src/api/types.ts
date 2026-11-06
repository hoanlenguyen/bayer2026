export type StageId =
  | "intent" | "discovery" | "governance" | "decision" | "actions" | "deliver"
  | "evidence" | "spec" | "approval" | "render" | "register";

export type StageStatus = "pending" | "running" | "waiting" | "done" | "rejected";
export type DecisionType = "reuse" | "extend" | "create" | "not_feasible";

export interface Preset {
  id: string;
  department: string;
  title: string;
  prompt: string;
  decision: string;
  measures: string[];
  dimensions: string[];
  grain: string;
}

export interface StageEvent {
  type: "stage";
  stage: StageId;
  title: string;
  status: StageStatus;
  summary: string;
  data: any;
  ts: string;
}

export interface MessageEvent {
  type: "message";
  role: "assistant";
  content: string;
  kind?: "question" | "result" | "approval";
  suggestions?: string[];
  decision?: DecisionType;
  ts: string;
}

export type PipelineEvent =
  | { type: "conversation"; id: string; provider: string; store: string }
  | { type: "user_message"; content: string; ts: string }
  | StageEvent
  | MessageEvent
  | { type: "done"; state: "idle" | "clarifying" | "awaiting_approval"; ts: string }
  | { type: "error"; message: string };

export interface Health {
  ok: boolean;
  provider: "mock" | "openai";
  store: "memory" | "mongodb";
  models: { reasoning: string; fast: string } | null;
}

export interface CatalogMeta {
  measures: Record<string, { name: string; unit: string; definition: string }>;
  dimensions: Record<string, { name: string }>;
}

export interface Candidate {
  asset_id: string;
  name: string;
  coverage: number;
  freshness: number;
  governance: number;
  measures_found: string[];
  measures_missing: string[];
  dimensions_found: string[];
  dimensions_missing: string[];
  grain_supported: boolean;
  gates_failed: string[];
  gates_pass: boolean;
  checks: { id: string; label: string; passed: boolean; weight: number }[];
}

export type ActionStatus = "open" | "in_progress" | "blocked" | "done" | "verified" | "dismissed";
export type ActionKind = "business" | "maintenance";

export interface VerifyTarget {
  metric_id: string | null;
  metric_name: string;
  direction: "increase" | "decrease";
  result: "improved" | "not_improved" | "confirmed" | null;
  note: string;
  checked_at: string | null;
  checked_by: string | null;
}

export interface ActionProposal {
  key: string;
  kind: ActionKind;
  title: string;
  reason: string;
  owner: string;
  due_date: string;
  asset_id: string | null;
  asset_name: string | null;
  verify: VerifyTarget | null;
  existing_action_id: string | null;
}

export interface Action {
  _id: string;
  key: string | null;
  kind: ActionKind;
  title: string;
  reason: string;
  owner: string;
  due_date: string | null;
  status: ActionStatus;
  asset_id: string | null;
  asset_name: string | null;
  conversation_id: string | null;
  blocker: string;
  outcome: string;
  verify: VerifyTarget | null;
  created_at: string;
  updated_at: string;
  created_by: string;
  sample: boolean;
  overdue: boolean;
  allowed: ActionStatus[];
  history: { at: string; by: string; change: string; from?: string | null; to?: string | null; note?: string | null }[];
}

export interface ActionSummary {
  open: number; in_progress: number; blocked: number; done: number; verified: number; dismissed: number;
  overdue: number; awaiting_verification: number; active: number;
}
