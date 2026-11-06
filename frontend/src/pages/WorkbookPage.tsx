import { useEffect, useState } from "react";
import { getJSON as request } from "../api/client";

export function WorkbookPage() {
  const [initial, setInitial] = useState(decodeURIComponent(window.location.hash.split("/").slice(1).join("/")));
  const [meta, setMeta] = useState<any>(null);
  useEffect(() => {
    request("/api/source").then(setMeta).catch(e => setError(e.message));
    const onHash = () => setInitial(decodeURIComponent(window.location.hash.split("/").slice(1).join("/")));
    window.addEventListener("hashchange", onHash);
    document.title = "Workbook · Analytics Manager";
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  const [sheet, setSheet] = useState(initial || "Analytics_Assets");
  const [offset, setOffset] = useState(0);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState("");
  useEffect(() => { setSheet(initial || "Analytics_Assets"); setOffset(0); }, [initial]);
  useEffect(() => {
    let alive = true; setResult(null); setError("");
    request(`/api/source/${encodeURIComponent(sheet)}?offset=${offset}&limit=50`)
      .then(v => { if (alive) setResult(v); }).catch(e => { if (alive) setError(e.message); });
    return () => { alive = false; };
  }, [sheet, offset]);
  return <main className="manager-page workbook-page">
    <span className="folio">SOURCE WORKBOOK / {meta?.sheet_count} SHEETS</span>
    <h1>The evidence, in full.</h1>
    <p>{meta?.filename} · v{meta?.version} · synthetic challenge data</p>
    <label>Worksheet <select value={sheet} onChange={e => { setSheet(e.target.value); setOffset(0); window.location.hash = "#source/" + encodeURIComponent(e.target.value); }}>
      {Object.keys(meta?.sheets ?? {}).map(s => <option key={s}>{s}</option>)}
    </select></label>
    {error && <p role="alert">{error}</p>}
    {!result && !error && <p>Loading source rows…</p>}
    {result && <><p>{result.total} records · rows retain their original Excel row numbers</p>
      <div className="workbook-table"><table><thead><tr><th>Excel row</th>{(result.columns.length ? result.columns : ["Values"]).map((c: string) => <th key={c}>{c}</th>)}</tr></thead>
        <tbody>{result.rows.map((r: any) => <tr key={r._source.row}><th>{r._source.row}</th>{(result.columns.length ? result.columns : ["values"]).map((c: string) => <td key={c}>{r[c] === null ? "—" : Array.isArray(r[c]) ? r[c].map((v: any) => v ?? "").join(" · ") : String(r[c] ?? "")}</td>)}</tr>)}</tbody></table></div>
      <div className="workbook-paging"><button disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 50))}>Previous</button><span>{offset + 1}–{Math.min(offset + 50, result.total)} of {result.total}</span><button disabled={offset + 50 >= result.total} onClick={() => setOffset(offset + 50)}>Next</button></div>
    </>}
  </main>;
}
