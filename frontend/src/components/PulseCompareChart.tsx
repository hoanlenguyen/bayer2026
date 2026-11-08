import { scaleLinear } from "d3";
import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import type { PulsePoint } from "./PulseChart";
import "./pulse-chart.css";

/** One metric, several markets (or any peers) as separate lines in the Monthly Pulse style, with a legend.
 *  Each peer has its own colour, line style and marker, so colour is never the only cue. */
export interface PulseSeries { label: string; points: readonly PulsePoint[] }

const PEERS = [
  { color: "var(--pc-teal)", dash: undefined, marker: "circle" },
  { color: "var(--pc-amber)", dash: "7 4", marker: "square" },
  { color: "var(--pc-violet)", dash: "2 3", marker: "diamond" },
] as const;

const numbers = new Intl.NumberFormat("en-GB", { maximumFractionDigits: 2 });
const tickNumbers = new Intl.NumberFormat("en-GB", { notation: "compact", maximumFractionDigits: 1 });
const monthShort = new Intl.DateTimeFormat("en-GB", { month: "short", timeZone: "UTC" });
const monthYear = new Intl.DateTimeFormat("en-GB", { month: "short", year: "numeric", timeZone: "UTC" });
const currency = (unit: string) => /^(€m|m eur|eur m|eur million|million eur)$/i.test(unit);
const percent = (unit: string) => /^(%|percent|pct)$/i.test(unit);
const monthDate = (period: string) => new Date(period.slice(0, 7) + "-01T00:00:00Z");
const monthNumber = (period: string) => Number(period.slice(0, 4)) * 12 + Number(period.slice(5, 7)) - 1;
const finite = (v: number | null | undefined): v is number => v != null && Number.isFinite(v);

function displayValue(value: number, unit: string) {
  if (currency(unit)) return `€${value.toFixed(2)}m`;
  if (percent(unit)) return `${numbers.format(value)}%`;
  return [numbers.format(value), unit].filter(Boolean).join(" ");
}

function changeLabel(current: number, previous: number, unit: string) {
  const change = current - previous;
  if (!change) return "No change";
  const sign = change > 0 ? "+" : "−";
  if (percent(unit)) return `${sign}${numbers.format(Math.abs(change))} pp`;
  if (previous > 0) return `${sign}${(100 * Math.abs(change) / previous).toFixed(1)}%`;
  return sign + displayValue(Math.abs(change), unit);
}

function Marker({ kind, x, y, r, color, hollow }: { kind: string; x: number; y: number; r: number; color: string; hollow?: boolean }) {
  const style = { fill: hollow ? "var(--pc-ink)" : color, stroke: color, strokeWidth: 1.5 };
  if (kind === "square") return <rect x={x - r} y={y - r} width={2 * r} height={2 * r} style={style} />;
  if (kind === "diamond") return <path d={`M${x},${y - r * 1.3} L${x + r * 1.3},${y} L${x},${y + r * 1.3} L${x - r * 1.3},${y} Z`} style={style} />;
  return <circle cx={x} cy={y} r={r} style={style} />;
}

export function PulseCompareChart({ title, unit, series: input, source }: { title: string; unit: string; series: PulseSeries[]; source?: string }) {
  const series = useMemo(() => input.slice(0, PEERS.length).map(s => ({
    label: s.label,
    points: s.points.filter(p => finite(p.value) && /^\d{4}-(0[1-9]|1[0-2])/.test(p.period)).slice().sort((a, b) => a.period.localeCompare(b.period)),
  })).filter(s => s.points.length > 0), [input]);
  const periods = useMemo(() => [...new Set(series.flatMap(s => s.points.map(p => p.period.slice(0, 7))))].sort(), [series]);
  const frame = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(640);
  const [picked, setPicked] = useState<string>();
  const id = useId();
  useEffect(() => {
    const element = frame.current;
    if (!element) return;
    const resize = () => setWidth(Math.max(1, Math.floor(element.clientWidth)));
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(element);
    return () => observer.disconnect();
  }, [periods.length > 0]);
  if (!periods.length) return null;

  const last = periods.length - 1;
  const index = periods.indexOf(picked ?? "");
  const selected = index < 0 ? last : index;
  const month = periods[selected];
  const at = (s: (typeof series)[number], period: string) => s.points.find(p => p.period.slice(0, 7) === period);
  const height = 190;
  const left = currency(unit) ? 46 : 44, right = Math.max(left + 1, width - 15), top = 10, bottom = height - 25;
  const start = monthNumber(periods[0]), end = monthNumber(periods[last]);
  const x = (period: string) => end > start ? left + (right - left) * (monthNumber(period) - start) / (end - start) : (left + right) / 2;
  const values = series.flatMap(s => s.points.flatMap(p => finite(p.forecast) ? [p.value, p.forecast] : [p.value]));
  const observedLow = Math.min(...values), observedHigh = Math.max(...values);
  const localPercent = percent(unit) && observedLow >= 50 && observedHigh <= 100 && observedHigh - observedLow < 35;
  const high = localPercent ? Math.min(100, Math.ceil((observedHigh + 2) / 10) * 10) : Math.max(1, observedHigh, percent(unit) ? 100 : 0);
  const low = localPercent ? Math.min(high - 20, Math.floor((observedLow - 2) / 10) * 10) : Math.min(0, observedLow);
  const y = scaleLinear().domain([low, high]).nice(3).range([bottom, top]);
  const [axisMin, axisMax] = y.domain();
  const axisValue = (v: number) => currency(unit) ? `€${tickNumbers.format(v)}m` : tickNumbers.format(v) + (percent(unit) ? "%" : "");
  const hasForecast = series.some(s => s.points.some(p => finite(p.forecast)));
  // Break lines at missing months instead of drawing across them.
  function path(points: readonly PulsePoint[], forecast: boolean) {
    let d = "", previous = -2;
    for (const p of points) {
      const v = forecast ? p.forecast : p.value;
      if (!finite(v)) { previous = -2; continue; }
      const m = monthNumber(p.period);
      d += `${m === previous + 1 ? " L" : " M"}${x(p.period)},${y(v)}`;
      previous = m;
    }
    return d.trim();
  }
  let previousTick = -Infinity;
  const labelled = periods.map((p, i) => {
    const px = x(p);
    if (i !== last && (px < previousTick + 38 || px > x(periods[last]) - 38)) return false;
    previousTick = px; return true;
  });
  const reading = series.map(s => {
    const p = at(s, month);
    return p ? `${s.label} ${displayValue(p.value, unit)}${finite(p.forecast) ? `, forecast ${displayValue(p.forecast, unit)}` : ""}` : `${s.label} no value`;
  }).join("; ");
  const inspect = (i: number) => setPicked(periods[Math.min(last, Math.max(0, i))]);
  function trackPointer(event: PointerEvent<HTMLDivElement>) {
    const px = event.clientX - event.currentTarget.getBoundingClientRect().left;
    inspect(periods.reduce((best, p, i) => Math.abs(x(p) - px) < Math.abs(x(periods[best]) - px) ? i : best, 0));
  }
  function trackKey(event: KeyboardEvent<HTMLDivElement>) {
    const keys: Record<string, number> = { ArrowLeft: selected - 1, ArrowDown: selected - 1, ArrowRight: selected + 1, ArrowUp: selected + 1, Home: 0, End: last };
    if (event.key in keys) { event.preventDefault(); inspect(keys[event.key]); }
  }
  const rows = series.flatMap(s => { const p = at(s, month); return p?.row != null ? [`${s.label} row ${p.row}`] : []; });

  return <figure className="pulse-chart pulse-compare" aria-labelledby={`${id}-title`}>
    <header className="pc-heading">
      <div className="pc-identity"><span className="pc-mark" aria-hidden="true" /><div>
        <span className="pc-overline">Monthly pulse · Synthetic workbook</span><h3 id={`${id}-title`}>{title}</h3>
        <p className="pc-scope">{series.map(s => s.label).join(" and ")}</p></div></div>
    </header>
    <div className="pcc-latest">{series.map((s, i) => {
      const latest = s.points[s.points.length - 1], previous = s.points[s.points.length - 2];
      return <div key={s.label} className="pcc-peer">
        <span className="pcc-peer-name"><i className="pcc-swatch" style={{ borderColor: PEERS[i].color, borderTopStyle: PEERS[i].dash ? "dashed" : "solid" }} aria-hidden="true" />{s.label}</span>
        <strong className="pcc-value">{displayValue(latest.value, unit)}</strong>
        <span className="pc-context"><span>{monthYear.format(monthDate(latest.period))}</span>
          {previous && <span className="pc-delta"><b>{changeLabel(latest.value, previous.value, unit)}</b> vs {monthShort.format(monthDate(previous.period))}</span>}</span>
      </div>;
    })}</div>
    <div className="pc-plot" ref={frame} role="slider" tabIndex={0} aria-label={`Inspect ${title} by month`}
      aria-valuemin={1} aria-valuemax={periods.length} aria-valuenow={selected + 1}
      aria-valuetext={`${monthYear.format(monthDate(month))}: ${reading}`} onKeyDown={trackKey} onPointerDown={trackPointer}
      onPointerMove={e => { if (e.pointerType === "mouse" || e.buttons > 0) trackPointer(e); }}>
      <svg viewBox={`0 0 ${width} ${height}`} style={{ height }} aria-hidden="true" focusable="false">
        {y.ticks(3).map(v => <g key={v}><line className="pc-gridline" x1={left} y1={y(v)} x2={right} y2={y(v)} />
          <text className="pc-axis" x={left - 7} y={y(v) + 4} textAnchor="end">{axisValue(v)}</text></g>)}
        {series.map((s, i) => hasForecast && <path key={`f${s.label}`} d={path(s.points, true)} fill="none" stroke={PEERS[i].color}
          strokeWidth={1.4} strokeDasharray="2 4" strokeOpacity={0.75} strokeLinecap="round" />)}
        {series.map((s, i) => <path key={s.label} d={path(s.points, false)} fill="none" stroke={PEERS[i].color} strokeWidth={2.5}
          strokeDasharray={PEERS[i].dash} strokeLinejoin="round" strokeLinecap="round" />)}
        <line className="pc-cursor" x1={x(month)} x2={x(month)} y1={top} y2={bottom} />
        {periods.map((p, i) => labelled[i] && <text key={p} className="pc-axis" x={x(p)} y={bottom + 18} textAnchor="middle">{monthShort.format(monthDate(p))}</text>)}
        {series.map((s, i) => s.points.map(p => <Marker key={`${s.label}${p.period}`} kind={PEERS[i].marker} x={x(p.period)} y={y(p.value)}
          r={p.period.slice(0, 7) === month ? 4.5 : 2.8} color={PEERS[i].color} hollow={p.value_type === "forecast_like_synthetic"} />))}
      </svg>
    </div>
    <div className="pc-reader">
      <div className="pc-reading"><span className="pc-period">{monthYear.format(monthDate(month))}</span>
        {series.map((s, i) => { const p = at(s, month); return <span key={s.label} className="pcc-reading">
          <i className="pcc-swatch" style={{ borderColor: PEERS[i].color, borderTopStyle: PEERS[i].dash ? "dashed" : "solid" }} aria-hidden="true" />
          {s.label} <strong>{p ? displayValue(p.value, unit) : "No value"}</strong>
          {p && finite(p.forecast) && <span className="pcc-forecast">forecast {displayValue(p.forecast, unit)}</span>}</span>; })}
      </div>
      {periods.length > 1 && <div className="pc-nav"><button type="button" aria-label="Inspect previous month" disabled={selected === 0} onClick={() => inspect(selected - 1)}>‹</button>
        <button type="button" aria-label="Inspect next month" disabled={selected === last} onClick={() => inspect(selected + 1)}>›</button></div>}
    </div>
    <figcaption className="pc-foot">
      <span>{[source, ...rows].filter(Boolean).join(" · ")}</span>
      <span className="pc-legend" aria-label="Legend">
        {series.map((s, i) => <span key={s.label} className="pc-key">
          <svg width="26" height="10" aria-hidden="true"><line x1="1" y1="5" x2="25" y2="5" stroke={PEERS[i].color} strokeWidth="2.5" strokeDasharray={PEERS[i].dash} />
            <Marker kind={PEERS[i].marker} x={13} y={5} r={3} color={PEERS[i].color} /></svg>{s.label}</span>)}
        {hasForecast && <span className="pc-key"><svg width="26" height="10" aria-hidden="true"><line x1="1" y1="5" x2="25" y2="5" stroke="var(--pc-quiet)" strokeWidth="1.4" strokeDasharray="2 4" /></svg>Forecast</span>}
        {series.some(s => s.points.some(p => p.value_type === "forecast_like_synthetic")) && <span className="pc-key"><i className="pc-key-open" aria-hidden="true" /> Forecast-like record</span>}
        {localPercent && <span>Scale {axisMin}–{axisMax}%</span>}
      </span>
    </figcaption>
  </figure>;
}
