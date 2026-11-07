import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { navigate } from "../../lib/navigation";

export function SavedDashboards() {
  const [items, setItems] = useState<Awaited<ReturnType<typeof api.dashboards>>["items"]>([]);
  useEffect(() => {
    let active = true;
    const load = () => { void api.dashboards().then(data => { if (active) setItems(data.items); }).catch(() => undefined); };
    load();
    window.addEventListener("dashboards-changed", load);
    return () => { active = false; window.removeEventListener("dashboards-changed", load); };
  }, []);
  if (!items.length) return null;
  return <details className="ask-saved"><summary>Saved dashboards ({items.length})</summary>
    <ul>{items.map(item => <li key={item.id}><a href={item.url} onClick={navigate}>{item.title}</a>
      <small>{item.period.start} – {item.period.end}</small></li>)}</ul>
  </details>;
}
