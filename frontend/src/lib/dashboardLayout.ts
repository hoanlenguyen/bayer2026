import type { SavedDashboard } from "../api/dashboardBuilder";

/* The one layout rule for saved analytics, mirrored from choose_layout in backend/app/dashboard_builder.py so the
   build receipt, the hand-off and the saved page always describe the same screen. It reads the data's shape only,
   so dashboards saved before this rule (no presentation flag, no layout field) get the same layout as new ones. */

export type DashboardLayout = "table" | "empty" | "pulse" | "summary" | "compare" | "overview";

type Shape = Pick<SavedDashboard, "columns" | "groups"> & { display_mode?: string };

/** The measures a chart draws: a sales forecast beside net sales is drawn as net sales' comparison line, not its own chart. */
export function chartedColumns<C extends { id: string }>(columns: C[]): C[] {
  return columns.filter((c) => c.id !== "sales_forecast" || !columns.some((x) => x.id === "net_sales"));
}

export function chooseLayout(record: Shape): DashboardLayout {
  if (record.display_mode === "table") return "table";
  const charted = chartedColumns(record.columns).map((c) => c.id);
  const months = record.groups
    .map((g) => new Set(g.points.filter((p) => charted.some((k) => Number.isFinite(p.values[k]))).map((p) => p.period)))
    .filter((m) => m.size > 0);
  if (!months.length) return "empty";
  if (months.length === 1) return months[0].size >= 2 ? "pulse" : "summary";
  if (months.length <= 3) return "compare";
  return "overview";
}

/** Months between two YYYY-MM periods (1 = adjacent). */
export function monthGap(a: string, b: string): number {
  const n = (p: string) => Number(p.slice(0, 4)) * 12 + Number(p.slice(5, 7));
  return n(b) - n(a);
}
