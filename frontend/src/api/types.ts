export type StageId =
  | "intent" | "kpis" | "discovery" | "lineage" | "governance" | "migration" | "decision" | "actions" | "deliver";

export type StageStatus = "pending" | "running" | "waiting" | "done" | "rejected";
// extend and create come from the backend before the SinceAI data pack; the rest from the data pack version.
export type DecisionType = "reuse" | "repair" | "consolidate" | "migrate" | "new_build" | "retire" | "review" | "extend" | "create" | "not_feasible";

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
  kind?: "question" | "result" | "retry";
  suggestions?: string[];
  choices?: GuidedChoice[];
  /** the verified scope a guided question was asked for */
  facts?: GuidedFacts;
  decision?: DecisionType;
  ts: string;
}

/** Marks the start of real work on the server (not stored). The UI shows it as the turn's status. */
/** Not stored: marks work that has started inside the Understand step (message check, reading an answer, guided scope or periods). */
export interface ProcessingEvent { type: "processing"; phase: "relevance" | "intent" | "scope" | "periods" }
export interface GuidedFacts { product: string; markets: string[]; measures: string[] }

export type PipelineEvent =
  | ProcessingEvent
  | { type: "conversation"; id: string; provider: string; store: string }
  /** history: present only when the server saved this accepted message (the tab adds the conversation to its History) */
  | { type: "user_message"; content: string; ts: string; history?: ConversationSummary }
  | StageEvent
  | MessageEvent
  | { type: "done"; state: "idle" | "clarifying" | "awaiting_approval"; ts: string }
  | { type: "error"; message: string };

export interface Health {
  ok: boolean;
  provider: "mock" | "openai";
  store: "memory" | "mongodb";
  models: { reasoning: string; fast: string } | null;
  jev?: boolean;
}

export interface CatalogMeta {
  measures: Record<string, { name: string; unit: string; definition: string }>;
  dimensions: Record<string, { name: string }>;
}

export interface Candidate {
  asset_id: string;
  name: string;
  owner?: string | null;
  owner_status?: string | null;
  platform?: string;
  scope_note?: string;
  scope_evidence?: {
    conflict: boolean; reason: string | null; asset_id: string; asset_product: string | null; asset_market: string | null;
    model_id: string | null; model_product: string | null; model_region: string | null;
  };
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

export interface ConversationSummary {
  _id: string;
  title: string | null;
  updated_at: string;
}

export interface ConversationDetail extends ConversationSummary {
  state: string;
  messages: { role: "user" | "assistant"; content: string; kind?: "question" | "result" | "retry"; suggestions?: string[]; choices?: GuidedChoice[]; facts?: GuidedFacts }[];
  runs: { id: string; events: (StageEvent | { type: "user_message" | "message" | "done" })[] }[];
}

// ---- Chat simulator (POST /api/simulator/turn)
export type GateLabel = "off_topic" | "business_talk" | "needs_decision" | "needs_context" | "already_answered";
export type DecidedBy = "jev" | "llm" | "rules";

export interface TokenUsage {
  input_tokens: number;
  output_tokens: number;
  calls: number;
}

export interface SimulatorRecommendation {
  value: string;
  label: string;
  reason: string;
  rule: string;
  rules_applied: string[];
  evidence: { step: number; task: string; summary: string }[];
}

export interface SimulatorReport {
  id: string;
  name: string;
  platform: string;
  workspace: string | null;
  owner: string | null;
}

export type SimulatorEvent =
  | { type: "gate"; label: GateLabel; confidence: number | null; reason: string; decided_by: DecidedBy; model: string; ms: number; usage: TokenUsage | null; cost: number; fallback_reason: string | null; jev_on: boolean }
  | { type: "searching" }
  | { type: "reply"; kind: "answer"; text: string; usage: TokenUsage | null; answer_key?: string; decision?: string; recommendation?: SimulatorRecommendation; report?: SimulatorReport | null; stages?: StageEvent[] }
  | { type: "needs_context"; usage: TokenUsage | null }
  | { type: "already_answered"; answer_key: string; usage: TokenUsage | null }
  | { type: "done" }
  | { type: "error"; message: string };

/** One line of the chat. A and B carry what was decided about them; C carries its answer. */
export interface SimulatorMessage {
  id: number;
  speaker: "A" | "B" | "C";
  text: string;
  label?: GateLabel;
  confidence?: number | null;
  ms?: number;
  decided_by?: DecidedBy;
  usage?: TokenUsage | null;
  search_usage?: TokenUsage | null;
  cost?: number;
  searching?: boolean;
  failed?: boolean;
  kind?: "answer";
  answer_key?: string;
  decision?: string;
  recommendation?: SimulatorRecommendation;
  report?: SimulatorReport | null;
  stages?: StageEvent[];
  /** AnalytIQ only: the sentence it answered, used as the title of its steps. */
  request?: string;
}

/** An offered answer in a guided example. The backend accepts only these, by ID. */
export interface GuidedChoice { id: string; label: string; detail?: string; start?: string; end?: string; count?: number }
export interface GuidedExample { id: string; placement: "visible" | "more"; text: string; product: string; markets: string[]; measures: string[] }
export interface GuidedExamples { examples: GuidedExample[]; purpose_question: string; period_question: string }
