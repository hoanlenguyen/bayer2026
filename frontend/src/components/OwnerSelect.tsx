import { useEffect, useState } from "react";
import { api } from "../api/client";

export function OwnerSelect({ id, value, onChange }: { id: string; value: string; onChange: (id: string) => void }) {
  const [owners, setOwners] = useState<[string, {owner_name: string; status: string}][]>([]);
  useEffect(() => { api.catalog().then(c => setOwners(Object.entries(c.owners ?? {}).filter(([, o]) => o.status === "active"))).catch(() => undefined); }, []);
  return <select id={id} value={value} onChange={e => onChange(e.target.value)}>
    <option value="">Select an active owner</option>
    {owners.map(([key, o]) => <option key={key} value={key}>{o.owner_name} · {key}</option>)}
  </select>;
}
