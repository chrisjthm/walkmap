export type ScoreLegend = {
  min: number;
  max: number;
  mode: "relative" | "global";
};

type ScoreFeature = {
  properties: {
    composite_score?: number;
    score?: number;
  };
};

const SCORE_STOPS = [
  { value: 0, color: "#d64545" },
  { value: 20, color: "#e78b3c" },
  { value: 40, color: "#f2d15c" },
  { value: 60, color: "#8ccf7a" },
  { value: 80, color: "#2f7f4f" },
  { value: 100, color: "#1f6a3f" },
];

export const buildScoreExpression = (minScore: number, maxScore: number) => {
  const span = Math.max(1, maxScore - minScore);
  const stops = SCORE_STOPS.flatMap((stop) => [
    minScore + (stop.value / 100) * span,
    stop.color,
  ]);

  return [
    "interpolate",
    ["linear"],
    ["coalesce", ["get", "composite_score"], ["get", "score"], 0],
    ...stops,
  ];
};

const getScoreValue = (feature: ScoreFeature) => {
  const raw = feature.properties.composite_score ?? feature.properties.score ?? 0;
  const value = Number(raw);
  return Number.isFinite(value) ? value : null;
};

const percentile = (sorted: number[], p: number) => {
  if (!sorted.length) {
    return 0;
  }
  const index = (sorted.length - 1) * p;
  const lower = Math.floor(index);
  const upper = Math.ceil(index);
  if (lower === upper) {
    return sorted[lower];
  }
  const weight = index - lower;
  return sorted[lower] + (sorted[upper] - sorted[lower]) * weight;
};

export const computeScoreAnchors = (features: ScoreFeature[]) => {
  const scores = features
    .map(getScoreValue)
    .filter((value): value is number => value !== null);

  if (!scores.length) {
    return {
      anchorLow: 0,
      anchorHigh: 100,
      legend: { min: 0, max: 100, mode: "global" as const },
    };
  }

  const sorted = [...scores].sort((a, b) => a - b);
  const minScore = sorted[0];
  const maxScore = sorted[sorted.length - 1];
  const low = percentile(sorted, 0.1);
  const high = percentile(sorted, 0.9);
  const range = high - low;

  if (scores.length < 10 || range < 10) {
    return {
      anchorLow: 0,
      anchorHigh: 100,
      legend: {
        min: Math.round(minScore),
        max: Math.round(maxScore),
        mode: "global" as const,
      },
    };
  }

  return {
    anchorLow: low,
    anchorHigh: high,
    legend: {
      min: Math.round(low),
      max: Math.round(high),
      mode: "relative" as const,
    },
  };
};
