import { useState, type ComponentProps } from "react";
import { PulseChart } from "./PulseChart";
import "./pulse-dashboard.css";

export interface PulseMetric {
  id: string;
  title: string;
  unit: string;
  points: ComponentProps<typeof PulseChart>["points"];
}

export function PulseDashboard({ metrics, scope, source, preferred, compact, choice: chosen, onChoose }: {
  metrics: PulseMetric[]; scope: string; source: string; preferred?: string; compact?: boolean;
  /** Controlled metric choice, so charts shown side by side switch together. */
  choice?: string; onChoose?: (id: string) => void;
}) {
  const [ownChoice, setOwnChoice] = useState<string>();
  const choice = chosen ?? ownChoice;
  const setChoice = onChoose ?? setOwnChoice;
  const available = metrics.filter(metric => metric.points.length > 1);
  const active = available.find(metric => metric.id === choice) ?? available.find(metric => metric.id === preferred) ?? available[0];
  if (!active) return null;
  const controls = available.length > 1 && <div className="pulse-picks" role="group" aria-label="Choose a metric">
    {available.map(metric => <button key={metric.id} type="button" aria-pressed={metric.id === active.id}
      onClick={() => setChoice(metric.id)}>{metric.title}</button>)}
  </div>;
  return <PulseChart title={active.title} unit={active.unit} points={active.points}
    scope={scope} source={source} controls={controls} compact={compact} />;
}
