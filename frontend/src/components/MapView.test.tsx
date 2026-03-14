import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const buildFeatureCollection = (scores: number[]) => ({
  type: "FeatureCollection",
  features: scores.map((score, index) => ({
    type: "Feature",
    geometry: {
      type: "LineString",
      coordinates: [
        [-74.04 + index * 0.0001, 40.71],
        [-74.041 + index * 0.0001, 40.711],
      ],
    },
    properties: {
      segment_id: `seg-${index}`,
      composite_score: score,
      verified: true,
      rating_count: 0,
      vibe_tag_counts: {},
    },
  })),
});

describe("MapView gradient refresh", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.stubEnv("VITE_E2E_MOCK_MAP", "true");
    vi.stubEnv("VITE_E2E", "true");
  });

  afterEach(() => {
    cleanup();
  });

  it("refreshes gradient on initial load based on viewport data", async () => {
    const data = buildFeatureCollection([10, 20, 30, 40, 50, 60, 70, 80, 90, 100]);
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => data,
    });
    global.fetch = fetchMock as typeof fetch;

    const { default: MapView } = await import("./MapView");
    render(<MapView />);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled();
    });

    const legend = await screen.findByText(/Scores in view:/i);
    expect(legend.textContent).toContain("19-91");
  });

  it("shows a loading state while refreshing the gradient", async () => {
    const initial = buildFeatureCollection([12, 22, 32, 42, 52, 62, 72, 82, 92, 100]);
    let resolveRefresh: ((value: unknown) => void) | null = null;
    const refreshPromise = new Promise((resolve) => {
      resolveRefresh = resolve;
    });

    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => initial,
      })
      .mockReturnValueOnce(refreshPromise as Promise<Response>);

    global.fetch = fetchMock as typeof fetch;

    const { default: MapView } = await import("./MapView");
    render(<MapView />);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });

    const buttons = await screen.findAllByRole("button", { name: /refresh gradient/i });
    const button = buttons[0];
    fireEvent.click(button);

    expect(button.hasAttribute("disabled")).toBe(true);
    expect(button.textContent?.toLowerCase()).toContain("refreshing");

    resolveRefresh?.({
      ok: true,
      json: async () => initial,
    });

    await waitFor(() => {
      expect(button.hasAttribute("disabled")).toBe(false);
    });
    expect(button.textContent?.toLowerCase()).toContain("refresh gradient");
  });
});
