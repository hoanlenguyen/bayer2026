import type { StageEvent, StageId } from "../../api/types";

interface Triage {
  status: "new" | "triaged";
  urgency: { value: "normal" | "high" | "urgent"; source: "stated" | "inferred" | "default"; evidence: string | null };
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

/** Status and urgency tags. `compact` drops the reason, for the flow panel. */
export function TriageTags({ triage: t, compact = false }: { triage: Triage; compact?: boolean }) {
  return (
    <div className="triage-tags" aria-label="Request tags">
      <span className={`triage-tag tag-${t.status}`} title="New on arrival; triaged once the request is understood and decided">
        {t.status === "triaged" ? "Triaged" : "New"}
      </span>
      <span className={`triage-tag tone-${URGENCY_TONE[t.urgency.value]}`} title={compact ? urgencySource(t.urgency) : undefined}>
        {t.urgency.value[0].toUpperCase() + t.urgency.value.slice(1)} urgency
        {!compact && <span className="triage-why"> · {urgencySource(t.urgency)}</span>}
      </span>
    </div>
  );
}

/** Intake tags for the current request: status, urgency and earlier requests that ask the same thing. */
export function TriageStrip({ stages }: { stages: Partial<Record<StageId, StageEvent>> }) {
  const t = currentTriage(stages);
  if (!t) return null;
  const dup = t.similar?.duplicates ?? [];
  const sim = t.similar?.similar ?? [];
  return (
    <section className="triage" aria-label="Request triage">
      <TriageTags triage={t} />
      {dup.length > 0 && (
        <p className="triage-note">
          <strong>Asked before:</strong> the same request is already in the queue {t.similar!.duplicate_count} times
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
