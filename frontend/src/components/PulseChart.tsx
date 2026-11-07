import { scaleLinear } from "d3";
import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";
import "./pulse-chart.css";

export interface PulsePoint {
  period: string;
  value: number;
  forecast?: number | null;
  value_type?: string;
  row?: number;
}
export interface PulseChartProps {
  title: string;
  unit: string;
  points: readonly PulsePoint[];
  scope?: string;
  source?: string;
  compact?: boolean;
  controls?: ReactNode;
}

const numbers = new Intl.NumberFormat("en-GB", { maximumFractionDigits: 2 });
const tickNumbers = new Intl.NumberFormat("en-GB", { notation: "compact", maximumFractionDigits: 1 });
const monthShort = new Intl.DateTimeFormat("en-GB", { month: "short", timeZone: "UTC" });
const monthYear = new Intl.DateTimeFormat("en-GB", { month: "short", year: "numeric", timeZone: "UTC" });
const currency = (unit: string) => /^(€m|m eur|eur m|eur million|million eur)$/i.test(unit);
const percent = (unit: string) => /^(%|percent|pct)$/i.test(unit);
const monthDate = (period: string) => new Date(period.slice(0, 7) + "-01T00:00:00Z");
const monthNumber = (period: string) => Number(period.slice(0, 4)) * 12 + Number(period.slice(5, 7)) - 1;
const forecastLike = (point: PulsePoint) => point.value_type === "forecast_like_synthetic";

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

export function PulseChart({ title, unit, points, scope, source, compact = false, controls }: PulseChartProps) {
  const series = useMemo(() => points.filter(p => Number.isFinite(p.value) && /^\d{4}-(0[1-9]|1[0-2])(?:$|-)/.test(p.period))
    .slice().sort((a, b) => a.period.localeCompare(b.period)), [points]);
  const frame = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(480);
  const [pickedMonth, setPickedMonth] = useState<string>();
  const id = useId();
  useEffect(() => {
    const element = frame.current;
    if (!element) return;
    const resize = () => setWidth(Math.max(1, Math.floor(element.clientWidth)));
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(element);
    return () => observer.disconnect();
  }, [!!series.length]);
  if (!series.length) return null;

  const last = series.length - 1;
  const first = series[0], latest = series[last], previous = series[last - 1];
  const index = series.findIndex(p => p.period === pickedMonth);
  const selected = index < 0 ? last : index;
  const point = series[selected];
  const height = compact ? 118 : 164;
  const left = currency(unit) ? 46 : 40, right = Math.max(left + 1, width - 15), top = 10, bottom = height - 25;
  const startMonth = monthNumber(first.period), endMonth = monthNumber(latest.period);
  const months = series.map(p => monthNumber(p.period));
  const xs = months.map(m => endMonth > startMonth ? left + (right - left) * (m - startMonth) / (endMonth - startMonth) : (right + left) / 2);
  const hasForecast = series.some(p => p.forecast != null && Number.isFinite(p.forecast));
  const values = series.flatMap(p => p.forecast != null && Number.isFinite(p.forecast) ? [p.value, p.forecast] : [p.value]);
  const observedLow = Math.min(...values), observedHigh = Math.max(...values);
  // Use a labelled local range for delivery rates clustered near 100%.
  const localPercent = percent(unit) && observedLow >= 50 && observedHigh <= 100 && observedHigh - observedLow < 35;
  const high = localPercent ? Math.min(100, Math.ceil((observedHigh + 2) / 10) * 10) : Math.max(1, observedHigh, percent(unit) ? 100 : 0);
  const low = localPercent ? Math.min(high - 20, Math.floor((observedLow - 2) / 10) * 10) : Math.min(0, observedLow);
  const y = scaleLinear().domain([low, high]).nice(3).range([bottom, top]);
  const yTicks = y.ticks(3);
  const [axisMin, axisMax] = y.domain();
  const fillBase = y(Math.max(0, axisMin));
  const axisValue = (value: number) => currency(unit) ? `€${tickNumbers.format(value)}m`
    : tickNumbers.format(value) + (percent(unit) ? "%" : "");
  // Keep gaps in time and unavailable forecast values visible instead of interpolating across them.
  function paths(forecast: boolean) {
    const segments: { path: string; start: number; end: number }[] = [];
    let active = false;
    for (const [i, p] of series.entries()) {
      const v = forecast ? p.forecast : p.value;
      if (v == null || !Number.isFinite(v)) { active = false; continue; }
      if (!active || months[i] !== months[i - 1] + 1) segments.push({ path: `M${xs[i]},${y(v)}`, start: xs[i], end: xs[i] });
      else { const segment = segments[segments.length - 1]; segment.path += ` L${xs[i]},${y(v)}`; segment.end = xs[i]; }
      active = true;
    }
    return segments;
  }
  const segments = paths(false);
  const minTickWidth = 38;
  let previousTickX = -Infinity;
  const labelAt = xs.map((x, i) => {
    if (i !== last && (x < previousTickX + minTickWidth || x > xs[last] - minTickWidth)) return false;
    previousTickX = x; return true;
  });
  const selectedDate = monthYear.format(monthDate(point.period));
  const sourceRow = point.row != null ? `Row ${point.row}` : null;
  const recordKind = forecastLike(point) ? "Forecast-like record" : point.value_type === "actual_like_synthetic" ? "Actual-like record" : null;
  const accessibleValue = [selectedDate, displayValue(point.value, unit), point.forecast != null && `Forecast ${displayValue(point.forecast, unit)}`, recordKind, sourceRow].filter(Boolean).join(", ");
  const inspect = (i: number) => setPickedMonth(series[Math.min(last, Math.max(0, i))].period);
  function trackPointer(event: PointerEvent<HTMLDivElement>) {
    const x = event.clientX - event.currentTarget.getBoundingClientRect().left;
    inspect(xs.reduce((best, value, i) => Math.abs(value - x) < Math.abs(xs[best] - x) ? i : best, 0));
  }
  function trackKey(event: KeyboardEvent<HTMLDivElement>) {
    const keys: Record<string, number> = { ArrowLeft: selected - 1, ArrowDown: selected - 1, ArrowRight: selected + 1, ArrowUp: selected + 1, Home: 0, End: last };
    if (event.key in keys) { event.preventDefault(); inspect(keys[event.key]); }
  }
  return <figure className={`pulse-chart${compact ? " pulse-chart--compact" : ""}`} aria-labelledby={`${id}-title`}>
    <header className="pc-heading">
      <div className="pc-identity"><span className="pc-mark" aria-hidden="true" /><div>
        <span className="pc-overline">Monthly pulse · Synthetic workbook</span><h3 id={`${id}-title`}>{title}</h3>
        {scope && <p className="pc-scope">{scope}</p>}</div></div>
      {controls && <div className="pc-controls">{controls}</div>}
    </header>
    <div className="pc-headline"><strong className="pc-latest">{displayValue(latest.value, unit)}</strong>
      <div className="pc-context"><span>{monthYear.format(monthDate(latest.period))}</span>
        {previous && <span className="pc-delta" title={percent(unit) ? "Change in percentage points" : undefined}><b>{changeLabel(latest.value, previous.value, unit)}</b> vs {monthShort.format(monthDate(previous.period))}{previous.period.slice(0, 4) !== latest.period.slice(0, 4) && ` ${previous.period.slice(0, 4)}`}</span>}</div>
    </div>
    <div className="pc-plot" ref={frame} role="slider" tabIndex={0} aria-label={`Inspect ${title} by month`}
      aria-valuemin={1} aria-valuemax={series.length} aria-valuenow={selected + 1} aria-valuetext={accessibleValue}
      aria-describedby={`${id}-keys`} onKeyDown={trackKey} onPointerDown={trackPointer}
      onPointerMove={e => { if (e.pointerType === "mouse" || e.buttons > 0) trackPointer(e); }}>
      <svg viewBox={`0 0 ${width} ${height}`} style={{ height }} aria-hidden="true" focusable="false">
        <defs><linearGradient id={`${id}-wash`} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor="var(--pc-teal)" stopOpacity=".24" /><stop offset="100%" stopColor="var(--pc-teal)" stopOpacity=".015" />
        </linearGradient></defs>
        {yTicks.map(value => <g key={value}><line className="pc-gridline" x1={left} y1={y(value)} x2={right} y2={y(value)} />
          <text className="pc-axis" x={left - 7} y={y(value) + 4} textAnchor="end">{axisValue(value)}</text></g>)}
        {segments.map(s => <path key={s.start} d={s.path + ` L${s.end},${fillBase} L${s.start},${fillBase} Z`} fill={`url(#${id}-wash)`} />)}
        {hasForecast && paths(true).map(s => <path key={s.start} className="pc-forecast-line" d={s.path} />)}
        {segments.map(s => <path key={s.start} className="pc-value-line" d={s.path} />)}
        <line className="pc-cursor" x1={xs[selected]} x2={xs[selected]} y1={top} y2={bottom} />
        {series.map((p, i) => <g key={p.period}>
          {labelAt[i] && <text className="pc-axis" x={xs[i]} y={bottom + 18} textAnchor="middle">{monthShort.format(monthDate(p.period))}</text>}
          {i === selected && <circle key={title} className="pc-halo" cx={xs[i]} cy={y(p.value)} r={8} />}
          <circle className={forecastLike(p) ? "pc-marker pc-hollow" : "pc-marker"} cx={xs[i]} cy={y(p.value)} r={i === selected ? 4.5 : 2.7} />
        </g>)}
      </svg>
    </div>
    <span className="sr-only" id={`${id}-keys`}>Use the arrow keys to inspect months. Home selects the first month and End selects the latest.</span>
    <div className="pc-reader">
      <div className="pc-reading"><span className="pc-period">{selectedDate}</span><strong>{displayValue(point.value, unit)}</strong>
        {point.forecast != null && <span>Forecast {displayValue(point.forecast, unit)}</span>}</div>
      {series.length > 1 && <div className="pc-nav"><button type="button" aria-label="Inspect previous month" disabled={selected === 0} onClick={() => inspect(selected - 1)}>‹</button>
        <button type="button" aria-label="Inspect next month" disabled={selected === last} onClick={() => inspect(selected + 1)}>›</button></div>}
    </div>
    <figcaption className="pc-foot">
      <span>{[source, sourceRow, recordKind].filter(Boolean).join(" · ")}</span>
      <span className="pc-legend">
        {localPercent && <span>Scale {axisMin}–{axisMax}%</span>}
        {series.some(p => p.value_type === "actual_like_synthetic") && <span className="pc-key"><i className="pc-key-solid" aria-hidden="true" /> Actual-like</span>}
        {series.some(forecastLike) && <span className="pc-key"><i className="pc-key-open" aria-hidden="true" /> Forecast-like</span>}
        {hasForecast && <span className="pc-key"><i className="pc-key-dash" aria-hidden="true" /> Forecast</span>}
      </span>
    </figcaption>
  </figure>;
}
