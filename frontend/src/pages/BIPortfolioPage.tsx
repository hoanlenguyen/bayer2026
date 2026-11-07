import { useEffect, useId, useRef, useState, type FormEvent, type MouseEvent, type ReactNode } from "react";
import { bi, type Case, type Detail, type EstatePage, type IssueCode, type Kpi, type Pair, type Persona, type Row, type Side } from "../api/biEstate";
import { setActor, useActor } from "../lib/actor";
import "./bi-portfolio.css";

/* BI Portfolio: the BI department head's tracker of every reporting asset AnalytIQ can see.
   Routes: /bi-estate?…filters, /bi-estate/<asset id>?…, /bi-estate/compare/<a>/<b>?…  (filters stay in the query string). */

const ISSUE_ORDER: IssueCode[] = ["needs_owner", "consolidation", "definition", "scope", "refresh", "retirement", "chronology"];
const FILTERS = ["q", "origin", "platform", "issue", "lifecycle", "owner_state", "product", "market"] as const;
const SORTS: { key: string; label: string }[] = [
  { key: "issues", label: "Number of issues" }, { key: "title", label: "Title" }, { key: "owner", label: "Owner" },
  { key: "last_use", label: "Last imported use" }, { key: "opens", label: "Last AnalytIQ open" }, { key: "created", label: "Created" },
  { key: "id", label: "ID" },
];
const OPTIONAL = [{ key: "creator", label: "Creator" }, { key: "created", label: "Created" }, { key: "model", label: "Model" }] as const;
type OptionalKey = (typeof OPTIONAL)[number]["key"];
const COLS_KEY = "analytiq.portfolio.columns";

const month = (m: string | null) => m ? new Date(m.slice(0, 7) + "-01T00:00:00Z").toLocaleDateString("en-GB", { month: "short", year: "numeric", timeZone: "UTC" }) : "Unknown";
const when = (iso: string | null) => iso ? new Date(iso).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" }) : "Never";
const day = (v: string | null, precision: string | null) => !v ? "Unknown"
  : precision === "day" ? new Date(v.slice(0, 10) + "T00:00:00Z").toLocaleDateString("en-GB", { dateStyle: "medium", timeZone: "UTC" }) : when(v);
const ownerState = { active: "Active", inactive: "Owner inactive", absent: "Unassigned" } as const;

function go(url: string, replace = false) {
  if (url === location.pathname + location.search) return;
  history[replace ? "replaceState" : "pushState"](null, "", url);
  window.dispatchEvent(new PopStateEvent("popstate"));
}
function link(event: MouseEvent<HTMLAnchorElement>) {
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return;
  event.preventDefault();
  const to = new URL(event.currentTarget.href);
  go(to.pathname + to.search);
  window.scrollTo(0, 0);
}

function readCols(): OptionalKey[] {
  try { const v = JSON.parse(localStorage.getItem(COLS_KEY) || "[]"); return Array.isArray(v) ? v : []; } catch { return []; }
}

function useLoad<T>(load: (signal: AbortSignal) => Promise<T>, deps: unknown[]) {
  const [state, setState] = useState<{ data: T | null; error: string; loading: boolean }>({ data: null, error: "", loading: true });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const ctl = new AbortController();
    setState((s) => ({ ...s, error: "", loading: true }));
    load(ctl.signal).then((data) => setState({ data, error: "", loading: false }))
      .catch((e: Error) => { if (!ctl.signal.aborted) setState((s) => ({ ...s, error: e.message, loading: false })); });
    return () => ctl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, attempt]);
  return { ...state, retry: () => setAttempt((n) => n + 1), set: (data: T) => setState({ data, error: "", loading: false }) };
}

/* ---------------------------------------------------------------- identity */

function IdentityPicker() {
  const actor = useActor();
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [note, setNote] = useState("");
  useEffect(() => { bi.personas().then((p) => { setPersonas(p.personas); setNote(p.note); }).catch(() => setNote("Demo identities could not be loaded.")); }, []);
  const id = useId();
  return <div className="bp-identity">
    <label htmlFor={id}>Acting as</label>
    <select id={id} value={actor} onChange={(e) => setActor(e.target.value)} aria-describedby={`${id}-note`}>
      <option value="">Viewer (read only)</option>
      {personas.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
    </select>
    <p id={`${id}-note`} className="muted small">{note || "Demo identities, checked on the server. Not a sign-in."}</p>
  </div>;
}
const roleOf = (personas: Persona[], actor: string) => personas.find((p) => p.id === actor)?.role;
function usePersonas() {
  const [personas, setPersonas] = useState<Persona[]>([]);
  useEffect(() => { bi.personas().then((p) => setPersonas(p.personas)).catch(() => undefined); }, []);
  return personas;
}

/* ---------------------------------------------------------------- shared bits */

function IssueTags({ issues, labels }: { issues: IssueCode[]; labels: Record<string, string> }) {
  if (!issues.length) return <span className="muted small">None found</span>;
  return <ul className="bp-tags" aria-label="Issues">{ISSUE_ORDER.filter((i) => issues.includes(i)).map((i) =>
    <li key={i} className={`bp-tag bp-tag-${i}`}>{labels[i] ?? i}</li>)}</ul>;
}
function OwnerCell({ owner, state }: { owner: Row["owner"]; state: Row["owner_state"] }) {
  if (!owner) return <span className="text-warn">Unassigned</span>;
  return <span>{owner.name} <span className="muted mono small">{owner.id}</span>
    {state !== "active" && <span className="text-bad small"> · {ownerState[state]}</span>}
    {owner.via === "assignment" && <span className="muted small"> · assigned</span>}</span>;
}
function Notice({ kind, children }: { kind: "error" | "info" | "ok"; children: ReactNode }) {
  return <div className={`bp-notice bp-notice-${kind}`} role={kind === "error" ? "alert" : "status"}>{children}</div>;
}
const KpiList = ({ items, empty }: { items: Kpi[]; empty: string }) => items.length
  ? <ul className="bp-kpis">{items.map((k) => <li key={k.id}><span className="mono">{k.id}</span> {k.name ?? "Unknown KPI"}
    {k.approved_canonical && <span className="bp-pill ok">Canonical, approved</span>}
    {k.definition_status === "definition_conflict" && <span className="bp-pill bad">Definition conflict</span>}
    {k.binding && <span className="muted small"> · {k.binding}</span>}</li>)}</ul>
  : <p className="muted small">{empty}</p>;

/* ---------------------------------------------------------------- list */

function PortfolioList({ params }: { params: URLSearchParams }) {
  const [cols, setCols] = useState<OptionalKey[]>(readCols);
  useEffect(() => { try { localStorage.setItem(COLS_KEY, JSON.stringify(cols)); } catch { /* this visit only */ } }, [cols]);
  const query = params.toString();
  const { data, error, loading, retry } = useLoad<EstatePage>((s) => bi.list(new URLSearchParams(query), s), [query]);
  const [q, setQ] = useState(params.get("q") ?? "");
  useEffect(() => setQ(params.get("q") ?? ""), [params]);

  const update = (changes: Record<string, string | null>, replace = false) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(changes)) { if (v) next.set(k, v); else next.delete(k); }
    if (!("page" in changes)) next.delete("page");
    const s = next.toString();
    go("/bi-estate" + (s ? "?" + s : ""), replace);
  };
  const submit = (e: FormEvent) => { e.preventDefault(); update({ q: q.trim() || null }); };
  const sort = params.get("sort") ?? "issues";
  const direction = params.get("direction") ?? "desc";
  const active = FILTERS.some((f) => params.get(f));
  const issue = params.get("issue") as IssueCode | null;

  return <>
    {data && <section className="bp-counts" aria-label="Findings across the whole portfolio">
      {ISSUE_ORDER.map((code) => {
        const c = data.counts[code];
        const on = issue === code;
        return <button key={code} type="button" className={`bp-count bp-count-${code}`} aria-pressed={on}
          onClick={() => update({ issue: on ? null : code })}>
          <strong>{code === "consolidation" ? c.pairs : c.assets}</strong>
          <span>{data.issue_labels[code]}{code === "consolidation" ? ` pairs (${c.assets} reports)` : ""}</span>
        </button>;
      })}
    </section>}

    <form className="bp-filters" role="search" onSubmit={submit}>
      <label className="bp-search"><span className="sr-only">Search reports</span>
        <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search by title, ID, owner, KPI, product or market" /></label>
      <button className="btn-outline" type="submit">Search</button>
      {data && <>
        <Select label="Source" value={params.get("origin")} onChange={(v) => update({ origin: v })}
          options={Object.entries(data.origin_labels).map(([v, l]) => [v, l])} />
        <Select label="Platform" value={params.get("platform")} onChange={(v) => update({ platform: v })} options={data.facets.platform.map((v) => [v, v])} />
        <Select label="Issue" value={issue} onChange={(v) => update({ issue: v })} options={ISSUE_ORDER.map((v) => [v, data.issue_labels[v]])} />
        <Select label="Owner" value={params.get("owner_state")} onChange={(v) => update({ owner_state: v })}
          options={[["active", "Active owner"], ["inactive", "Owner inactive"], ["absent", "Unassigned"]]} />
        <Select label="Lifecycle" value={params.get("lifecycle")} onChange={(v) => update({ lifecycle: v })} options={data.facets.lifecycle.map((v) => [v, v])} />
        <Select label="Product" value={params.get("product")} onChange={(v) => update({ product: v })} options={data.facets.product.map((v) => [v, v])} />
        <Select label="Market" value={params.get("market")} onChange={(v) => update({ market: v })} options={data.facets.market.map((v) => [v, v])} />
      </>}
      {active && <button type="button" className="bp-linkbtn" onClick={() => go("/bi-estate")}>Clear filters</button>}
    </form>

    <div className="bp-tablebar">
      <p role="status" aria-live="polite">{data ? <><strong>{data.matching}</strong> of {data.total} reporting assets
        {data.pairs_in_view > 0 && <> · {data.pairs_in_view} consolidation {data.pairs_in_view === 1 ? "pair" : "pairs"} in view</>}</> : loading ? "Loading the portfolio…" : ""}</p>
      <div className="bp-tablecontrols">
        <label>Sort by <select value={sort} onChange={(e) => update({ sort: e.target.value })}>
          {SORTS.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}</select></label>
        <button type="button" className="btn-outline bp-small" onClick={() => update({ direction: direction === "desc" ? "asc" : "desc" })}
          aria-label={`Sort direction: ${direction === "desc" ? "descending" : "ascending"}. Switch`}>{direction === "desc" ? "↓ Desc" : "↑ Asc"}</button>
        <details className="bp-columns"><summary>Columns</summary>
          <fieldset><legend>Optional columns</legend>{OPTIONAL.map((c) => <label key={c.key}>
            <input type="checkbox" checked={cols.includes(c.key)} onChange={(e) => setCols((v) => e.target.checked ? [...v, c.key] : v.filter((x) => x !== c.key))} /> {c.label}</label>)}
          </fieldset></details>
      </div>
    </div>

    {error && <Notice kind="error">Could not load the portfolio: {error} <button type="button" className="bp-linkbtn" onClick={retry}>Try again</button></Notice>}
    {data && data.rows.length === 0 && <Notice kind="info">No reporting asset matches these filters. <button type="button" className="bp-linkbtn" onClick={() => go("/bi-estate")}>Clear filters</button></Notice>}
    {data && data.rows.length > 0 && <div className="bp-tablewrap" aria-busy={loading}>
      <table className="bp-table">
        <caption className="sr-only">Reporting assets, sorted by {SORTS.find((s) => s.key === sort)?.label}, {direction === "desc" ? "descending" : "ascending"}</caption>
        <thead><tr>
          <th scope="col">Report</th><th scope="col">Scope</th><th scope="col">Accountable owner</th>
          {cols.includes("creator") && <th scope="col">Creator</th>}
          {cols.includes("created") && <th scope="col">Created</th>}
          {cols.includes("model") && <th scope="col">Model</th>}
          <th scope="col">Use</th><th scope="col">Findings</th>
        </tr></thead>
        <tbody>{data.rows.map((r) => <tr key={r.id}>
          <td data-label="Report"><a href={`/bi-estate/${encodeURIComponent(r.id)}?${query}`} onClick={link} className="bp-title">{r.title}</a>
            <div className="muted small"><span className="mono">{r.id}</span> · {r.type} · {r.platform}{r.lifecycle !== "active" && <> · {r.lifecycle}</>}</div>
            {r.alias && <div className="muted small">Imported title: {r.original_title}</div>}</td>
          <td data-label="Scope">{r.product ?? "Unknown"}<div className="muted small">{r.market_name ?? r.market ?? "Unknown market"}</div></td>
          <td data-label="Owner"><OwnerCell owner={r.owner} state={r.owner_state} /></td>
          {cols.includes("creator") && <td data-label="Creator">{r.creator.name ?? <span className="muted small">{r.creator.source}</span>}</td>}
          {cols.includes("created") && <td data-label="Created">{day(r.created.value, r.created.precision)}</td>}
          {cols.includes("model") && <td data-label="Model" className="mono small">{r.model_id ?? "None"}</td>}
          <td data-label="Use"><div>{r.last_view_month ? <>Imported: last viewed {month(r.last_view_month)}</> : <span className="muted">No imported views</span>}</div>
            <div className="muted small">AnalytIQ opens: {r.app_opens.count}{r.app_opens.last_at && <>, last {when(r.app_opens.last_at)}</>}</div></td>
          <td data-label="Findings"><IssueTags issues={r.issues} labels={data.issue_labels} /><p className="bp-finding small">{r.finding}</p></td>
        </tr>)}</tbody>
      </table>
    </div>}

    {data && data.pages > 1 && <nav className="bp-pages" aria-label="Pages">
      <button type="button" className="btn-outline bp-small" disabled={data.page <= 1} onClick={() => update({ page: String(data.page - 1) })}>Previous</button>
      <span>Page {data.page} of {data.pages}</span>
      <button type="button" className="btn-outline bp-small" disabled={data.page >= data.pages} onClick={() => update({ page: String(data.page + 1) })}>Next</button>
    </nav>}

    {data && <footer className="bp-sources small muted">
      <p>{data.sources.note}</p>
      <p>Sources: {data.sources.origins.workbook} workbook assets ({data.sources.workbook.file}, SHA-256 <span className="mono">{data.sources.workbook.sha256.slice(0, 12)}…</span>,
        usage {month(data.sources.workbook.observation_window[0] ?? null)} to {month(data.sources.workbook.observation_window[1] ?? null)}),
        {" "}{data.sources.origins.app_report} app employee reports, {data.sources.origins.generated} employee-built dashboards. Store: {data.sources.store}. As of {when(data.sources.as_of)}.</p>
    </footer>}
  </>;
}

function Select({ label, value, onChange, options }: { label: string; value: string | null; onChange: (v: string | null) => void; options: string[][] }) {
  return <label className="bp-select"><span>{label}</span>
    <select value={value ?? ""} onChange={(e) => onChange(e.target.value || null)}>
      <option value="">All</option>{options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>;
}

/* ---------------------------------------------------------------- detail */

function AssetDetail({ id, back }: { id: string; back: string }) {
  const { data, error, loading, retry, set } = useLoad<Detail>((s) => bi.detail(id, s), [id]);
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { if (data) { heading.current?.focus(); document.title = `${data.title} · BI Portfolio · AnalytIQ intelligence`; } }, [data?.id]);
  if (!data) return <section className="bp-detail" aria-busy={loading}>
    <a href={back} onClick={link}>← Back to the portfolio</a>
    {error ? <Notice kind="error">{error} <button type="button" className="bp-linkbtn" onClick={retry}>Try again</button></Notice> : <p role="status">Loading the asset…</p>}</section>;
  const d = data;
  return <section className="bp-detail" aria-labelledby="bp-detail-title">
    <a href={back} onClick={link}>← Back to the portfolio</a>
    <header><p className="bp-kicker">{d.type} · {d.platform} · <span className="mono">{d.id}</span></p>
      <h2 id="bp-detail-title" tabIndex={-1} ref={heading}>{d.title}</h2>
      {d.alias && <p className="muted small">Imported title: {d.original_title}</p>}
      <p>{d.finding}</p>
      <div className="bp-links">
        {d.links.dashboard && <a href={d.links.dashboard}>Open the dashboard</a>}
        {d.links.register && <a href={d.links.register}>Open in the report register</a>}
        {d.links.explorer && <a href={d.links.explorer}>Open the Estate Explorer</a>}
      </div></header>

    <div className="bp-grid">
      <Card title="Ownership">
        <dl className="bp-dl">
          <dt>Accountable owner</dt><dd><OwnerCell owner={d.owner} state={d.owner_state} />{d.owner?.evidence && <div className="muted small">{d.owner.evidence}</div>}</dd>
          {d.imported_owner && d.owner?.via === "assignment" && <><dt>Imported owner</dt><dd>{d.imported_owner.name} <span className="mono small">{d.imported_owner.id}</span></dd></>}
          <dt>Creator</dt><dd>{d.creator.name ?? "Unrecorded"}<div className="muted small">{d.creator.source}</div></dd>
          <dt>Created</dt><dd>{day(d.created.value, d.created.precision)}<div className="muted small">{d.created.source}</div></dd>
          <dt>Last modified</dt><dd>{day(d.modified.value, d.modified.precision)}<div className="muted small">{d.modified.source}</div></dd>
          {d.teams.length > 0 && <><dt>Teams using it</dt><dd>{d.teams.join(", ")}</dd></>}
        </dl>
        <AssignOwner detail={d} onSaved={set} />
        {d.owner_history.length > 0 && <details><summary>Ownership changes ({d.owner_history.length})</summary><ol className="bp-history">
          {d.owner_history.map((h) => <li key={h.seq}>{when(h.at)}: {h.actor_name} assigned {h.owner_name} <span className="mono small">{h.owner_id}</span>. {h.reason}</li>)}</ol></details>}
      </Card>

      <Card title="Scope and model">
        <dl className="bp-dl">
          <dt>Declared scope</dt><dd>{d.product ?? "Unknown"} · {d.market_name ?? d.market ?? "Unknown"}</dd>
          <dt>Model</dt><dd>{d.model ? <>{d.model.name} <span className="mono small">{d.model.id}</span><div className="muted small">{d.model.product} · {d.model.region} · Semantic_Models row {d.model.row}</div></> : "No semantic model"}</dd>
          {d.scope && <><dt>Scope check</dt><dd className={d.scope.mismatch ? "text-bad" : ""}>Product {d.scope.product.replaceAll("_", " ")}, geography {d.scope.geography.replaceAll("_", " ")}
            <div className="muted small">{d.scope.rule.id} v{d.scope.rule.version}: {d.scope.rule.text}</div></dd></>}
          <dt>Refresh</dt><dd>{d.refresh.status.replaceAll("_", " ")}{d.refresh.cadence && <> · {d.refresh.cadence}</>}<div className="muted small">Last success: {d.refresh.last_success ?? "Unknown"}. {d.refresh.note}</div></dd>
          {d.data_through && <><dt>Data through</dt><dd>{month(d.data_through)}</dd></>}
        </dl>
      </Card>

      <Card title="Use">
        <p><strong>Imported usage</strong> ({d.usage.source}): {d.usage.views == null ? "none recorded" : <>{d.usage.views.toLocaleString()} views over {d.usage.months} months, last viewed {month(d.usage.last_view_month)}</>}</p>
        {d.usage_series.length > 0 && <details><summary>Monthly usage ({d.usage_series.length} rows)</summary>
          <table className="bp-mini"><thead><tr><th scope="col">Month</th><th scope="col">Views</th><th scope="col">Users</th><th scope="col">Row</th></tr></thead>
            <tbody>{d.usage_series.map((u) => <tr key={u.month}><td>{month(u.month)}</td><td>{u.views}</td><td>{u.unique_users}</td><td className="mono">{u.row}</td></tr>)}</tbody></table></details>}
        <p><strong>AnalytIQ opens</strong>: {d.app_opens.count}{d.app_opens.last_at && <>, last {when(d.app_opens.last_at)}</>}
          <span className="muted small"> · counted once per rendered, visible view. Kept apart from imported usage.</span></p>
      </Card>

      <Card title={`KPIs (${d.kpis.length})`}>
        <KpiList items={d.kpis} empty="No KPI is bound to this asset." />
        {d.variant_kpi_ids.length > 0 && <p className="text-bad small">Definition conflict: {d.variant_kpi_ids.join(", ")}</p>}
        {d.nonstandard_kpi_ids.length > 0 && <p className="muted small">Other non-standard definitions (weaker context): {d.nonstandard_kpi_ids.join(", ")}</p>}
      </Card>

      <Card title="Dependencies">
        <p className="muted small">{d.downstream_coverage}</p>
        <EdgeList title="Upstream" items={d.upstream} />
        <EdgeList title="Downstream" items={d.downstream} />
        {d.siblings_on_model && d.siblings_on_model.count > 0 && <p className="small">{d.siblings_on_model.count} other assets read the same model ({d.siblings_on_model.class}).</p>}
      </Card>

      {(d.signals.length > 0 || d.quality.length > 0) && <Card title="Governance signals and data quality">
        <ul className="bp-plain">{d.signals.map((s) => <li key={s.id}><span className="mono">{s.code}</span> · {s.severity} · {s.status} <span className="muted small">{s.evidence}</span></li>)}
          {d.quality.map((q) => <li key={q.id}>{q.field} on <span className="mono">{q.record}</span> · {q.severity}: {q.impact} <span className="muted small">{q.evidence}</span></li>)}</ul>
      </Card>}
    </div>

    {d.pairs.length > 0 && <Card title="Consolidation candidates">
      <ul className="bp-plain">{d.pairs.map((p) => {
        const other = p.a.id === d.id ? p.b : p.a;
        return <li key={p.id}><a href={`/bi-estate/compare/${p.a.id}/${p.b.id}`} onClick={link}>Compare with {other.title}</a> <span className="mono small">{other.id}</span>
          <span className="muted small"> · {p.shared_approved_ids.length} shared approved KPIs</span></li>;
      })}</ul></Card>}
    {d.cases.length > 0 && <Card title="Owner reviews">
      <ul className="bp-plain">{d.cases.map((c) => <li key={c.id}><a href={`/bi-estate/compare/${c.assets[0]}/${c.assets[1]}`} onClick={link}>{c.id}</a> · {c.status_label}</li>)}</ul></Card>}
    <p className="muted small">Sources: {d.sources.filter(Boolean).join(" · ")}</p>
  </section>;
}

function Card({ title, children }: { title: string; children: ReactNode }) {
  const id = useId();
  return <section className="bp-card" aria-labelledby={id}><h3 id={id}>{title}</h3>{children}</section>;
}
function EdgeList({ title, items }: { title: string; items: Detail["upstream"] }) {
  if (!items.length) return null;
  return <><h4>{title}</h4><ul className="bp-plain">{items.map((e, i) => <li key={e.id + i}>{e.title ?? e.id} <span className="mono small">{e.id}</span>
    <span className="muted small"> · {e.relationship} · {e.evidence}</span></li>)}</ul></>;
}

function AssignOwner({ detail, onSaved }: { detail: Detail; onSaved: (d: Detail) => void }) {
  const actor = useActor();
  const personas = usePersonas();
  const [open, setOpen] = useState(false);
  const [owner, setOwner] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  if (roleOf(personas, actor) !== "bi_steward") return null;
  const owners = personas.filter((p) => p.role === "owner");
  const save = async (e: FormEvent) => {
    e.preventDefault(); setBusy(true); setError("");
    try {
      onSaved(await bi.assignOwner(detail.id, { owner_id: owner, reason, expected_seq: detail.owner_history.at(-1)?.seq ?? 0 }));
      setOpen(false); setReason("");
    } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };
  if (!open) return <button type="button" className="btn-outline bp-small" onClick={() => setOpen(true)}>{detail.owner ? "Change accountable owner" : "Assign an owner"}</button>;
  return <form className="bp-form" onSubmit={save}>
    <label>New accountable owner<select required value={owner} onChange={(e) => setOwner(e.target.value)}>
      <option value="">Choose an active owner</option>{owners.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}</select></label>
    <label>Reason<textarea required minLength={3} value={reason} onChange={(e) => setReason(e.target.value)} rows={2} /></label>
    <p className="muted small">Recorded as an assignment on top of the imported owner. The workbook stays as it is.</p>
    {error && <Notice kind="error">{error}</Notice>}
    <div className="bp-actions"><button className="btn" disabled={busy}>Save owner</button><button type="button" className="btn-outline" onClick={() => setOpen(false)}>Cancel</button></div>
  </form>;
}

/* ---------------------------------------------------------------- compare and review */

function Compare({ a, b, back }: { a: string; b: string; back: string }) {
  const { data, error, loading, retry, set } = useLoad<Pair>((s) => bi.pair(a, b, s), [a, b]);
  const actor = useActor();
  const personas = usePersonas();
  useEffect(() => { document.title = `Compare ${a} and ${b} · BI Portfolio · AnalytIQ intelligence`; }, [a, b]);
  if (!data) return <section className="bp-detail" aria-busy={loading}><a href={back} onClick={link}>← Back to the portfolio</a>
    {error ? <Notice kind="error">{error} <button type="button" className="bp-linkbtn" onClick={retry}>Try again</button></Notice> : <p role="status">Loading the comparison…</p>}</section>;
  const p = data;
  const cases = p.cases ?? [];
  const open = cases.find((c) => c.status !== "closed");
  const replaceCase = (c: Case) => set({ ...p, cases: [...cases.filter((x) => x.id !== c.id), c].sort((x, y) => x.generation - y.generation) });
  return <section className="bp-detail" aria-labelledby="bp-compare-title">
    <a href={back} onClick={link}>← Back to the portfolio</a>
    <header><p className="bp-kicker">Compare · {p.qualifies ? `${p.rule.id} consolidation candidate` : "Not a rule-based candidate"}</p>
      <h2 id="bp-compare-title">{p.a.title} and {p.b.title}</h2>
      <p>{p.question}</p><p className="muted small">{p.note} Rule {p.rule.id} v{p.rule.version}: {p.rule.text}</p></header>

    <div className="bp-compare">
      <SideCard side={p.a} only={p.only_a} />
      <SideCard side={p.b} only={p.only_b} />
    </div>
    <Card title={`Shared KPIs (${p.shared.length}, ${p.shared_approved_ids.length} canonical and approved)`}><KpiList items={p.shared} empty="These reports share no KPI." /></Card>
    <dl className="bp-facts"><div><dt>Same scope</dt><dd>{p.same_scope ? "Yes" : "No"}</dd></div><div><dt>Same model</dt><dd>{p.same_model ? "Yes" : "No"}</dd></div>
      <div><dt>Same owner</dt><dd>{p.same_owner ? "Yes, one person answers for both" : "No"}</dd></div></dl>
    {p.blockers.length > 0 && <Notice kind="info"><strong>Before a decision:</strong><ul>{p.blockers.map((x) => <li key={x}>{x}</li>)}</ul></Notice>}

    {open ? <CasePanel c={open} pair={p} onChange={replaceCase} />
      : roleOf(personas, actor) === "bi_steward" ? <StartReview pair={p} onStarted={replaceCase} />
      : <Notice kind="info">{p.qualifies ? "No owner review is open. The BI steward can start one." : "This pair does not meet the consolidation rule, so no review is suggested."}</Notice>}
    {cases.filter((c) => c.status === "closed").reverse().map((c) => <CasePanel key={c.id} c={c} pair={p} onChange={replaceCase} />)}
  </section>;
}

function SideCard({ side, only }: { side: Side; only: Kpi[] }) {
  return <section className="bp-card" aria-label={side.title}>
    <h3><a href={`/bi-estate/${side.id}`} onClick={link}>{side.title}</a></h3>
    <p className="muted small"><span className="mono">{side.id}</span> · {side.type} · {side.platform} · {side.lifecycle}</p>
    <dl className="bp-dl">
      <dt>Owner</dt><dd><OwnerCell owner={side.owner} state={side.owner_state} /></dd>
      <dt>Scope</dt><dd>{side.product ?? "Unknown"} · {side.market_name ?? side.market ?? "Unknown"}</dd>
      <dt>Model</dt><dd>{side.model ? <>{side.model.name} <span className="mono small">{side.model.id}</span></> : "None"}{side.scope?.mismatch && <div className="text-bad small">Scope differs from the model</div>}</dd>
      <dt>Imported use</dt><dd>{side.usage.views == null ? "None recorded" : `${side.usage.views.toLocaleString()} views, last ${month(side.usage.last_view_month)}`}</dd>
      <dt>AnalytIQ opens</dt><dd>{side.app_opens.count}</dd>
      <dt>Downstream</dt><dd>{side.downstream.length ? side.downstream.map((e) => e.title ?? e.id).join(", ") : "None recorded"}</dd>
    </dl>
    <h4>Only in this report</h4><KpiList items={only} empty="Nothing beyond the shared KPIs." />
  </section>;
}

function StartReview({ pair, onStarted }: { pair: Pair; onStarted: (c: Case) => void }) {
  const [question, setQuestion] = useState(pair.question);
  const [note, setNote] = useState("");
  const [due, setDue] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setBusy(true); setError("");
    try { onStarted(await bi.startReview({ asset_a: pair.a.id, asset_b: pair.b.id, question, note, due: due || null })); }
    catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };
  return <form className="bp-card bp-form" onSubmit={submit} aria-labelledby="bp-start">
    <h3 id="bp-start">Start owner review</h3>
    <p className="muted small">Asks both accountable owners the question below. One review per pair: starting it again opens the same review.</p>
    <label>Question for the owners<textarea required minLength={10} rows={3} value={question} onChange={(e) => setQuestion(e.target.value)} /></label>
    <label>Note (optional)<textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} /></label>
    <label>Respond by (optional)<input type="date" value={due} onChange={(e) => setDue(e.target.value)} /></label>
    {error && <Notice kind="error">{error}</Notice>}
    <div className="bp-actions"><button className="btn" disabled={busy}>Start owner review</button></div>
  </form>;
}

function CasePanel({ c, pair, onChange }: { c: Case; pair: Pair; onChange: (c: Case) => void }) {
  const actor = useActor();
  const personas = usePersonas();
  const role = roleOf(personas, actor);
  const [copied, setCopied] = useState<"" | "done" | "manual">("");
  const mine = c.owners.filter((o) => o.owner?.id === actor && o.owner_state === "active").map((o) => o.asset_id);
  const unanswered = mine.filter((aid) => !c.responses[aid]);
  const title = (aid: string) => aid === pair.a.id ? pair.a.title : pair.b.title;
  const copy = async () => { try { await navigator.clipboard.writeText(c.brief); setCopied("done"); } catch { setCopied("manual"); } };
  const closed = c.status === "closed";
  return <section className={`bp-card bp-case${closed ? " closed" : ""}`} aria-labelledby={`case-${c.id}`}>
    <div className="bp-casehead"><h3 id={`case-${c.id}`}>Owner review <span className="mono">{c.id}</span></h3>
      <span className={`bp-status bp-status-${c.status}`}>{c.status_label}</span></div>
    <p>{c.question}</p>
    <p className="muted small">Coordinator {c.coordinator} · started {when(c.created_at)}{c.due && <> · respond by {day(c.due, "day")}</>}
      {c.reopened_from && <> · reopens {c.reopened_from} (changed since: {(c.changed_since_previous ?? []).join(", ")})</>}</p>
    {c.note && <p className="small">{c.note}</p>}
    {c.needs_reassessment && !closed && <Notice kind="info">An owner, scope or KPI binding changed since this review started. Reassess before deciding.</Notice>}

    <h4>Owner responses</h4>
    <ul className="bp-responses">{c.owners.map((o) => {
      const r = c.responses[o.asset_id];
      return <li key={o.asset_id}><strong>{title(o.asset_id)}</strong> <span className="mono small">{o.asset_id}</span>
        <div className="small">Owner: {o.owner ? o.owner.name : "Unassigned"}{o.owner_state !== "active" && <span className="text-bad"> · {ownerState[o.owner_state as Row["owner_state"]]}</span>}</div>
        {r ? <div className="bp-response"><p><strong>{({ consolidate: "Consolidate", more_evidence: "Request more evidence", keep_both: "Keep both" } as Record<string, string>)[r.proposal]}</strong> · {r.actor_name}, {when(r.at)}</p>
          <p>{r.purpose}</p>{r.consumers && <p className="small">Who relies on it: {r.consumers}</p>}
          {r.essential_kpis.length > 0 && <p className="small">Essential KPIs: {r.essential_kpis.join(", ")}</p>}
          {r.blockers && <p className="small">Blockers: {r.blockers}</p>}</div>
          : <p className="muted small">{closed ? "No response." : "Waiting for a response."}</p>}
      </li>;
    })}</ul>
    {c.same_owner && <p className="muted small">The same person owns both reports, so one response covers both.</p>}

    {!closed && role === "owner" && unanswered.length > 0 && <RespondForm c={c} assetId={unanswered[0]} kpis={pair.shared} onDone={onChange} />}
    {!closed && role === "owner" && mine.length === 0 && <p className="muted small">You do not own either report, so you cannot respond here.</p>}
    {!closed && role === "bi_steward" && <DecideForm c={c} pair={pair} onDone={onChange} />}

    {c.decision && <div className="bp-decision"><h4>Decision: {c.decision.outcome_label}</h4>
      <p>{c.decision.reason}</p>
      <p className="muted small">{c.decision.actor_name}, {when(c.decision.at)}{c.decision.owner_disagreement && " · The owners proposed different outcomes."}</p>
      {c.decision.plan && <p className="small">Plan: keep <span className="mono">{c.decision.plan.survivor}</span>, accountable {c.decision.plan.accountable_owner.name},
        checkpoint {day(c.decision.plan.checkpoint, "day")}.{c.decision.plan.affected && ` Affected: ${c.decision.plan.affected}.`}{c.decision.plan.validation && ` Validation: ${c.decision.plan.validation}.`}</p>}
      <p className="small text-warn">{c.decision.execution}</p></div>}

    <div className="bp-actions">
      <button type="button" className="btn-outline bp-small" onClick={() => void copy()}>{copied === "done" ? "Brief copied" : "Copy discussion brief"}</button>
    </div>
    {copied === "manual" && <label className="bp-form">Discussion brief<textarea readOnly rows={8} value={c.brief} onFocus={(e) => e.currentTarget.select()} /></label>}
    <details><summary>History ({c.events.length})</summary><ol className="bp-history">{c.events.map((e) =>
      <li key={e.seq}>{when(e.at)}: {e.actor_name} {e.kind === "opened" ? "started the review" : e.kind === "response" ? "responded" : "recorded the decision"}</li>)}</ol></details>
  </section>;
}

function RespondForm({ c, assetId, kpis, onDone }: { c: Case; assetId: string; kpis: Kpi[]; onDone: (c: Case) => void }) {
  const [proposal, setProposal] = useState("");
  const [purpose, setPurpose] = useState("");
  const [consumers, setConsumers] = useState("");
  const [essential, setEssential] = useState<string[]>([]);
  const [blockers, setBlockers] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setBusy(true); setError("");
    try { onDone(await bi.caseEvent(c.id, { kind: "response", expected_seq: c.seq, asset_id: assetId, proposal, purpose, consumers, essential_kpis: essential, blockers })); }
    catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };
  return <form className="bp-form" onSubmit={submit}>
    <h4>Your response for <span className="mono">{assetId}</span>{c.same_owner && " (covers both reports)"}</h4>
    <fieldset><legend>Your proposal</legend>{[["consolidate", "Consolidate"], ["more_evidence", "Request more evidence"], ["keep_both", "Keep both"]].map(([v, l]) =>
      <label key={v} className="bp-radio"><input type="radio" name={`proposal-${c.id}`} value={v} required checked={proposal === v} onChange={() => setProposal(v)} /> {l}</label>)}</fieldset>
    <label>What is the report for?<textarea required rows={2} value={purpose} onChange={(e) => setPurpose(e.target.value)} /></label>
    <label>Who relies on it? (optional)<input value={consumers} onChange={(e) => setConsumers(e.target.value)} /></label>
    {kpis.length > 0 && <fieldset><legend>Essential KPIs (optional)</legend>{kpis.map((k) => <label key={k.id} className="bp-radio">
      <input type="checkbox" checked={essential.includes(k.id)} onChange={(e) => setEssential((v) => e.target.checked ? [...v, k.id] : v.filter((x) => x !== k.id))} /> {k.name} <span className="mono small">{k.id}</span></label>)}</fieldset>}
    <label>Blockers (optional)<textarea rows={2} value={blockers} onChange={(e) => setBlockers(e.target.value)} /></label>
    {error && <Notice kind="error">{error}</Notice>}
    <div className="bp-actions"><button className="btn" disabled={busy}>Send response</button></div>
  </form>;
}

function DecideForm({ c, pair, onDone }: { c: Case; pair: Pair; onDone: (c: Case) => void }) {
  const personas = usePersonas();
  const [outcome, setOutcome] = useState("");
  const [reason, setReason] = useState("");
  const [survivor, setSurvivor] = useState("");
  const [owner, setOwner] = useState("");
  const [checkpoint, setCheckpoint] = useState("");
  const [affected, setAffected] = useState("");
  const [validation, setValidation] = useState("");
  const [ack, setAck] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const ready = c.status === "ready_for_decision";
  const options: [string, string][] = [["keep_both", "Keep both"], ["remediate", "Remediate definitions or scope"], ["consolidation_plan", "Prepare consolidation plan"], ["dismiss", "Dismiss candidate"]];
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setBusy(true); setError("");
    const body: Record<string, unknown> = { kind: "decision", expected_seq: c.seq, outcome, reason, acknowledge_changes: ack };
    if (outcome === "consolidation_plan") Object.assign(body, { survivor, accountable_owner_id: owner, checkpoint, affected, validation });
    try { onDone(await bi.caseEvent(c.id, body)); } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };
  return <form className="bp-form" onSubmit={submit}>
    <h4>Record the decision</h4>
    {!ready && <p className="muted small">Both owners respond first. Until then only Dismiss candidate is possible.</p>}
    <fieldset><legend>Outcome</legend>{options.map(([v, l]) => <label key={v} className="bp-radio">
      <input type="radio" name={`outcome-${c.id}`} value={v} required disabled={!ready && v !== "dismiss"} checked={outcome === v} onChange={() => setOutcome(v)} /> {l}</label>)}</fieldset>
    {outcome === "consolidation_plan" && <>
      <label>Report that stays<select required value={survivor} onChange={(e) => setSurvivor(e.target.value)}><option value="">Choose</option>
        {[pair.a, pair.b].map((s) => <option key={s.id} value={s.id}>{s.title} ({s.id})</option>)}</select></label>
      <label>Accountable owner for the plan<select required value={owner} onChange={(e) => setOwner(e.target.value)}><option value="">Choose an active owner</option>
        {personas.filter((p) => p.role === "owner").map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}</select></label>
      <label>Checkpoint date<input type="date" required value={checkpoint} onChange={(e) => setCheckpoint(e.target.value)} /></label>
      <label>Affected users or reports (optional)<input value={affected} onChange={(e) => setAffected(e.target.value)} /></label>
      <label>How the result is validated (optional)<input value={validation} onChange={(e) => setValidation(e.target.value)} /></label>
    </>}
    <label>Reason<textarea required minLength={5} rows={2} value={reason} onChange={(e) => setReason(e.target.value)} /></label>
    {c.needs_reassessment && <label className="bp-radio"><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} /> I reassessed the changed evidence</label>}
    <p className="muted small">The decision is recorded only. Nothing is retired or changed in Power BI or Tableau.</p>
    {error && <Notice kind="error">{error}</Notice>}
    <div className="bp-actions"><button className="btn" disabled={busy}>Record decision</button></div>
  </form>;
}

/* ---------------------------------------------------------------- page */

export function BIPortfolioPage({ ids }: { ids: string[] }) {
  const [search, setSearch] = useState(() => location.search);
  useEffect(() => {
    const on = () => setSearch(location.search);
    window.addEventListener("popstate", on);
    return () => window.removeEventListener("popstate", on);
  }, []);
  const params = new URLSearchParams(search);
  const listParams = new URLSearchParams([...params].filter(([k]) => (FILTERS as readonly string[]).includes(k) || ["sort", "direction", "page"].includes(k)));
  const back = "/bi-estate" + (listParams.toString() ? "?" + listParams : "");
  const view = ids[0] === "compare" ? "compare" : ids[0] ? "detail" : "list";
  useEffect(() => { if (view === "list") document.title = "BI Portfolio · AnalytIQ intelligence"; }, [view]);
  return <main className="page bp-page">
    <header className="bp-head">
      <div><h1>BI Portfolio</h1>
        <p className="muted">Every reporting asset AnalytIQ can see, who answers for it, how it is used, and what needs a decision. Sample data.</p></div>
      <IdentityPicker />
    </header>
    {view === "list" && <PortfolioList params={listParams} />}
    {view === "detail" && <AssetDetail key={ids[0]} id={ids[0]} back={back} />}
    {view === "compare" && ids.length === 3 && <Compare key={ids.slice(1).join("~")} a={ids[1]} b={ids[2]} back={back} />}
  </main>;
}
