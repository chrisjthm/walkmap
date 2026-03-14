import { describe, expect, it } from "vitest";
import { buildScoreExpression, computeScoreAnchors } from "./mapScoreUtils";

const makeFeatures = (scores: number[]) =>
  scores.map((score) => ({
    properties: { composite_score: score },
  }));

describe("computeScoreAnchors", () => {
  it("uses percentile anchors when enough variation exists", () => {
    const scores = Array.from({ length: 10 }, (_, i) => i * 10);
    const result = computeScoreAnchors(makeFeatures(scores));

    expect(result.legend.mode).toBe("relative");
    expect(result.anchorLow).toBeCloseTo(9, 1);
    expect(result.anchorHigh).toBeCloseTo(81, 1);
    expect(result.legend.min).toBe(9);
    expect(result.legend.max).toBe(81);
  });

  it("falls back to global scale for small samples", () => {
    const result = computeScoreAnchors(makeFeatures([12, 40, 55, 60, 82]));

    expect(result.legend.mode).toBe("global");
    expect(result.anchorLow).toBe(0);
    expect(result.anchorHigh).toBe(100);
    expect(result.legend.min).toBe(12);
    expect(result.legend.max).toBe(82);
  });

  it("falls back to global scale when range is too narrow", () => {
    const scores = Array.from({ length: 12 }, (_, i) => 50 + (i % 7));
    const result = computeScoreAnchors(makeFeatures(scores));

    expect(result.legend.mode).toBe("global");
    expect(result.anchorLow).toBe(0);
    expect(result.anchorHigh).toBe(100);
    expect(result.legend.min).toBe(50);
    expect(result.legend.max).toBe(56);
  });

  it("defaults to global scale when no scores are present", () => {
    const result = computeScoreAnchors([]);

    expect(result.legend.mode).toBe("global");
    expect(result.anchorLow).toBe(0);
    expect(result.anchorHigh).toBe(100);
    expect(result.legend.min).toBe(0);
    expect(result.legend.max).toBe(100);
  });
});

describe("buildScoreExpression", () => {
  it("scales stops to the provided score range", () => {
    const expression = buildScoreExpression(20, 80);
    const firstStop = expression[3] as number;
    const lastStop = expression[expression.length - 2] as number;

    expect(firstStop).toBe(20);
    expect(lastStop).toBe(80);
  });
});
