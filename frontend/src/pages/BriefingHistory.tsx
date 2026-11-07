import type { ReportHistory, ReportView } from "../api/briefings";
import { PulseChart } from "../components/PulseChart";
import { amount, month } from "../lib/briefingFormat";

function HistoryTable({ history }: { history: ReportHistory }) {
  const hasForecast = history.points.some(point => point.forecast != null);
  return <div className="bf-table-scroll"><table className="bf-history-table">
    <caption className="sr-only">Monthly workbook values, source record types and sheet rows</caption>
    <thead><tr><th scope="col">Month</th><th scope="col">Value</th>{hasForecast && <th scope="col">Forecast</th>}
      <th scope="col">Record type</th><th scope="col">Row</th></tr></thead>
    <tbody>{history.points.map(point => <tr key={point.row}><th scope="row">{point.period}</th>
      <td>{amount(point.value, history.unit)}</td>{hasForecast && <td>{point.forecast == null ? "—" : amount(point.forecast, history.unit)}</td>}
      <td>{point.value_type === "forecast_like_synthetic" ? "Forecast-like" : "Actual-like"}</td><td>{point.row}</td></tr>)}</tbody>
  </table></div>;
}

export function MonthlyHistory({ view }: { view: ReportView }) {
  const history = view.history;
  if (!history?.points.length) return null;
  return <section className="bf-monthly" aria-label="Monthly history"><h3>Monthly history</h3>
    <p className="bf-origin">{month(history.start_period)} – {month(history.end_period)} · {history.unit === "€m" ? "EUR millions" : history.unit === "%" ? "Percent" : "Units shipped"} · Synthetic records</p>
    {view.display_mode === "table" ? <HistoryTable history={history} /> : <>
      <PulseChart title={view.title} unit={history.unit} points={history.points} source={history.sheet} />
      <details className="bf-disclosure"><summary>Exact monthly values and workbook rows</summary><HistoryTable history={history} /></details>
    </>}
  </section>;
}
