import { useEffect, useId, useRef, useState, type MouseEvent, type ReactNode } from "react";
import { handoffPath, readHandoff, type DecisionHandoff } from "../api/handoff";
import type { DashboardObservation, SavedDashboard, SourceRecord } from "../api/dashboardBuilder";
import { PulseDashboard } from "../components/PulseDashboard";
import { ReceiptDetails, ReceiptFacts } from "../components/ask/BuildHandoff";
import { bi } from "../api/biEstate";
import { openConversation } from "../lib/conversations";
import { navigate } from "../lib/navigation";
import "./saved-dashboard.css";

interface Column { id: string; name: string; unit: string; field: string }
interface Group { label: string; points: DashboardObservation[] }

const periodName = (period: string) => new Date(period.slice(0, 7) + "-01T00:00:00Z").toLocaleDateString("en-GB", {
  month: "short", year: "numeric", timeZone: "UTC",
});
const recordKinds = (types: string[]) => types.map(type => type === "actual_like_synthetic" ? "Actual-like"
  : type === "forecast_like_synthetic" ? "Forecast-like" : type).join(" / ");
const pretty = (text: string) => text.replaceAll("_", " ");

function useRecord<T>(path: string) {
  const [record, setRecord] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    setError("");
    readHandoff<T>(path).then(value => { if (active) setRecord(value); }).catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [path, attempt]);
  return { record, error, retry: () => setAttempt(n => n + 1) };
}

function Status({ error, retry }: { error: string; retry: () => void }) {
  return <main className="sd-page" role={error ? "alert" : "status"}>{error
    ? <><h1>Could not open this view</h1><p>{error}</p><button type="button" className="btn-outline" onClick={retry}>Retry opening dashboard</button></>
    : <p>Opening dashboard…</p>}</main>;
}

function PageHeader({ name, kind, description, conversationId }: { name: string; kind: string; description: string; conversationId: string }) {
  const [copyState, setCopyState] = useState<"idle" | "copied" | "manual">("idle");
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { document.title = name + " · AnalytIQ intelligence"; }, [name]);
  // Arriving from a build: move focus to the dashboard, once per history entry.
  useEffect(() => {
    const state = (history.state ?? {}) as { focusHeading?: boolean };
    if (!state.focusHeading) return;
    heading.current?.focus();
    try { history.replaceState({ ...state, focusHeading: false }, ""); } catch { /* focus once per mount instead */ }
  }, []);
  async function copy() {
    try { await navigator.clipboard.writeText(window.location.href); setCopyState("copied"); }
    catch { setCopyState("manual"); }
  }
  function back(event: MouseEvent<HTMLAnchorElement>) {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    openConversation(conversationId); navigate(event);
  }
  return <header className="sd-header"><div className="sd-toolbar"><a href="/#ask" onClick={back}>← Open source conversation</a>
    <button type="button" className="btn-outline" onClick={() => void copy()}>{copyState === "copied" ? "Link copied" : "Copy link"}</button></div>
    {copyState === "manual" && <label className="sd-link-field">Dashboard link<input readOnly value={window.location.href} onFocus={e => e.currentTarget.select()}/></label>}
    <p className="sd-kicker">{kind} · Synthetic workbook</p><h1 ref={heading} tabIndex={-1}>{name}</h1><p className="sd-subtitle">{description}</p>
  </header>;
}

function DashboardData({ groups, columns, source, tableOnly = false, scope }: { groups: Group[]; columns: Column[]; source: string; tableOnly?: boolean; scope?: string }) {
  const [groupIndex, setGroupIndex] = useState(0);
  const [months, setMonths] = useState(0);
  const group = groups[groupIndex] ?? groups[0];
  const id = useId();
  if (!group) return <p role="status">No workbook observations were saved for this scope.</p>;
  const groupLabel = group.label === "Selected scope" && scope ? scope : group.label;
  const points = months ? group.points.slice(-months) : group.points;
  const metrics = columns.filter(col => col.id !== "sales_forecast" || !columns.some(c => c.id === "net_sales")).map(col => ({
    id: col.id, title: col.name, unit: col.unit,
    points: points.filter(point => Number.isFinite(point.values[col.id])).map(point => ({
      period: point.period, value: point.values[col.id],
      row: point.source_rows.length === 1 ? point.source_rows[0] : undefined,
      value_type: point.value_types.length === 1 ? point.value_types[0] : undefined,
      forecast: col.id === "net_sales" ? point.values.sales_forecast : undefined,
    })),
  }));
  return <section className="sd-data" aria-labelledby={id}>
    <div className="sd-section-head"><div><h2 id={id}>Monthly results</h2><p>{groupLabel} · {points.length} {points.length === 1 ? "period" : "periods"}</p></div>
      <div className="sd-filters">
        {groups.length > 1 && <label><span>Group</span><select aria-label="Dashboard group" value={groupIndex} onChange={e => setGroupIndex(Number(e.target.value))}>
          {groups.map((g, i) => <option key={g.label} value={i}>{g.label}</option>)}</select></label>}
        {group.points.length > 3 && <label><span>Period</span><select aria-label="Displayed periods" value={months} onChange={e => setMonths(Number(e.target.value))}>
          <option value={0}>All {group.points.length} months</option>{group.points.length > 6 && <option value={6}>Latest 6 months</option>}<option value={3}>Latest 3 months</option>
        </select></label>}
      </div>
    </div>
    {!tableOnly && <PulseDashboard metrics={metrics} scope={groupLabel} source={source}/>}
    <div className="sd-table-region" role="region" aria-label="Monthly values and workbook rows" tabIndex={0}>
      <table><caption>Values and source rows · {source}</caption><thead><tr><th scope="col">Month</th>
        {columns.map(c => <th scope="col" key={c.id}>{c.name} <small>{c.unit}</small></th>)}<th scope="col">Record type</th><th scope="col">Sheet rows</th>
      </tr></thead><tbody>{points.map(point => <tr key={point.period}><th scope="row">{periodName(point.period)}</th>
        {columns.map(c => <td key={c.id}>{Number.isFinite(point.values[c.id]) ? point.values[c.id].toLocaleString("en-GB", { maximumFractionDigits: 4 }) : "—"}</td>)}
        <td>{recordKinds(point.value_types)}</td><td>{point.source_rows.length > 4
          ? <details><summary>{point.source_rows.length} rows</summary>{point.source_rows.join(", ")}</details> : point.source_rows.join(", ")}</td>
      </tr>)}</tbody></table>
    </div>
  </section>;
}

function SourceLookup({ records }: { records: SourceRecord[] }) {
  const [row, setRow] = useState(String(records[0]?.row ?? ""));
  if (!records.length) return null;
  const record = records.find(entry => String(entry.row) === row);
  return <section className="sd-row-lookup"><label>Inspect workbook row <input type="number" min={2} value={row}
    onChange={e => setRow(e.target.value)}/></label>
    {record ? <><p>{record.product_id} · {record.market_id} · {periodName(record.month)} · {recordKinds([record.value_type])}</p>
      <dl>{Object.entries(record).filter(([field]) => !["row", "product_id", "market_id", "month", "value_type"].includes(field))
        .map(([field, value]) => <div key={field}><dt><code>{field}</code></dt><dd>{String(value)}</dd></div>)}</dl></>
      : <p>No source row {row || "selected"} in this dashboard snapshot.</p>}
  </section>;
}

function SourceNotes({ children }: { children: ReactNode }) {
  return <details className="sd-sources"><summary>Dashboard brief and sources</summary><div>{children}</div></details>;
}

/** One ID per history entry, so a remount, re-render or reload of the same view is not counted twice. */
function viewIdForThisEntry(): string {
  const state = (history.state ?? {}) as { analytiqView?: string };
  if (state.analytiqView) return state.analytiqView;
  const id = (crypto.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`).replace(/[^A-Za-z0-9_-]/g, "");
  try { history.replaceState({ ...state, analytiqView: id }, ""); } catch { /* counted per mount instead */ }
  return id;
}

/** Record an AnalytIQ open once the dashboard is rendered and the tab is visible. Never blocks the dashboard. */
function useRecordOpen(assetId: string, rendered: boolean) {
  useEffect(() => {
    if (!rendered) return;
    const viewId = viewIdForThisEntry();
    let sent = false;
    const send = () => {
      if (sent || document.visibilityState !== "visible") return;
      sent = true;
      bi.recordOpen(assetId, viewId).catch(() => undefined);
    };
    send();
    document.addEventListener("visibilitychange", send);
    return () => document.removeEventListener("visibilitychange", send);
  }, [assetId, rendered]);
}

export function SavedDashboardPage({ id }: { id: string }) {
  const { record, error, retry } = useRecord<SavedDashboard>(`/api/dashboards/${encodeURIComponent(id)}`);
  useRecordOpen(id, record !== null);
  if (!record) return <Status error={error} retry={retry}/>;
  const { period, scope } = record;
  const scopedNames = (values: string[], label: string) => values.length > 3 ? `${values.length} ${label}` : values.join(", ");
  const places = [scopedNames(scope.products, "products"), scopedNames(scope.markets, "markets")].filter(Boolean).join(" · ");
  return <main className="sd-page">
    <PageHeader name={record.title} description={record.decision_goal} kind="Saved dashboard" conversationId={record.conversation_id}/>
    <div className="sd-meta"><span>{places}</span><span>{periodName(period.start)} – {periodName(period.end)}</span>
      <span>{record.columns.length} governed {record.columns.length === 1 ? "KPI" : "KPIs"}</span></div>
    <DashboardData groups={record.groups} columns={record.columns} source={record.source} scope={places}/>
    <SourceNotes>{record.receipt && <section className="sd-receipt" aria-label="What this dashboard holds">
        <p><strong>Built from the approved brief</strong></p><ReceiptFacts receipt={record.receipt} saved/><ReceiptDetails receipt={record.receipt}/>
        {record.created_by && <p>Built by {record.created_by.name}</p>}</section>}
      <p><strong>Original request</strong><br/>{record.request}</p>
      <p><strong>Scope</strong><br/>{scope.products.join(", ")} · {scope.markets.join(", ")}</p>
      {record.omitted_measures?.length > 0 && <p><strong>Outside this dashboard</strong><br/>{record.omitted_measures.map(pretty).join(", ")}</p>}
      <p><strong>Measures</strong></p><ul>{record.columns.map(col => <li key={col.id}>{col.name} ({col.kpi_id}) · {pretty(col.aggregation)} · <code>{col.field}</code></li>)}</ul>
      <p>Workbook sheet <code>{record.source}</code> · Created {new Date(record.created_at).toLocaleString()} · Decision <code>{record.run_id}</code></p>
      {record.storage_mode === "memory" && <p>Demo storage · This link is available until the server restarts.</p>}
      <SourceLookup records={record.source_records}/>
    </SourceNotes>
  </main>;
}

export function WorkbookViewPage({ conversationId, runId }: { conversationId: string; runId: string }) {
  const { record, error, retry } = useRecord<DecisionHandoff>(handoffPath(conversationId, runId));
  if (!record) return <Status error={error} retry={retry}/>;
  const series = record.metric_series;
  if (!series || record.current_review || (record.handoff_verdict || record.verdict) !== "reuse") {
    return <main className="sd-page"><PageHeader name="Workbook view unavailable" kind="Decision record" conversationId={conversationId}
      description={record.current_review?.reason || "This decision does not have a verified workbook series."}/></main>;
  }
  const groups = [{ label: `${series.product} · ${series.market}`, points: series.points.map(p => ({
    period: p.period, values: p.values, source_rows: [p.row], value_types: [p.value_type],
  })) }];
  return <main className="sd-page">
    <PageHeader name={record.candidate?.name || record.employee_report?.title || "Workbook view"} kind="Verified workbook view"
      description={`${series.product} · ${series.market} · ${series.columns.map(col => col.name).join(", ")}`} conversationId={conversationId}/>
    <DashboardData columns={series.columns} groups={groups} source={series.source} tableOnly={series.display_mode === "table"}/>
    <SourceNotes><p><strong>Original request</strong><br/>{record.question}</p><p>{record.reason}</p>
      {record.candidate && <p>Imported catalog record · <a href={`/briefings?report=${encodeURIComponent(record.candidate.asset_id)}`} onClick={navigate}>{record.candidate.asset_id}</a></p>}
      {record.source_refs.map(ref => <p key={`${ref.id}-${ref.row}`}><strong>{ref.sheet} · Row {ref.row}</strong><br/>{ref.detail}</p>)}
      <p>Decision <code>{runId}</code></p></SourceNotes>
  </main>;
}
