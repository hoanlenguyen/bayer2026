import type { Candidate, CatalogMeta, StageId } from "../../api/types";

const pct = (v: number) => `${Math.round(v * 100)}%`;
const tone = (v: number, good = 0.9, ok = 0.6) => (v >= good ? "ok" : v >= ok ? "warn" : "bad");

function names(ids: string[] = [], kind: "m" | "d", catalog: CatalogMeta | null): string {
  if (!ids.length) return "None";
  const src = kind === "m" ? catalog?.measures : catalog?.dimensions;
  return ids.map((i) => src?.[i]?.name ?? i).join(", ");
}

function Score({ label, value, good }: { label: string; value: number; good?: number }) {
  return (
    <span className={`score tone-${tone(value, good)}`} title={label}>
      <span className="score-k">{label}</span>
      <span className="score-v">{pct(value)}</span>
    </span>
  );
}

function KV({ rows }: { rows: [string, React.ReactNode][] }) {
  return (
    <dl className="kv">
      {rows.map(([k, v]) => (
        <div key={k}><dt>{k}</dt><dd>{v}</dd></div>
      ))}
    </dl>
  );
}

export function StageDetail({ stage, data, catalog }: { stage: StageId; data: any; catalog: CatalogMeta | null }) {
  switch (stage) {
    case "intent":
      return (
        <KV rows={[
          ["Decision", data.decision ?? "Not yet known"],
          ["Numbers", names(data.measures, "m", catalog)],
          ["Broken down by", names(data.dimensions, "d", catalog)],
          ["Time grain", data.grain ?? "Not yet known"],
          ...(Object.keys(data.filters ?? {}).length
            ? [["Filters", Object.entries(data.filters).map(([k, v]) => `${k} = ${v}`).join(", ")] as [string, string]]
            : []),
          ...(data.department ? [["Department", data.department] as [string, string]] : []),
          ...(data.unmatched_terms?.length ? [["Not in catalog", data.unmatched_terms.join(", ")] as [string, string]] : []),
        ]} />
      );

    case "discovery": {
      const cands: Candidate[] = data.candidates ?? [];
      return (
        <div className="detail-stack">
          <p className="muted">Searched {data.searched} catalog assets. Scores compare each report with your request.</p>
          {cands.length === 0 && <p className="muted">No existing report uses these numbers.</p>}
          {cands.map((c) => (
            <div key={c.asset_id} className="cand">
              <div className="cand-head"><strong>{c.name}</strong></div>
              <div className="scores">
                <Score label="Coverage" value={c.coverage} />
                <Score label="Freshness" value={c.freshness} />
                <Score label="Governance" value={c.governance} good={0.8} />
              </div>
              {(c.measures_missing.length > 0 || c.dimensions_missing.length > 0 || !c.grain_supported) && (
                <p className="muted small">
                  Missing: {[...c.measures_missing.map((m) => catalog?.measures[m]?.name ?? m),
                    ...c.dimensions_missing.map((d) => catalog?.dimensions[d]?.name ?? d),
                    ...(c.grain_supported ? [] : ["finer time grain"])].join(", ")}
                </p>
              )}
            </div>
          ))}
          {!data.availability?.available && (
            <p className="warn-text small">
              Data not available: {[...(data.availability?.missing_terms ?? []), ...(data.availability?.missing_dimensions ?? [])].join(", ") || "no catalog measures matched"}
            </p>
          )}
        </div>
      );
    }

    case "governance":
      return (
        <div className="detail-stack">
          {(data.candidates ?? []).map((c: Candidate) => (
            <div key={c.asset_id} className="cand">
              <div className="cand-head"><strong>{c.name}</strong><Score label="Score" value={c.governance} good={0.8} /></div>
              <ul className="checks">
                {c.checks.map((k) => (
                  <li key={k.id} className={k.passed ? "pass" : "fail"}>
                    <span aria-hidden="true">{k.passed ? "✓" : "✕"}</span> {k.label} <span className="muted">({k.weight.toFixed(2)})</span>
                  </li>
                ))}
              </ul>
              {c.gates_failed.map((g) => <p key={g} className="bad-text small">Blocked: {g}</p>)}
            </div>
          ))}
        </div>
      );

    case "decision": {
      const c: Candidate | null = data.candidate;
      return (
        <div className="detail-stack">
          <div className={`decision-badge d-${data.decision}`}>
            {({ reuse: "Reuse", extend: "Extend", create: "Create", not_feasible: "Not feasible" } as Record<string, string>)[data.decision]}
            {data.change_type && <span> · {data.change_type}</span>}
          </div>
          <p>{data.reason}</p>
          <p className="rule"><span className="muted">Rule applied: </span>{data.rule}</p>
          {c && (
            <div className="scores">
              <Score label="Coverage" value={c.coverage} />
              <Score label="Freshness" value={c.freshness} />
              <Score label="Governance" value={c.governance} good={0.8} />
            </div>
          )}
          {data.flags?.length > 0 && (
            <div className="flags-box">
              <strong className="small">Also flagged</strong>
              {data.flags.map((f: { asset_id: string; name: string; message: string }) => (
                <p key={f.asset_id} className="small"><strong>{f.name}</strong>: {f.message}</p>
              ))}
            </div>
          )}
          <details className="thresholds">
            <summary>Thresholds</summary>
            <KV rows={Object.entries(data.thresholds ?? {}).map(([k, v]) => [k.replace(/_/g, " "), String(v)])} />
          </details>
        </div>
      );
    }

    case "deliver": {
      const a = data.asset;
      return (
        <KV rows={[
          ["Report", <strong key="n">{a.name}</strong>],
          ["Workspace", a.workspace],
          ["Owner", a.owner],
          ["Views (90 days)", a.views_90d?.toLocaleString("en-US") ?? "0"],
          ["Last reviewed", a.last_review],
        ]} />
      );
    }

    case "evidence":
      return (
        <div className="detail-stack">
          <ul className="checks">
            {data.proofs.map((p: { ok: boolean; text: string }) => (
              <li key={p.text} className={p.ok ? "pass" : "fail"}><span aria-hidden="true">{p.ok ? "✓" : "!"}</span> {p.text}</li>
            ))}
          </ul>
          <KV rows={Object.entries(data.columns as Record<string, string[]>).map(([t, cols]) => [t, <code key={t}>{cols.join(", ")}</code>])} />
        </div>
      );

    case "spec":
      return (
        <div className="detail-stack">
          <KV rows={[
            ["Name", <strong key="n">{data.name}</strong>],
            ["Type", `${data.decision_type}${data.change_type ? ` (${data.change_type})` : ""}`],
            ["Owner", data.owner],
            ["Review date", data.review_date],
            ["Pages", data.pages.map((p: { name: string; visuals: unknown[] }) => `${p.name} (${p.visuals.length} visuals)`).join(", ")],
          ]} />
          {data.rationale && <p className="muted">{data.rationale}</p>}
          <details>
            <summary>DashboardSpec (JSON)</summary>
            <pre className="code">{JSON.stringify(data, null, 2)}</pre>
          </details>
        </div>
      );

    case "approval":
      return <KV rows={[["Approver", data.approver], ...(data.approved_at ? [["Approved at", data.approved_at] as [string, string]] : [])]} />;

    case "render":
      return (
        <div className="detail-stack">
          <ul className="files">
            {data.files.map((f: { path: string; bytes: number }) => (
              <li key={f.path}><code>{f.path}</code><span className="muted">{f.bytes.toLocaleString("en-US")} B</span></li>
            ))}
          </ul>
          <details>
            <summary>Table definition (TMDL preview)</summary>
            <pre className="code">{data.preview.model}</pre>
          </details>
          {!data.validated_in_power_bi && <p className="muted small">Skeleton output: not yet opened in Power BI Desktop.</p>}
        </div>
      );

    case "register":
      return (
        <KV rows={[
          ["Asset", <strong key="n">{data.name}</strong>],
          ["Workspace", data.workspace],
          ["Owner", data.owner],
          ["Next review", data.next_review],
        ]} />
      );
  }
}
