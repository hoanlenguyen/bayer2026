import type { ReportHistory, ReportView } from "../api/briefings";
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

function TrendChart({ history }: { history: ReportHistory }) {
  const { points, unit } = history;
  const left = 58, right = 474, top = 13, bottom = 126;
  const values = points.flatMap(point => point.forecast == null ? [point.value] : [point.value, point.forecast]);
  const peak = Math.max(1, ...values);
  const step = 10 ** Math.floor(Math.log10(peak));
  const max = unit === "%" ? 100 : Math.ceil(peak / step) * step;
  const x = (index: number) => left + (right - left) * index / Math.max(1, points.length - 1);
  const y = (value: number) => bottom - value / max * (bottom - top);
  const series = points.map((point, i) => `${x(i)},${y(point.value)}`).join(" ");
  const forecasts = points.map((point, i) => point.forecast == null ? "" : `${x(i)},${y(point.forecast)}`).filter(Boolean).join(" ");
  const axis = (v: number) => v === 0 ? "0" : unit === "€m" ? `€${v}m` : unit === "%" ? `${v}%` : new Intl.NumberFormat("en-GB", { notation: "compact" }).format(v);
  return <figure className="bf-trend">
    <svg viewBox="0 0 494 157" role="img" aria-label={`Monthly ${unit} values from ${month(history.start_period)} to ${month(history.end_period)}. Exact values follow in the table.`}>
      {[0, max / 2, max].map(v => <g key={v}><line className="bf-axis-line" x1={left} y1={y(v)} x2={right} y2={y(v)} />
        <text x={left - 9} y={y(v) + 4} textAnchor="end">{axis(v)}</text></g>)}
      {forecasts && <polyline className="bf-forecast-line" points={forecasts} />}
      <polyline className="bf-series-line" points={series} />
      {points.map((point, i) => <g key={point.row}>
        <circle className={point.value_type === "forecast_like_synthetic" ? "bf-forecast-point" : "bf-actual-point"} cx={x(i)} cy={y(point.value)} r={3.5}/>
        <text textAnchor="middle" x={x(i)} y={bottom + 19}>{month(point.period, true)}</text>
      </g>)}
    </svg>
    <figcaption><span><i className="bf-key-dot" /> Actual-like</span><span><i className="bf-key-dot bf-hollow" /> Forecast-like</span>
      {forecasts && <span><i className="bf-key-line" /> Sales forecast</span>}</figcaption>
  </figure>;
}

export function MonthlyHistory({ view }: { view: ReportView }) {
  const history = view.history;
  if (!history?.points.length) return null;
  return <section className="bf-monthly" aria-label="Monthly history"><h3>Monthly history</h3>
    <p className="bf-origin">{month(history.start_period)} – {month(history.end_period)} · {history.unit === "€m" ? "EUR millions" : history.unit === "%" ? "Percent" : "Units shipped"} · Synthetic records</p>
    {view.display_mode === "table" ? <HistoryTable history={history} /> : <>
      <TrendChart history={history} />
      <details className="bf-disclosure"><summary>Exact monthly values and workbook rows</summary><HistoryTable history={history} /></details>
    </>}
  </section>;
}
