import { useId, useMemo, useState, type KeyboardEvent } from "react";
import type { SavedDashboard, SourceRecord } from "../api/dashboardBuilder";
import "./market-comparison.css";

/* Two countries, two governed KPIs, one month grain: the saved view of a guided example. Every plotted value is one
   workbook row; the month inspector shows both countries' values with those rows. Different units never share a scale. */

type Column = SavedDashboard["columns"][number];
interface Point { period: string; value: number; row?: number; type?: string }

const monthShort = new Intl.DateTimeFormat("en-GB", { month: "short", timeZone: "UTC" });
const monthLong = new Intl.DateTimeFormat("en-GB", { month: "long", year: "numeric", timeZone: "UTC" });
const date = (p: string) => new Date(p.slice(0, 7) + "-01T00:00:00Z");
const isCurrency = (u: string) => /^(m eur|€m|eur m)$/i.test(u);
const isPercent = (u: string) => /^(%|percent)$/i.test(u);
const nf = (d: number) => new Intl.NumberFormat("en-GB", { maximumFractionDigits: d, minimumFractionDigits: d });

export const displayUnit = (unit: string) => isCurrency(unit) ? "€m" : unit;

export function formatValue(v: number, unit: string) {
  if (isCurrency(unit)) return `€${nf(2).format(v)}m`;
  if (isPercent(unit)) return `${nf(1).format(v)}%`;
  if (/^units?$/i.test(unit)) return `${nf(0).format(v)} units`;
  return `${nf(2).format(v)} ${unit}`;
}
function formatChange(d: number, unit: string) {
  const sign = d > 0 ? "+" : d < 0 ? "−" : "±";
  const a = Math.abs(d);
  if (isCurrency(unit)) return `${sign}€${nf(2).format(a)}m`;
  if (isPercent(unit)) return `${sign}${nf(1).format(a)} percentage points`;
  if (/^units?$/i.test(unit)) return `${sign}${nf(0).format(a)} units`;
  return `${sign}${nf(2).format(a)} ${unit}`;
}
const recordType = (t?: string) => t === "actual_like_synthetic" ? "Actual-like" : t === "forecast_like_synthetic" ? "Forecast-like" : (t ?? "Unknown");

export function MarketComparison({ record }: { record: SavedDashboard }) {
  const order = record.market_order ?? record.groups.map((g) => g.label);
  const groups = [...record.groups].sort((a, b) => order.indexOf(a.label) - order.indexOf(b.label));
  const columns = [...record.columns].sort((a, b) => Number(b.id === record.lead_measure) - Number(a.id === record.lead_measure));
  const lead = columns[0];
  const periods = useMemo(() => [...new Set(groups.flatMap((g) => g.points.map((p) => p.period)))].sort(), [groups]);
  const [selected, setSelected] = useState(periods.length - 1);
  const month = periods[selected];
  const series = (col: Column, label: string): Point[] => (groups.find((g) => g.label === label)?.points ?? [])
    .filter((p) => Number.isFinite(p.values[col.id]))
    .map((p) => ({ period: p.period, value: p.values[col.id], row: p.source_rows.length === 1 ? p.source_rows[0] : undefined,
                   type: p.value_types.length === 1 ? p.value_types[0] : undefined }));
  const at = (col: Column, label: string, period: string) => series(col, label).find((p) => p.period === period);
  const last = periods[periods.length - 1];
  const prior = periods[periods.length - 2];
  const rowsById = new Map(record.source_records.map((r) => [r.row, r]));

  return <section className="mc" aria-label="Country comparison">
    <div className="mc-summary">{columns.map((col) => <article key={col.id} className={col === lead ? "mc-kpi mc-lead" : "mc-kpi"}>
      <h3>{col.name}{col === lead && <span className="mc-tag">Lead metric</span>}</h3>
      <p className="mc-sub">{monthLong.format(date(last))}{prior && ` · change from ${monthLong.format(date(prior))}`}</p>
      <dl>{order.map((label, i) => {
        const now = at(col, label, last), before = prior ? at(col, label, prior) : undefined;
        return <div key={label}><dt><span className={`mc-swatch mc-s${i}`} aria-hidden="true" />{label}</dt>
          <dd><strong>{now ? formatValue(now.value, col.unit) : "No value"}</strong>
            {now && before && <span className="mc-change">{formatChange(now.value - before.value, col.unit)}</span>}</dd></div>;
      })}</dl>
    </article>)}</div>

    <LeadBars col={lead} order={order} values={order.map((l) => at(lead, l, last)?.value)} month={last} />

    <div className="mc-panels">{columns.map((col) => <TrendPanel key={col.id} col={col} order={order} periods={periods}
      series={order.map((l) => series(col, l))} selected={selected} onSelect={setSelected} lead={col === lead} />)}</div>

    <section className="mc-inspect" aria-live="polite" aria-labelledby="mc-inspect-title">
      <h3 id="mc-inspect-title">{monthLong.format(date(month))}: both countries</h3>
      <div className="mc-months" role="group" aria-label="Choose a month">
        {periods.map((p, i) => <button key={p} type="button" aria-pressed={i === selected} onClick={() => setSelected(i)}>{monthShort.format(date(p))}</button>)}
      </div>
      <div className="mc-table" role="region" aria-label="Selected month values and workbook rows" tabIndex={0}>
        <table><thead><tr><th scope="col">Country</th>{columns.map((c) => <th key={c.id} scope="col">{c.name}</th>)}<th scope="col">Record type</th><th scope="col">Workbook row</th></tr></thead>
          <tbody>{order.map((label) => {
            const pts = columns.map((c) => at(c, label, month));
            const row = pts.find((p) => p?.row)?.row;
            return <tr key={label}><th scope="row">{label}</th>{columns.map((c, i) => <td key={c.id}>{pts[i] ? formatValue(pts[i]!.value, c.unit) : "No value"}</td>)}
              <td>{recordType(pts[0]?.type)}</td><td>{row ? <RowDetails row={row} record={rowsById.get(row)} sheet={record.source} /> : "Not recorded"}</td></tr>;
          })}</tbody></table>
      </div>
      <p className="mc-note">Synthetic workbook observations. A change is the measured difference between two months, not a cause.</p>
    </section>
  </section>;
}

function RowDetails({ row, record, sheet }: { row: number; record?: SourceRecord; sheet: string }) {
  return <details className="mc-row"><summary>Row {row}</summary>
    {record ? <dl>{Object.entries(record).filter(([k]) => k !== "row").map(([k, v]) => <div key={k}><dt><code>{k}</code></dt><dd>{String(v)}</dd></div>)}</dl>
      : <p>Row {row} of {sheet} is not in this snapshot.</p>}</details>;
}

function LeadBars({ col, order, values, month }: { col: Column; order: string[]; values: (number | undefined)[]; month: string }) {
  const max = Math.max(0, ...values.map((v) => v ?? 0)) || 1;
  return <section className="mc-bars" aria-label={`${col.name}, ${monthLong.format(date(month))}`}>
    <h3>{col.name} in {monthLong.format(date(month))}</h3>
    {order.map((label, i) => <div key={label} className="mc-bar">
      <span className="mc-bar-label">{label}</span>
      <span className="mc-bar-track"><span className={`mc-bar-fill mc-s${i}`} style={{ width: `${((values[i] ?? 0) / max) * 100}%` }} /></span>
      <span className="mc-bar-value">{values[i] !== undefined ? formatValue(values[i]!, col.unit) : "No value"}</span>
    </div>)}
  </section>;
}

const W = 640, H = 230, PAD = { l: 64, r: 16, t: 14, b: 30 };

function TrendPanel({ col, order, periods, series, selected, onSelect, lead }: {
  col: Column; order: string[]; periods: string[]; series: Point[][]; selected: number; onSelect: (i: number) => void; lead: boolean;
}) {
  const id = useId();
  const all = series.flat().map((p) => p.value);
  const lo = Math.min(...all), hi = Math.max(...all);
  const span = hi - lo || Math.abs(hi) || 1;
  // Values that are never negative get an axis that never goes below zero.
  const y0 = lo >= 0 ? Math.max(0, lo - span * 0.12) : lo - span * 0.12, y1 = hi + span * 0.12;
  const x = (i: number) => PAD.l + (periods.length > 1 ? (i / (periods.length - 1)) * (W - PAD.l - PAD.r) : (W - PAD.l - PAD.r) / 2);
  const y = (v: number) => PAD.t + (1 - (v - y0) / (y1 - y0 || 1)) * (H - PAD.t - PAD.b);
  const ticks = [0, 0.5, 1].map((f) => y0 + f * (y1 - y0));
  const key = (e: KeyboardEvent) => {
    if (e.key === "ArrowLeft" || e.key === "ArrowRight") { e.preventDefault(); onSelect(Math.max(0, Math.min(periods.length - 1, selected + (e.key === "ArrowLeft" ? -1 : 1)))); }
    if (e.key === "Home") { e.preventDefault(); onSelect(0); }
    if (e.key === "End") { e.preventDefault(); onSelect(periods.length - 1); }
  };
  const selectedText = order.map((l, i) => { const p = series[i].find((q) => q.period === periods[selected]); return `${l} ${p ? formatValue(p.value, col.unit) : "no value"}`; }).join(", ");
  return <figure className={lead ? "mc-panel mc-panel-lead" : "mc-panel"} aria-labelledby={`${id}-t`}>
    <figcaption id={`${id}-t`}><strong>{col.name}</strong> <span className="mc-unit">{displayUnit(col.unit)}{col.kpi_id && ` · ${col.kpi_id}`}</span>{lead && <span className="mc-tag">Lead metric</span>}</figcaption>
    <ul className="mc-legend" aria-label="Countries">{order.map((l, i) => <li key={l}><span className={`mc-key mc-s${i} mc-shape${i}`} aria-hidden="true" />{l}</li>)}</ul>
    <svg viewBox={`0 0 ${W} ${H}`} role="group" tabIndex={0} onKeyDown={key} className="mc-svg"
      aria-label={`${col.name} by month. Use the left and right arrow keys to choose a month. Selected ${monthLong.format(date(periods[selected]))}: ${selectedText}.`}>
      {ticks.map((t) => <g key={t}><line x1={PAD.l} x2={W - PAD.r} y1={y(t)} y2={y(t)} className="mc-grid" />
        <text x={PAD.l - 8} y={y(t) + 4} textAnchor="end" className="mc-axis">{formatValue(t, col.unit).replace(" units", "").replace(` ${col.unit}`, "")}</text></g>)}
      {periods.map((p, i) => <text key={p} x={x(i)} y={H - 8} textAnchor="middle" className="mc-axis">{monthShort.format(date(p))}</text>)}
      <line x1={x(selected)} x2={x(selected)} y1={PAD.t} y2={H - PAD.b} className="mc-cursor" />
      {series.map((pts, s) => <g key={order[s]} className={`mc-line mc-s${s}`}>
        <polyline fill="none" points={pts.map((p) => `${x(periods.indexOf(p.period))},${y(p.value)}`).join(" ")} strokeDasharray={s ? "6 4" : undefined} />
        {pts.map((p) => { const cx = x(periods.indexOf(p.period)), cy = y(p.value), r = periods.indexOf(p.period) === selected ? 5.5 : 3.5;
          return s ? <rect key={p.period} x={cx - r} y={cy - r} width={r * 2} height={r * 2} /> : <circle key={p.period} cx={cx} cy={cy} r={r} />; })}
      </g>)}
      {periods.map((p, i) => <rect key={p} x={x(i) - (W - PAD.l - PAD.r) / Math.max(1, periods.length - 1) / 2} y={PAD.t} height={H - PAD.t - PAD.b}
        width={(W - PAD.l - PAD.r) / Math.max(1, periods.length - 1)} className="mc-hit" onClick={() => onSelect(i)} />)}
    </svg>
  </figure>;
}
