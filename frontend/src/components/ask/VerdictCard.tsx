import type { Candidate, CatalogMeta, StageEvent, StageId } from "../../api/types";
import { Icon } from "../Icon";
import { RUNNING_COPY } from "./FlowPanel";

interface Props {
  stages: Partial<Record<StageId, StageEvent>>;
  catalog: CatalogMeta | null;
  busy: boolean;
  onApprove: (approved: boolean) => void;
}

const VERDICTS = {
  reuse: { tag: "Reuse", title: "Use the existing report", tone: "ok" },
  extend: { tag: "Extend", title: "Extend an existing report", tone: "accent" },
  maintenance: { tag: "Extend", title: "Fix the refresh schedule, no new report", tone: "accent" },
  create: { tag: "Create", title: "Build a new report", tone: "accent" },
  repair: { tag: "Repair", title: "Repair the existing report, no new report", tone: "accent" },
  consolidate: { tag: "Consolidate", title: "Merge the overlapping reports into one", tone: "accent" },
  migrate: { tag: "Migrate", title: "Rebuild this report in Power BI", tone: "accent" },
  new_build: { tag: "New build", title: "Build a new report", tone: "accent" },
  not_feasible: { tag: "Not feasible", title: "This can't be answered with today's data", tone: "bad" },
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

/** The answer to "do we already have this?": verdict, scores and the one action that follows. */
export function VerdictCard({ stages, catalog, busy, onApprove }: Props) {
  const stage = stages.decision;
  if (!stage || stage.status !== "done") return null;

  const d = stage.data;
  const v = d.decision === "extend" && d.change_type === "maintenance"
    ? VERDICTS.maintenance
    : VERDICTS[d.decision as keyof typeof VERDICTS] ?? { tag: String(d.decision), title: stage.summary, tone: "accent" as const };
  const c: Candidate | null = d.candidate ?? null;
  // On a new build the candidate is only the closest old report, not the report being built.
  const building = d.decision === "new_build" || d.decision === "create";
  const t = d.thresholds ?? {};

  const asset = stages.deliver?.data?.asset;
  const spec = stages.spec?.status === "done" ? stages.spec.data : null;
  const evidence = stages.evidence?.status === "done" ? stages.evidence.data : null;
  const approval = stages.approval;
  const registered = stages.register?.status === "done" ? stages.register.data : null;
  const files: number | null = stages.render?.status === "done" ? stages.render.data.files.length : null;

  const reportName: string | null = asset?.name ?? (building ? spec?.name : c?.name ?? spec?.name) ?? null;
  const owner: string | null = asset?.owner ?? spec?.owner ?? null;

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
  const proofs: { ok: boolean }[] = evidence?.proofs ?? [];
  const proofsOk = proofs.filter((p) => p.ok).length;
  const waiting = approval?.status === "waiting" && !busy;

  return (
    <article className={`verdict verdict-${v.tone}`} aria-label="Decision">
      <header className="verdict-head">
        <span className={`verdict-tag tag-${v.tone}`}>{v.tag}</span>
        <h2>{v.title}</h2>
        {reportName && (
          <p className="verdict-subject">
            <strong>{reportName}</strong>
            {owner && <span className="muted"> · Owner: {owner}</span>}
          </p>
        )}
      </header>

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

      {waiting && spec && (
        <section className="approval" aria-label="Approval needed">
          <h3>Your approval is needed</h3>
          <p className="muted">Nothing is built until you approve.</p>
          <ul className="approval-facts">
            <li><span className="muted">Report</span>{spec.name}</li>
            <li>
              <span className="muted">Content</span>
              {spec.pages.map((p: { name: string; visuals: unknown[] }) => `${p.name} (${p.visuals.length} visuals)`).join(", ")}
            </li>
            <li><span className="muted">First review</span>{spec.review_date}</li>
            {proofs.length > 0 && <li><span className="muted">Data checks</span>{proofsOk} of {proofs.length} passed</li>}
          </ul>
          {!spec.validation?.passed && (
            <p className="text-warn">The design did not pass every check. See "Design the report" in the steps before you approve.</p>
          )}
          <div className="approval-actions">
            <button type="button" className="btn" onClick={() => onApprove(true)}>
              <Icon name="check" />Approve as {approval.data?.approver ?? "owner"}
            </button>
            <button type="button" className="btn-outline" onClick={() => onApprove(false)}>Reject</button>
          </div>
        </section>
      )}

      {approval?.status === "rejected" && (
        <p className="verdict-outcome"><Icon name="close" />{approval.summary}. Nothing was built.</p>
      )}

      {registered && (
        <p className="verdict-outcome text-ok">
          <Icon name="check" />
          Approved and added to the catalog{files !== null ? ` (${files} PBIP files)` : ""}. Next review: {registered.next_review}.
        </p>
      )}

      {(registered || asset) && (
        <div className="verdict-actions">
          <button type="button" className="btn" onClick={() => openEntity(registered?.id ?? asset.id)}>
            View in Estate Explorer<Icon name="arrowRight" />
          </button>
        </div>
      )}
    </article>
  );
}
