import { useEffect, useState } from "react";
import { getJSON as request } from "../api/client";
import type { SourceRef } from "../data/types";

export function SourceEvidence({ sources }: { sources: SourceRef[] }) {
  const [selected, setSelected] = useState<SourceRef | null>(null);
  const [value, setValue] = useState<any>(null);
  const [error, setError] = useState("");
  const sourceKey = sources.map(s => `${s.snapshot}:${s.sheet}:${s.row}`).join("|");
  useEffect(() => { setSelected(null); setValue(null); }, [sourceKey]);
  useEffect(() => {
    let alive = true; setValue(null); setError("");
    if (selected) request(`/api/source/${encodeURIComponent(selected.sheet)}?row=${selected.row}`)
      .then(v => { if (alive) setValue(v.rows[0]); }).catch(e => { if (alive) setError(e.message); });
    return () => { alive = false; };
  }, [selected]);
  if (!sources.length) return null;
  return <section className="source-evidence">
    <h3>Source evidence</h3>
    <div className="source-links">{sources.slice(0, 30).map((s, i) => <button type="button" key={`${s.sheet}:${s.row}:${i}`}
      aria-pressed={selected?.sheet === s.sheet && selected?.row === s.row} onClick={() => setSelected(s)}>{s.sheet} · row {s.row}</button>)}</div>
    {sources.length > 30 && <p>{sources.length} source rows. Open the workbook for the complete records.</p>}
    {error && <p role="alert">{error}</p>}
    {selected && !value && !error && <p>Loading original row…</p>}
    {value && <dl className="source-values">{Object.entries(value).filter(([k]) => k !== "_source").map(([k, v]) =>
      <div key={k}><dt>{k}</dt><dd>{v === null ? "Not supplied" : typeof v === "object" ? JSON.stringify(v) : String(v)}</dd></div>)}</dl>}
    {selected && <a href={`#source/${encodeURIComponent(selected.sheet)}`}>Open worksheet ↗</a>}
  </section>;
}
