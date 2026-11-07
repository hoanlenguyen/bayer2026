import type { Candidate, CatalogMeta, StageEvent, StageId } from "../../api/types";
import { Icon } from "../Icon";
import { RUNNING_COPY } from "./FlowPanel";
import { RecommendationChip } from "./RecommendationChip";

interface Props {
  stages: Partial<Record<StageId, StageEvent>>;
  catalog: CatalogMeta | null;
  busy: boolean;
}

const VERDICTS = {
  reuse: "Use the existing report",
  repair: "Repair the existing report, then use it",
  consolidate: "Merge the overlapping reports into one",
  migrate: "Move this report to Power BI",
  retire: "Retire this report",
  review: "Have someone review this report first",
  new_build: "Build a new report",
  not_feasible: "This can't be answered with today's data",
} as const;

const openEntity = (id: string) => window.dispatchEvent(new CustomEvent("open-entity", { detail: id }));

function ScoreMeter({ label, hint, value, target, floor }: { label: string; hint: string; value: number; target: number; floor: number }) {
  const tone = value >= target ? "ok" : value >= floor ? "warn" : "bad";
  const pct = Math.round(value * 100);
  return (
    <div className="vscore">
      <div className="vscore-top"><span className="vscore-label">{label}</span><span className={`vscore-value text-${tone}`}>{pct}%</span></div>
      <div
        className="vscore-track"
        role="meter"
        aria-label={label}
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        title={`Needs ${Math.round(target * 100)}% to pass`}
      >
        <span className="vscore-fill" style={{ width: `${pct}%`, background: `var(--${tone})` }} />
        <span className="vscore-tick" style={{ left: `${target * 100}%` }} />
      </div>
      <p className="vscore-hint">{hint}</p>
    </div>
  );
}

/** The answer to "do we already have this?": the recommendation and its scores. The evidence is in the steps beside it. It only recommends. */
export function VerdictCard({ stages, catalog, busy }: Props) {
  const stage = stages.decision;
  if (!stage || stage.status !== "done") return null;

  const d = stage.data;
  const title = VERDICTS[d.decision as keyof typeof VERDICTS] ?? stage.summary;
  const c: Candidate | null = d.candidate ?? null;
  // On a new build the candidate is only the closest old report, not the report to build.
  const building = d.decision === "new_build";
  const t = d.thresholds ?? {};

  const asset = stages.deliver?.data?.asset;
  const reportName: string | null = asset?.name ?? (building ? null : c?.name) ?? null;
  const targetModel: { name: string; owner?: string | null; owner_status?: string | null } | null = d.target_model ?? null;
  const owner: string | null = asset?.owner ?? (building ? targetModel?.owner : c?.owner) ?? null;
  const ownerStatus: string | null | undefined = asset?.owner_status ?? (building ? targetModel?.owner_status : c?.owner_status);
  const ownerText = owner && `Owner: ${owner}${ownerStatus && ownerStatus !== "active" ? ` (${ownerStatus})` : ""}`;
  const reportId: string | null = asset?.id ?? (building ? null : c?.asset_id) ?? null;

  const missing = c && !building
    ? [
        ...c.measures_missing.map((m) => catalog?.measures[m]?.name ?? m),
        ...(c.dimensions_missing ?? []).map((x) => catalog?.dimensions[x]?.name ?? x),
        ...(c.grain_supported === false ? ["Finer time grain"] : []),
      ]
    : [];
  const unavailable: string[] = d.decision === "not_feasible"
    ? [
        ...(d.availability?.missing_terms ?? []),
        ...(d.availability?.missing_dimensions ?? []).map((x: string) => catalog?.dimensions[x]?.name ?? x),
      ]
    : [];

  const running = (Object.values(stages) as StageEvent[]).find((s) => s.status === "running");

  return (
    <article className="verdict" aria-label="Decision">
      <header className="verdict-head">
        <RecommendationChip value={String(d.decision)} />
        <h2>{title}</h2>
        {reportName && (
          <p className="verdict-subject">
            <strong>{reportName}</strong>
            {ownerText && <span className="muted"> · {ownerText}</span>}
          </p>
        )}
        {!reportName && building && targetModel && (
          <p className="verdict-subject">
            <span className="muted">Shared model: </span><strong>{targetModel.name}</strong>
            {ownerText && <span className="muted"> · {ownerText}</span>}
          </p>
        )}
      </header>

      {d.reason && <p className="verdict-note">{d.reason}</p>}

      {building && c && (
        <p className="muted verdict-note">Closest existing report, which can't be reused: <strong>{c.name}</strong></p>
      )}

      {c ? (
        <div className="vscores">
          <ScoreMeter label="Coverage" hint="Has the numbers you asked for" value={c.coverage} target={t.reuse_coverage ?? 0.9} floor={t.consolidate_min_coverage ?? t.extend_min_coverage ?? 0.6} />
          <ScoreMeter label="Freshness" hint="Data is recent enough" value={c.freshness} target={t.reuse_freshness ?? 0.9} floor={0.6} />
          <ScoreMeter label="Governance" hint="Certified, owned and reviewed" value={c.governance} target={t.reuse_governance ?? t.min_governance ?? 0.8} floor={t.consolidate_governance ?? t.ungoverned_governance ?? 0.6} />
        </div>
      ) : building && (
        <p className="muted verdict-note">No existing report has these numbers, so reuse is not possible.</p>
      )}

      {missing.length > 0 && (
        <p className="verdict-note"><span className="muted">To add: </span>{missing.join(", ")}</p>
      )}
      {unavailable.length > 0 && (
        <p className="verdict-note"><span className="muted">Not in the catalog: </span>{unavailable.join(", ")}</p>
      )}

      {d.flags?.length > 0 && (
        <div className="verdict-flags">
          <Icon name="alert" />
          <div>
            {d.flags.map((f: { asset_id: string; name: string; message: string }) => (
              <p key={f.asset_id}><strong>{f.name}:</strong> {f.message}</p>
            ))}
          </div>
        </div>
      )}

      {busy && (
        <p className="verdict-progress"><span className="spinner" aria-hidden="true" />{running ? RUNNING_COPY[running.stage] : "Working on the next step"}</p>
      )}

      {d.rules_applied?.length > 0 && <p className="muted small verdict-fine">Rules applied: {d.rules_applied.join(", ")}</p>}

      {d.decision !== "reuse" && d.decision !== "not_feasible" && (
        <p className="muted small verdict-fine">This is a recommendation. Nothing has been built, changed or retired.</p>
      )}

      {reportId && (
        <div className="verdict-actions">
          <button type="button" className="btn" onClick={() => openEntity(reportId)}>
            View in Estate Explorer<Icon name="arrowRight" />
          </button>
        </div>
      )}
    </article>
  );
}
