import { useState } from "react";
import { api } from "../../api/client";
import type { ActionProposal } from "../../api/types";

type RowState = { owner: string; due: string; status: "idle" | "saving" | "added" | "error"; message?: string };

/** Suggested follow-up actions. Nothing is tracked until a person accepts one and confirms the owner. */
export function ProposedActions({ proposals, conversationId, onAdded }: {
  proposals: ActionProposal[]; conversationId: string | null; onAdded: () => void;
}) {
  const [rows, setRows] = useState<Record<string, RowState>>(() =>
    Object.fromEntries(proposals.map((p) => [p.key, {
      owner: p.owner, due: p.due_date,
      status: p.existing_action_id ? "added" : "idle",
      message: p.existing_action_id ? "Already tracked" : undefined,
    }])));

  const update = (key: string, patch: Partial<RowState>) => setRows((r) => ({ ...r, [key]: { ...r[key], ...patch } }));

  const accept = async (p: ActionProposal) => {
    const row = rows[p.key];
    update(p.key, { status: "saving", message: undefined });
    try {
      await api.createAction({ ...p, owner: row.owner, due_date: row.due, conversation_id: conversationId, by: "You" });
      update(p.key, { status: "added", message: `Assigned to ${row.owner}` });
      onAdded();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      update(p.key, { status: msg.includes("already covers") ? "added" : "error", message: msg.includes("already covers") ? "Already tracked" : msg });
    }
  };

  if (!proposals.length) return null;
  return (
    <section className="proposals" aria-label="Suggested follow-up actions">
      <header>
        <strong>Suggested follow-up actions</strong>
        <span className="muted small">Accept the ones you want tracked. You can change the owner and due date first.</span>
      </header>
      <ul>
        {proposals.map((p) => {
          const row = rows[p.key];
          const done = row.status === "added";
          return (
            <li key={p.key} className={done ? "is-added" : ""}>
              <div className="pr-main">
                <span className={`kind ${p.kind === "business" ? "kind-biz" : "kind-maint"}`}>{p.kind === "business" ? "Business" : "Maintenance"}</span>
                <span className="pr-title">{p.title}</span>
                <span className="muted small">{p.reason}</span>
              </div>
              {done ? (
                <a className="pr-done" href="#actions">✓ {row.message} · View</a>
              ) : (
                <div className="pr-form">
                  <label htmlFor={`own-${p.key}`} className="sr-only">Owner</label>
                  <input id={`own-${p.key}`} value={row.owner} onChange={(e) => update(p.key, { owner: e.target.value })} />
                  <label htmlFor={`due-${p.key}`} className="sr-only">Due date</label>
                  <input id={`due-${p.key}`} type="date" value={row.due} onChange={(e) => update(p.key, { due: e.target.value })} />
                  <button type="button" className="btn" disabled={row.status === "saving" || !row.owner.trim()} onClick={() => accept(p)}>
                    {row.status === "saving" ? "Adding…" : "Accept"}
                  </button>
                </div>
              )}
              {row.status === "error" && <p className="bad-text small">{row.message}</p>}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
