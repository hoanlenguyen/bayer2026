import type { ReportView } from "../api/briefings";

export function month(value: string, abbreviated = false) {
  const [year, number] = value.split("-").map(Number);
  return new Intl.DateTimeFormat("en-GB", abbreviated ? { month: "short", timeZone: "UTC" } : {
    month: "long", year: "numeric", timeZone: "UTC",
  }).format(new Date(Date.UTC(year, number - 1, 1)));
}

export function amount(value: number, unit: ReportView["unit"]) {
  if (unit === "€m") return `€${value.toFixed(2)}m`;
  if (unit === "%") return `${value.toFixed(1)}%`;
  return value.toLocaleString("en-GB");
}

function movement(delta: number, unit: string, reference: string) {
  if (delta === 0) return `Unchanged from ${reference}`;
  return `${Math.abs(delta).toFixed(1)}${unit} ${delta > 0 ? "above" : "below"} ${reference}`;
}

export function comparison(view: ReportView, previous: string) {
  if (view.forecast_variance_pct != null && view.forecast != null) {
    return movement(view.forecast_variance_pct, "%", "forecast");
  }
  if (view.change_pp != null) return movement(view.change_pp, " percentage points", month(previous).split(" ")[0]);
  if (view.change_pct != null) return movement(view.change_pct, "%", month(previous).split(" ")[0]);
  return `Compared with ${month(previous)}`;
}
