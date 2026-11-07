import type { StageEvent, StageId } from "../../api/types";

interface Triage {
  /** Not set while the request is being understood; "triaged" from the decision on. */
  status: "new" | "triaged" | null;
  request_id?: string | null;
  request_store?: "atlas" | "memory" | null;
  urgency: { value: "normal" | "high" | "urgent"; source: "stated" | "inferred" | "model" | "default"; evidence: string | null };
  similar: {
    duplicates: { text: string; asked: number; request_ids: string[]; similarity: number }[];
    similar: { text: string; asked: number; request_ids: string[]; similarity: number }[];
    duplicate_count: number;
    embedder: string;
    search: string;
  } | null;
}

const URGENCY_TONE = { urgent: "bad", high: "warn", normal: "muted" } as const;

function urgencySource(u: Triage["urgency"]): string {
  if (u.source === "stated") return "you said so";
  if (u.source === "inferred") return `from “${u.evidence}”`;
  if (u.source === "model") return "estimated from your wording";
  return "no deadline mentioned";
}

function ids(list: string[], total: number): string {
  const shown = list.slice(0, 3).join(", ");
  return total > 3 ? `${shown} and ${total - 3} more` : shown;
}

/** Latest triage for the request: the decision stage marks it triaged, the intent stage tags it new. */
export function currentTriage(stages: Partial<Record<StageId, StageEvent>>): Triage | undefined {
  return stages.decision?.data?.triage ?? stages.intent?.data?.triage;
}

/** Status and urgency tags. `only` limits which tag shows; `compact` drops the reason, for the flow panel. */
export function TriageTags({ triage: t, compact = false, only }: { triage: Triage; compact?: boolean; only?: "status" | "urgency" }) {
  const showStatus = !!t.status && only !== "urgency";
  const showUrgency = only !== "status";
  if (!showStatus && !showUrgency) return null;
  return (
    <div className="triage-tags" aria-label="Request tags">
      {showStatus && (
        <span className={`triage-tag tag-${t.status}`} title="Set once the request is understood and a decision is made">
          {t.status === "triaged" ? "Triaged" : "New"}
        </span>
      )}
      {showUrgency && (
        <span className={`triage-tag tone-${URGENCY_TONE[t.urgency.value]}`} title={compact ? urgencySource(t.urgency) : undefined}>
          {t.urgency.value[0].toUpperCase() + t.urgency.value.slice(1)} urgency
          {!compact && <span className="triage-why"> · {urgencySource(t.urgency)}</span>}
        </span>
      )}
    </div>
  );
}

/** Earlier requests that ask the same thing. Only there when it has one to show; the tags live in the flow panel. */
export function TriageStrip({ stages }: { stages: Partial<Record<StageId, StageEvent>> }) {
  const t = currentTriage(stages);
  const dup = t?.similar?.duplicates ?? [];
  const sim = t?.similar?.similar ?? [];
  if (dup.length === 0 && sim.length === 0) return null;
  return (
    <section className="triage" aria-label="Earlier requests">
      {dup.length > 0 && (
        <p className="triage-note">
          <strong>Asked before:</strong> the same request is already in the queue {t!.similar!.duplicate_count} times
          ({ids(dup[0].request_ids, dup[0].asked)}). Join it instead of adding another.
        </p>
      )}
      {dup.length === 0 && sim.length > 0 && (
        <p className="triage-note">
          <strong>Similar request:</strong> “{sim[0].text}” was asked {sim[0].asked} times ({ids(sim[0].request_ids, sim[0].asked)}).
        </p>
      )}
    </section>
  );
}
