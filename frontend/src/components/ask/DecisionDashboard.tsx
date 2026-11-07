import { useState } from "react";
import type { DecisionHandoff, MetricSeries } from "../../api/handoff";
import { PulseDashboard } from "../PulseDashboard";
import "./decision-dashboard.css";

interface MigrationAsset { id: string; name: string; recommendation: string; reason: string }
const paths = [
  { id: "migrate", label: "Migrate" }, { id: "retire", label: "Retire" },
  { id: "review", label: "Human review" }, { id: "consolidate", label: "Consolidate" },
];

function MigrationOverview({ assets }: { assets: MigrationAsset[] }) {
  const [selected, setSelected] = useState<string>();
  const groups = paths.map(path => ({ ...path, assets: assets.filter(asset => asset.recommendation === path.id) }))
    .filter(path => path.assets.length > 0);
  const current = groups.find(group => group.id === selected);
  if (!groups.length) return null;
  return <section className="decision-overview" aria-label="Migration plan">
    <span className="do-kicker">Tableau migration plan</span>
    <h3><strong>{assets.length}</strong> {assets.length === 1 ? "report assessed" : "reports assessed"}</h3>
    <div className="do-strip" aria-hidden="true">{groups.map(group =>
      <span key={group.id} className={`do-${group.id}`} style={{ flexGrow: group.assets.length }} />)}</div>
    <div className="do-keys" role="group" aria-label="Inspect reports by recommendation">{groups.map(group =>
      <button type="button" key={group.id} aria-pressed={selected === group.id}
        onClick={() => setSelected(selected === group.id ? undefined : group.id)}>
        <i className={`do-${group.id}`} aria-hidden="true" />{group.label}<strong>{group.assets.length}</strong></button>)}</div>
    {current ? <ul className="do-assets">{current.assets.map(asset => <li key={asset.id}><strong>{asset.name}</strong>
      <span>{asset.reason}</span></li>)}</ul> : <p>Choose a recommendation to inspect the reports behind it.</p>}
  </section>;
}

function SourceSeries({ series }: { series: MetricSeries }) {
  if (series.display_mode === "table") return <section className="rh-preview" aria-label="Approved monthly comparison table">
    <h3>Monthly comparison</h3><p className="rh-sub">{series.product} · {series.market} · Synthetic workbook</p>
    <div className="do-data-scroll"><table className="rh-table"><thead><tr><th scope="col">Month</th>{series.columns.map(col =>
      <th scope="col" key={col.id}>{col.name} ({col.unit})</th>)}</tr></thead>
      <tbody>{series.points.map(point => <tr key={point.period}><th scope="row">{point.period}</th>{series.columns.map(col =>
        <td key={col.id}>{point.values[col.id]?.toLocaleString("en-GB", { maximumFractionDigits: 2 }) ?? "—"}</td>)}</tr>)}</tbody>
    </table></div></section>;
  const forecast = series.columns.find(col => col.id === "sales_forecast");
  const metrics = series.columns.filter(col => col !== forecast || !series.columns.some(item => item.id === "net_sales"))
    .map(col => ({ ...col, title: col.name, points: series.points.flatMap(point => Number.isFinite(point.values[col.id])
      ? [{ period: point.period, row: point.row, value_type: point.value_type, value: point.values[col.id],
           forecast: col.id === "net_sales" && forecast ? point.values[forecast.id] : undefined }] : []) }));
  return <PulseDashboard scope={`${series.product} · ${series.market}`} source={series.source} metrics={metrics} compact />;
}

export function DecisionDashboard({ data }: { data: DecisionHandoff }) {
  if (data.metric_series?.points.length && data.handoff_verdict !== "review") return <SourceSeries series={data.metric_series} />;
  if (data.intent.migration) {
    const migration = data.evidence.find(step => step.stage === "migration")?.data;
    if (migration?.assets?.length) return <MigrationOverview assets={migration.assets} />;
  }
  if (["new_build", "repair", "consolidate", "extend"].includes(data.verdict) && data.intent.measures.length) {
    const requested = new Set(data.intent.measures);
    const reports = data.candidates.filter(candidate => Array.isArray(candidate.measures_found)).slice(0, 3);
    if (reports.length) return <section className="do-coverage" aria-label="Coverage of requested KPIs">
      <span className="rh-kicker">Catalog comparison</span><h3>Which reports list the requested KPIs?</h3>
      {reports.map(candidate => {
        const matched = [...requested].filter(id => candidate.measures_found.includes(id)).length;
        return <div key={candidate.asset_id}><span>{candidate.name}</span><strong>{matched} of {requested.size}</strong>
          <meter aria-label={`Requested KPIs listed on ${candidate.name}`} min={0} max={requested.size} value={matched} /></div>;
      })}
    </section>;
  }
  return null;
}
