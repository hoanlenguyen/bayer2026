import { OwnerSelect } from "../components/OwnerSelect";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { Action, ActionKind, ActionStatus, ActionSummary } from "../api/types";

const LANES: { status: ActionStatus; title: string; hint: string }[] = [
  { status: "open", title: "Open", hint: "Assigned, not started" },
  { status: "in_progress", title: "In progress", hint: "Being worked on" },
  { status: "blocked", title: "Blocked", hint: "Needs help to continue" },
  { status: "done", title: "Done, not verified", hint: "Work finished; outcome still to check" },
  { status: "verified", title: "Verified", hint: "Outcome checked" },
];

const STATUS_LABEL: Record<ActionStatus, string> = {
  open: "Open", in_progress: "In progress", blocked: "Blocked", done: "Done", verified: "Verified", dismissed: "Dismissed",
};
const MOVE_LABEL: Record<ActionStatus, string> = {
  open: "Reopen", in_progress: "Start", blocked: "Mark blocked", done: "Mark done", verified: "Verify outcome", dismissed: "Dismiss",
};

function fmtDate(iso: string | null) {
  if (!iso) return "No due date";
  return new Date(iso + "T00:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

function KindChip({ kind }: { kind: ActionKind }) {
  return <span className={`kind ${kind === "business" ? "kind-biz" : "kind-maint"}`}>{kind === "business" ? "Business" : "Maintenance"}</span>;
}

function openEntity(id: string) {
  window.dispatchEvent(new CustomEvent("open-entity", { detail: id }));
}

/** Edit panel for one action: owner, due date, status moves with required notes, verification, history. */
function ActionDetail({ action, onSaved, onClose }: { action: Action; onSaved: (a: Action) => void; onClose: () => void }) {
  const [owner, setOwner] = useState(action.owner_id ?? "");
  const [due, setDue] = useState(action.due_date ?? "");
  const [blocker, setBlocker] = useState(action.blocker);
  const [outcome, setOutcome] = useState(action.outcome);
  const [result, setResult] = useState<"improved" | "not_improved" | "confirmed">(action.verify?.metric_id ? "improved" : "confirmed");
  const [note, setNote] = useState("");
  const [pending, setPending] = useState<ActionStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setOwner(action.owner_id ?? ""); setDue(action.due_date ?? ""); setBlocker(action.blocker); setOutcome(action.outcome);
    setPending(null); setError(null); setNote("");
  }, [action]);

  const save = async (body: Record<string, unknown>) => {
    setBusy(true); setError(null);
    try {
      onSaved(await api.updateAction(action._id, { ...body, version: action.version ?? 1 }));
      setPending(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const move = (to: ActionStatus) => {
    if (to === "blocked" || to === "done" || to === "verified") setPending(to);
    else void save({ status: to });
  };

  const fieldsChanged = owner !== (action.owner_id ?? "") || due !== (action.due_date ?? "");
  const metric = action.verify?.metric_name;
  const better = action.verify?.direction === "decrease" ? "go down" : "go up";
  const went = action.verify?.direction === "decrease" ? "went down" : "went up";

  return (
    <aside className="action-detail" aria-label="Action details">
      <div className="ad-head">
        <div className="ad-tags"><KindChip kind={action.kind} /><span className={`pill st-pill-${action.status}`}>{STATUS_LABEL[action.status]}</span>
          {action.overdue && <span className="pill tone-bad">Overdue</span>}{action.sample && <span className="pill tone-neutral">Sample</span>}</div>
        <button type="button" className="btn-ghost" onClick={onClose} aria-label="Close details">Close</button>
      </div>
      <h2>{action.title}</h2>
      {action.reason && <p className="muted">{action.reason}</p>}
      {action.asset_id && (
        <button type="button" className="btn-ghost small" onClick={() => openEntity(action.asset_id!)}>
          Linked report: {action.asset_name ?? action.asset_id}
        </button>
      )}

      <div className="ad-fields">
        <label htmlFor="ad-owner">Owner<OwnerSelect id="ad-owner" value={owner} onChange={setOwner} /></label>
        <label htmlFor="ad-due">Due date<input id="ad-due" type="date" value={due} onChange={(e) => setDue(e.target.value)} /></label>
        {fieldsChanged && (
          <button type="button" className="btn" disabled={busy} onClick={() => save({ owner_id: owner || undefined, due_date: due || undefined })}>Save changes</button>
        )}
      </div>

      {action.status === "blocked" && action.blocker && <p className="ad-note"><strong>Blocked:</strong> {action.blocker}</p>}
      {action.outcome && <p className="ad-note"><strong>What was done:</strong> {action.outcome}</p>}

      {action.verify && (
        <div className="ad-verify">
          <strong>Verification</strong>
          {action.verify.result ? (
            <p>
              {action.verify.result === "improved" ? "✓ Improved" : action.verify.result === "not_improved" ? "✕ Did not improve" : "✓ Confirmed"}
              {action.verify.note && `: ${action.verify.note}`}
              <span className="muted"> · {action.verify.checked_by}</span>
            </p>
          ) : (
            <p className="muted">
              {metric ? `After the work is done, check that ${metric} ${went}.` : "After the work is done, confirm the fix worked."}
              {" "}Finishing the work does not count as verification.
            </p>
          )}
        </div>
      )}

      {action.allowed.length > 0 && !pending && (
        <div className="ad-moves">
          {action.allowed.filter((s) => s !== "dismissed").map((s) => (
            <button key={s} type="button" className={s === "verified" || s === "done" ? "btn" : "btn-ghost"} disabled={busy} onClick={() => move(s)}>
              {MOVE_LABEL[s]}
            </button>
          ))}
          {action.allowed.includes("dismissed") && (
            <button type="button" className="btn-ghost danger" disabled={busy} onClick={() => move("dismissed")}>Dismiss</button>
          )}
        </div>
      )}

      {pending === "blocked" && (
        <form className="ad-form" onSubmit={(e) => { e.preventDefault(); void save({ blocker, status: "blocked" }); }}>
          <label htmlFor="ad-blocker">What is blocking this?</label>
          <textarea id="ad-blocker" value={blocker} onChange={(e) => setBlocker(e.target.value)} rows={2} required />
          <div className="ad-moves"><button className="btn" disabled={busy || !blocker.trim()}>Mark blocked</button>
            <button type="button" className="btn-ghost" onClick={() => setPending(null)}>Cancel</button></div>
        </form>
      )}
      {pending === "done" && (
        <form className="ad-form" onSubmit={(e) => { e.preventDefault(); void save({ outcome, status: "done" }); }}>
          <label htmlFor="ad-outcome">What was done?</label>
          <textarea id="ad-outcome" value={outcome} onChange={(e) => setOutcome(e.target.value)} rows={2} required />
          <div className="ad-moves"><button className="btn" disabled={busy || !outcome.trim()}>Mark done</button>
            <button type="button" className="btn-ghost" onClick={() => setPending(null)}>Cancel</button></div>
        </form>
      )}
      {pending === "verified" && (
        <form className="ad-form" onSubmit={(e) => { e.preventDefault(); void save({ status: "verified", verification: { result, note } }); }}>
          <fieldset>
            <legend>{metric ? `Did ${metric} ${better}?` : "Did the fix work?"}</legend>
            {(metric ? (["improved", "not_improved"] as const) : (["confirmed", "not_improved"] as const)).map((r) => (
              <label key={r} className="radio" htmlFor={`ad-r-${r}`}>
                <input id={`ad-r-${r}`} type="radio" name="result" checked={result === r} onChange={() => setResult(r)} />
                {r === "improved" ? "Yes, it improved" : r === "confirmed" ? "Yes, confirmed" : "No"}
              </label>
            ))}
          </fieldset>
          <label htmlFor="ad-vnote">Evidence (for example the number before and after)</label>
          <textarea id="ad-vnote" value={note} onChange={(e) => setNote(e.target.value)} rows={2} />
          <div className="ad-moves"><button className="btn" disabled={busy}>Record verification</button>
            <button type="button" className="btn-ghost" onClick={() => setPending(null)}>Cancel</button></div>
        </form>
      )}
      {error && <p className="bad-text small" role="alert">{error}</p>}

      <div className="ad-history">
        <strong className="small">History</strong>
        <ol>
          {[...action.history].reverse().map((h, i) => (
            <li key={i}>
              <span className="muted mono small">{new Date(h.at).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</span>
              <span>
                {h.change === "status" ? <>{h.by}: {STATUS_LABEL[h.from as ActionStatus]} → <strong>{STATUS_LABEL[h.to as ActionStatus]}</strong></>
                  : h.change === "created" ? <>{h.by} created it</>
                  : <>{h.by} changed {h.change.replace("_", " ")} to <strong>{h.to}</strong></>}
                {h.note && <span className="muted">. {h.note}</span>}
              </span>
            </li>
          ))}
        </ol>
      </div>
    </aside>
  );
}

export function ActionsPage({ onChanged }: { onChanged: () => void }) {
  const [items, setItems] = useState<Action[] | null>(null);
  const [summary, setSummary] = useState<ActionSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [kind, setKind] = useState<"all" | ActionKind>("all");
  const [owner, setOwner] = useState("all");
  const [selected, setSelected] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await api.actions();
      setItems(data.items);
      setSummary(data.summary);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const owners = useMemo(() => [...new Set((items ?? []).map((a) => a.owner))].sort(), [items]);
  const shown = (items ?? []).filter((a) => (kind === "all" || a.kind === kind) && (owner === "all" || a.owner === owner));
  const current = items?.find((a) => a._id === selected) ?? null;

  const onSaved = (a: Action) => {
    setItems((prev) => prev?.map((x) => (x._id === a._id ? a : x)) ?? prev);
    void load();
    onChanged();
  };

  if (error) {
    return <main className="page"><div className="banner" role="status">Actions could not be loaded ({error}). Is the backend running on port 8000?</div></main>;
  }
  if (!items || !summary) return <main className="page"><p className="muted">Loading actions…</p></main>;

  return (
    <main className={`page actions-page${current ? " with-detail" : ""}`}>
      <div className="actions-head">
        <div>
          <h1>Actions</h1>
          <p className="muted">Follow-up work from analytics findings. Business actions act on the numbers; maintenance actions fix the analytics.</p>
        </div>
        <div className="head-stats" aria-label="Summary">
          <div className="head-stat"><span className="k">Active</span><span className="v">{summary.active}</span></div>
          <div className="head-stat"><span className="k">Overdue</span><span className="v" style={{ color: summary.overdue ? "var(--bad)" : undefined }}>{summary.overdue}</span></div>
          <div className="head-stat"><span className="k">Blocked</span><span className="v" style={{ color: summary.blocked ? "var(--warn)" : undefined }}>{summary.blocked}</span></div>
          <div className="head-stat"><span className="k">To verify</span><span className="v">{summary.awaiting_verification}</span></div>
        </div>
      </div>

      <div className="actions-filters">
        <div className="seg" role="group" aria-label="Kind">
          {(["all", "business", "maintenance"] as const).map((k) => (
            <button key={k} type="button" aria-pressed={kind === k} onClick={() => setKind(k)}>
              {k === "all" ? "All" : k === "business" ? "Business" : "Maintenance"}
            </button>
          ))}
        </div>
        <label htmlFor="owner-filter" className="owner-filter">Owner
          <select id="owner-filter" value={owner} onChange={(e) => setOwner(e.target.value)}>
            <option value="all">Everyone</option>
            {owners.map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
        </label>
        <span className="muted small">{shown.length} of {items.length} actions{items.some((a) => a.sample) ? " · includes sample data" : ""}</span>
      </div>

      <div className="actions-body">
        <div className="board" role="list">
          {LANES.map((lane) => {
            const cards = shown.filter((a) => a.status === lane.status);
            return (
              <section key={lane.status} className={`lane-col lane-${lane.status}`} aria-label={lane.title}>
                <header><h2>{lane.title}</h2><span className="count">{cards.length}</span></header>
                <p className="lane-hint">{lane.hint}</p>
                {cards.length === 0 && <p className="lane-empty">Nothing here</p>}
                {cards.map((a) => (
                  <button key={a._id} type="button" role="listitem" className={`action-card${selected === a._id ? " is-selected" : ""}`}
                    onClick={() => setSelected(a._id)}>
                    <span className="ac-top"><KindChip kind={a.kind} />{a.overdue && <span className="pill sm tone-bad">Overdue</span>}</span>
                    <span className="ac-title">{a.title}</span>
                    <span className="ac-meta">
                      <span>{a.owner}</span>
                      <span className={a.overdue ? "bad-text" : ""}>{fmtDate(a.due_date)}</span>
                    </span>
                    {a.status === "blocked" && a.blocker && <span className="ac-blocker">{a.blocker}</span>}
                    {a.status === "verified" && a.verify?.result && (
                      <span className={a.verify.result === "not_improved" ? "bad-text small" : "ok-text small"}>
                        {a.verify.result === "not_improved" ? "Did not improve" : a.verify.result === "improved" ? "Improved" : "Confirmed"}
                      </span>
                    )}
                  </button>
                ))}
              </section>
            );
          })}
        </div>
        {current && <ActionDetail action={current} onSaved={onSaved} onClose={() => setSelected(null)} />}
      </div>
    </main>
  );
}
