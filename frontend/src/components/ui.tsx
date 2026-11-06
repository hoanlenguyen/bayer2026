import { STATUS, TYPES } from "../data/estate";
import type { EntityType, Severity, Status } from "../data/types";
import { toneOf } from "../lib/estate";
import { SEV } from "../data/estate";

export function Pill({ status, sm }: { status: Status; sm?: boolean }) {
  const st = STATUS[status];
  return <span className={`pill tone-${st.tone}${sm ? " sm" : ""}`}>{st.label}</span>;
}

export function SeverityPill({ sev }: { sev: Severity }) {
  return <span className={`pill sm tone-${sev === "info" ? "neutral" : sev}`}>{SEV[sev]}</span>;
}

export function TypeChip({ type }: { type: EntityType }) {
  return (
    <span className={`type-chip t-${type}`}>
      <span className="tdot" />
      {TYPES[type].label}
    </span>
  );
}

export function Meter({ value }: { value: number | null }) {
  if (value === null) return <span className="muted">Not established</span>;
  return (
    <span className="meter">
      <span className="meter-track">
        <span style={{ width: `${Math.round(value * 100)}%`, background: `var(--${toneOf(value)})` }} />
      </span>
      {value.toFixed(2)}
    </span>
  );
}
