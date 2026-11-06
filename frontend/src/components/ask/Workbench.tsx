import { useState, type ReactNode } from "react";
import type {
  Candidate,
  CatalogMeta,
  DecisionType,
  StageEvent,
  StageId,
} from "../../api/types";
import { StageDetail } from "./StageDetail";

interface Props {
  stages: Partial<Record<StageId, StageEvent>>;
  catalog: CatalogMeta | null;
  decision: DecisionType | null;
  children: ReactNode;
}
const percent = (n: number) => `${Math.round(n * 100)}%`;
const labels: Record<DecisionType, string> = {
  reuse: "Reuse existing analysis",
  repair: "Repair existing analysis",
  consolidate: "Consolidate into existing analysis",
  migrate: "Migrate to Power BI (without the waste)",
  new_build: "Build one report on a shared model",
  not_feasible: "Adjust the request",
};
export const decisionLabel = (decision: DecisionType | null) =>
  decision ? labels[decision] : "Understanding the request";

/** Presentation only. All fit scores, checks and decisions come from pipeline events. */
export function Workbench({ stages, catalog, decision, children }: Props) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [inspector, setInspector] = useState<
    "fit" | "evidence" | "spec" | "decision"
  >("fit");
  // Governance events contain partial summaries; discovery retains the full scored candidates.
  const candidates: Candidate[] = stages.discovery?.data?.candidates ?? [];
  const recommended: Candidate | undefined = stages.decision?.data?.candidate;
  const selected =
    candidates.find((c) => c.asset_id === selectedId) ??
    candidates.find((c) => c.asset_id === recommended?.asset_id) ??
    candidates[0];
  const intent = stages.intent?.data;
  const names = (ids: string[], kind: "measures" | "dimensions") =>
    ids.map((id) => catalog?.[kind]?.[id]?.name ?? id).join(", ") ||
    "None specified";
  const requestedScope =
    Object.entries((intent?.filters ?? {}) as Record<string, string[]>)
      .map(([k, v]) => `${k.replace("_", " ")}: ${v.join(", ")}`)
      .join(" · ") || (intent?.scope_global ? "All products, all markets" : "Not specified");
  const dimensions = selected
    ? [
        {
          title: "KPIs",
          requested: names(
            intent?.measures ?? [
              ...selected.measures_found,
              ...selected.measures_missing,
            ],
            "measures",
          ),
          available: names(selected.measures_found, "measures"),
          missing: names(selected.measures_missing, "measures"),
          aligned: selected.measures_missing.length === 0,
        },
        {
          title: "Scope",
          requested: requestedScope + (intent?.scope_global ? " (global)" : ""),
          available: selected.scope_note ?? "Unknown",
          missing: "Product or market scope does not fit",
          aligned: (selected.scope_score ?? 0) >= 0.75,
        },
        {
          title: "Usage",
          requested: "Used by people today",
          available: `${(selected.views_90d ?? 0).toLocaleString("en-US")} views in Aug–Oct 2026 · ${selected.platform ?? ""} · ${(selected.lifecycle ?? "").replace("_", " ")}`,
          missing: "Low usage or marked for retirement",
          aligned: (selected.views_90d ?? 0) >= 150 && selected.lifecycle !== "candidate_retire",
        },
      ]
    : [];
  const searched = stages.discovery?.data?.searched;
  const data = inspector === "fit" ? null : stages[inspector]?.data;
  return (
    <div className="workbench-grid">
      <aside className="asset-rail" aria-label="Existing analyses">
        <div className="section-heading">
          <h2>Existing analyses</h2>
          <span className="folio">
            {String(candidates.length).padStart(2, "0")}
          </span>
        </div>
        <p className="rail-caption">
          {searched != null
            ? `${stages.discovery?.data?.total_candidates ?? candidates.length} of ${searched} assets use a requested KPI; closest ${candidates.length} shown`
            : "Matches appear as discovery runs."}
        </p>
        <div className="asset-list">
          {candidates.map((c, i) => (
            <button
              key={c.asset_id}
              type="button"
              className="asset-row"
              aria-pressed={selected?.asset_id === c.asset_id}
              onClick={() => {
                setSelectedId(c.asset_id);
                setInspector("fit");
              }}
            >
              <span className="folio">{String(i + 1).padStart(2, "0")}</span>
              <span>
                <strong>{c.name}</strong>
                <small>
                  {c.asset_id} · {c.platform} · {percent(c.coverage)} coverage ·{" "}
                  {percent(c.governance)} governance
                </small>
                <span className="asset-note">
                  {c.asset_id === recommended?.asset_id
                    ? "Closest comparison candidate"
                    : c.gates_failed.length
                      ? "Governance review required"
                      : "Select to inspect fit"}
                </span>
              </span>
            </button>
          ))}
          {!candidates.length && (
            <div className="rail-empty">
              <span className="index-mark" aria-hidden="true">
                ∅
              </span>
              <p>
                {stages.discovery?.status === "done"
                  ? "No existing analysis matched this request. The decision will explain the next step."
                  : "Your existing work comes first. Clarify the request to find relevant analyses."}
              </p>
            </div>
          )}
        </div>
        <a className="rail-link" href="#explorer">
          Browse the asset index <span aria-hidden="true">↗</span>
        </a>
      </aside>
      <section
        className="comparison-surface"
        aria-label="Compatibility workbench"
      >
        <div className="section-heading">
          <h2>
            {selected ? "Compatibility view" : "Define the investigation"}
          </h2>
          <span className="folio">01 / COMPARE</span>
        </div>
        {selected ? (
          <>
            <p className="comparison-caption">
              Your request, aligned with <strong>{selected.name}</strong>.
            </p>
            <div className="alignment-grid">
              <span className="alignment-label">Your request</span>
              {dimensions.map((d) => (
                <div className="alignment-cell requested" key={d.title}>
                  <span>{d.title}</span>
                  <strong>{d.requested}</strong>
                </div>
              ))}
              <span className="alignment-label">Selected analysis</span>
              {dimensions.map((d) => (
                <button
                  type="button"
                  className={`alignment-cell available ${d.aligned ? "aligned" : "needs-review"}`}
                  key={d.title}
                  onClick={() => setInspector("fit")}
                >
                  <span>{d.title}</span>
                  <strong>{d.available}</strong>
                  <small>
                    {d.aligned ? "✓ Aligned" : "! Missing coverage"}
                  </small>
                </button>
              ))}
            </div>
            <div className="fit-scores" aria-label="Backend decision scores">
              {(
                [
                  ["Coverage", selected.coverage],
                  ["Freshness", selected.freshness],
                  ["Governance", selected.governance],
                ] as [string, number][]
              ).map(([label, score]) => (
                <div key={label}>
                  <span>{label}</span>
                  <strong>{percent(score)}</strong>
                  <meter min="0" max="1" value={score} aria-label={label} />
                </div>
              ))}
            </div>
            <div className="compatibility-summary">
              <span className="folio">COVERAGE REVIEW</span>
              <p>
                {dimensions.some((d) => !d.aligned)
                  ? dimensions
                      .filter((d) => !d.aligned)
                      .map((d) => `${d.title}: ${d.missing}`)
                      .join(" · ")
                  : "Requested KPIs, scope and usage line up. Check freshness and governance before reuse."}
              </p>
            </div>
          </>
        ) : (
          <div className="investigation-intro">
            <span className="folio">
              REQUEST → EXISTING WORK → EVIDENCE → PLAN
            </span>
            <h3>
              Start with the request.
              <br />
              Build on what exists.
            </h3>
            <p>
              The investigation keeps your requirements, catalog matches and
              supporting evidence together.
            </p>
          </div>
        )}
        {children}
      </section>
      <aside className="evidence-inspector" aria-label="Evidence inspector">
        <div className="section-heading">
          <h2>Evidence &amp; review</h2>
          <span className="folio">02 / VERIFY</span>
        </div>
        <div
          className="inspector-nav"
          role="group"
          aria-label="Inspect results"
        >
          {(["fit", "evidence", "spec", "decision"] as const).map((id) => (
            <button
              type="button"
              key={id}
              aria-pressed={inspector === id}
              disabled={id !== "fit" && !stages[id]?.data}
              onClick={() => setInspector(id)}
            >
              {
                {
                  fit: "Asset fit",
                  evidence: "Evidence",
                  spec: "Spec",
                  decision: "Decision",
                }[id]
              }
            </button>
          ))}
        </div>
        {inspector === "fit" ? (
          selected ? (
            <>
              <span className="folio">{selected.asset_id}</span>
              <h3>{selected.name}</h3>
              <p className="muted">
                Checks and scores reported by the backend for this analysis.
              </p>
              <ul className="review-checks">
                {selected.checks.map((check) => (
                  <li key={check.id}>
                    <span
                      className={check.passed ? "check-pass" : "check-review"}
                    >
                      {check.passed ? "✓" : "!"}
                    </span>
                    <span>
                      {check.label}
                      <small>{check.passed ? "Passed" : "Needs review"}</small>
                    </span>
                  </li>
                ))}
              </ul>
              {selected.gates_failed.map((gate) => (
                <p className="gate-warning" key={gate}>
                  Blocked: {gate}
                </p>
              ))}
              <button
                className="btn-ghost inspector-open"
                type="button"
                onClick={() =>
                  window.dispatchEvent(
                    new CustomEvent("open-entity", {
                      detail: selected.asset_id,
                    }),
                  )
                }
              >
                Inspect source in asset index ↗
              </button>
              {recommended && recommended.asset_id !== selected.asset_id && (
                <p className="fineprint">
                  You are inspecting an alternative. The decision below still
                  refers to {recommended.name}.
                </p>
              )}
            </>
          ) : (
            <div className="inspector-empty">
              <span className="folio">A TRACEABLE DECISION</span>
              <h3>
                Evidence stays
                <br />
                beside the work.
              </h3>
              <p>
                Inspect coverage, freshness, ownership and governance checks
                here when a match is available.
              </p>
              <p>Extensions and new reports still require human approval.</p>
            </div>
          )
        ) : data ? (
          <StageDetail stage={inspector} data={data} catalog={catalog} />
        ) : (
          <p className="muted">
            This result will appear when the stage completes.
          </p>
        )}
        <div className="inspector-footnote">
          {decision ? decisionLabel(decision) : "Awaiting a decision"}
          <span>Catalog metadata · synthetic Bayer data pack</span>
        </div>
      </aside>
    </div>
  );
}
