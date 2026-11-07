/** One colour and one name per recommendation, wherever it appears. Colours are the --rec-* tokens in styles.css. */
const LABELS = {
  reuse: "Reuse",
  repair: "Reuse after repair",
  consolidate: "Consolidation",
  migrate: "Migration",
  retire: "Retirement",
  new_build: "New build",
  review: "Human review",
  not_feasible: "Not feasible",
} as const;

export type Recommendation = keyof typeof LABELS;

export function RecommendationChip({ value, count }: { value: string; count?: number }) {
  const known = value in LABELS;
  return (
    <span className={`rec-chip${known ? ` rec-${value}` : ""}`}>
      {count !== undefined && `${count} `}{known ? LABELS[value as Recommendation] : value}
    </span>
  );
}
