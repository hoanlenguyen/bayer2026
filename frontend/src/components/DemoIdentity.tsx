import { useEffect, useState } from "react";
import { ensureSession, getJSON, selectActor, type DemoActor } from "../api/client";

export function DemoIdentity() {
  const [actors, setActors] = useState<DemoActor[]>([]);
  const [id, setId] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    getJSON<{ actors: DemoActor[] }>("/api/session").then(r => setActors(r.actors)).catch(e => setError(e.message));
    ensureSession().then(r => setId(r.actor.id)).catch(e => setError(e.message));
  }, []);
  return <label className="demo-identity" title="Explicit synthetic demo roles. This is not Bayer sign-in.">
    <span>DEMO ROLE</span>
    <select aria-label="Demo actor" value={id} onChange={async e => {
      try { const r = await selectActor(e.target.value); setId(r.actor.id); setError(""); }
      catch (e) { setError(String(e)); }
    }}>{actors.map(a => <option key={a.id} value={a.id}>{a.name} · {a.role} ({a.id})</option>)}</select>
    {error && <small role="alert">{error}</small>}
  </label>;
}
