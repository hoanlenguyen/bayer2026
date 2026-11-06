export type StageId =
  | "intent" | "discovery" | "governance" | "decision" | "actions" | "deliver"
  | "evidence" | "spec" | "approval" | "render" | "register";

export type StageStatus = "pending" | "running" | "waiting" | "done" | "rejected";
// extend and create come from the backend before the Bayer data pack; the rest from the data pack version.
export type DecisionType = "reuse" | "repair" | "consolidate" | "migrate" | "new_build" | "extend" | "create" | "not_feasible";

export interface Preset {
  id: string;
  department: string;
  title: string;
  prompt: string;
  decision: string;
  measures: string[];
  dimensions: string[];
  grain?: string;
}

export interface ActionProposal {
  key: string;
  kind: "business" | "maintenance";
  title: string;
  reason: string;
  owner: string;
  due_date: string;
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
  platform?: string;
  scope_note?: string;
  coverage: number;
  freshness: number;
  governance: number;
  measures_found: string[];
  measures_missing: string[];
  dimensions_found?: string[];
  dimensions_missing?: string[];
  grain_supported?: boolean;
  gates_failed?: string[];
  gates_pass: boolean;
  checks: { id: string; label: string; passed: boolean; weight: number }[];
}
