import { amount, comparison, month } from "../lib/briefingFormat";
import { MonthlyHistory } from "./BriefingHistory";
import { Icon } from "../components/Icon";
import type { Evidence, ReportView, Snapshot } from "../api/briefings";

type Periods = Pick<Snapshot, "period" | "previous_period">;

export function ReportCard({ view, periods, index, onOpen }: {
  view: ReportView; periods: Periods; index: number; onOpen?: () => void;
}) {
  const bars = [
    { label: month(periods.previous_period, true), value: view.previous },
    { label: month(periods.period, true), value: view.current, current: true },
  ];
  if (view.forecast != null) bars.push({ label: `${month(periods.period, true)} fcst.`, value: view.forecast });
  const max = view.unit === "%" ? 100 : Math.max(...bars.map(b => b.value), 1);
  return <article className="bf-card">
    <div className="bf-card-heading"><div><span className="bf-kicker">Report view {String(index + 1).padStart(2, "0")}</span>
      <h3>{view.title}</h3></div></div>
    <p className="bf-origin">{view.report}</p>
    <div className="bf-value">{amount(view.current, view.unit)}</div>
    <p className="bf-comparison">{comparison(view, periods.previous_period)}</p>
    {view.display_mode === "table" ? <table className="bf-value-table"><caption className="sr-only">Values for {view.title}</caption>
      <thead><tr><th scope="col">Period</th><th scope="col">Value</th></tr></thead><tbody>{bars.map(bar =>
        <tr key={bar.label}><th scope="row">{bar.label}</th><td>{amount(bar.value, view.unit)}</td></tr>)}</tbody></table> : <dl className="bf-bars">{bars.map(bar => <div key={bar.label} className={bar.current ? "bf-current" : ""}>
      <dt>{bar.label}</dt><dd><span className="bf-track" aria-hidden="true"><span style={{ width: `${Math.min(100, Math.max(0, bar.value / max * 100))}%` }} /></span>
        <span>{amount(bar.value, view.unit)}</span></dd></div>)}</dl>}
    {onOpen && <button type="button" className="bf-card-link" onClick={onOpen}>Open report <span className="sr-only">{view.report}</span><Icon name="arrowRight" size={15} /></button>}
  </article>;
}

export function WorkbookEvidence({ evidence }: { evidence: Evidence }) {
  return <div className="bf-evidence">
    <p><strong>{evidence.sheet}</strong> · {evidence.rows.length === 1 ? "row" : "rows"} {evidence.rows.join(", ")}</p>
    <p className="bf-origin">{evidence.filters.product_id} · {evidence.filters.market_id}</p>
    <div className="bf-table-scroll" tabIndex={0} role="region" aria-label="Workbook values">
      <table><thead><tr><th scope="col">Workbook field</th>{evidence.records.map((r, index) =>
        <th scope="col" key={index}>{r.month != null ? String(r.month) : `Row ${evidence.rows[index]}`}</th>)}</tr></thead>
        <tbody>{evidence.fields.map(field => <tr key={field}><th scope="row">{field}</th>
          {evidence.records.map((record, index) => <td key={index}>{record[field] == null ? "—" : String(record[field])}</td>)}</tr>)}</tbody></table>
    </div>
  </div>;
}

export function SnapshotEvidence({ snapshot }: { snapshot: Snapshot }) {
  return <details className="bf-disclosure"><summary>Saved briefing snapshot</summary>
    <div className="bf-snapshot"><p>{snapshot.product} · {snapshot.market} · {month(snapshot.period)}</p>
      <p className="bf-origin">Compared with {month(snapshot.previous_period)} · Synthetic workbook · Version <code>{snapshot.version}</code></p>
      {snapshot.views.map(view => <details className="bf-disclosure" key={view.id}><summary>{view.report} · {amount(view.current, view.unit)}</summary>
        <MonthlyHistory view={view} /><WorkbookEvidence evidence={view.evidence} /></details>)}
    </div>
  </details>;
}
