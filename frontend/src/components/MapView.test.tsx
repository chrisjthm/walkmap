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
    globalThis.fetch = fetchMock as typeof fetch;

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
    let resolveRefresh: ((value: Response) => void) | undefined;
    const refreshPromise = new Promise<Response>((resolve) => {
      resolveRefresh = resolve;
    });

    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => initial,
      })
      .mockReturnValueOnce(refreshPromise as Promise<Response>);

    globalThis.fetch = fetchMock as typeof fetch;

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
    } as Response);

    await waitFor(() => {
      expect(button.hasAttribute("disabled")).toBe(false);
    });
    expect(button.textContent?.toLowerCase()).toContain("refresh gradient");
  });
});

describe("MapView score breakdown", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.stubEnv("VITE_E2E_MOCK_MAP", "true");
    vi.stubEnv("VITE_E2E", "true");
  });

  afterEach(() => {
    cleanup();
  });

  it("shows AI factors and rating blend copy for zero ratings", async () => {
    const segments = buildFeatureCollection([88]);
    const detail = {
      segment_id: "seg-0",
      composite_score: 88,
      verified: true,
      rating_count: 0,
      vibe_tag_counts: {},
      factors: {
        waterfront: 25,
        park_adjacency: 0,
        walkmap_sidewalk_penalty: -15,
      },
    };

    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => segments,
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => detail,
      });
    globalThis.fetch = fetchMock as typeof fetch;

    const { default: MapView } = await import("./MapView");
    render(<MapView />);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled();
    });

    const map = (window as { __walkmap__?: { map?: { __triggerClick?: (point: { x: number; y: number }) => void } } })
      .__walkmap__?.map;
    map?.__triggerClick?.({ x: 0, y: 0 });

    await screen.findByText("Segment Detail");
    const breakdownButton = screen.getByRole("button", { name: /score breakdown/i });
    fireEvent.click(breakdownButton);

    expect(await screen.findByText("AI factors")).toBeTruthy();
    expect(screen.getByText("Waterfront proximity")).toBeTruthy();
    expect(screen.getByText("+25")).toBeTruthy();
    expect(screen.getByText("Residential street without sidewalks")).toBeTruthy();
    expect(screen.getByText("-15")).toBeTruthy();
    expect(screen.queryByText("Park adjacency")).toBeNull();
    expect(
      screen.getByText("Score is AI-estimated - no user ratings yet"),
    ).toBeTruthy();
  });

  it("describes blend state for 1-4 ratings", async () => {
    const segments = buildFeatureCollection([62]);
    const detail = {
      segment_id: "seg-0",
      composite_score: 62,
      verified: false,
      rating_count: 3,
      vibe_tag_counts: {},
      factors: {
        residential_landuse: 6,
      },
    };

    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => segments,
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => detail,
      });
    globalThis.fetch = fetchMock as typeof fetch;

    const { default: MapView } = await import("./MapView");
    render(<MapView />);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled();
    });

    const map = (window as { __walkmap__?: { map?: { __triggerClick?: (point: { x: number; y: number }) => void } } })
      .__walkmap__?.map;
    map?.__triggerClick?.({ x: 0, y: 0 });

    await screen.findByText("Segment Detail");
    fireEvent.click(screen.getByRole("button", { name: /score breakdown/i }));

    expect(
      screen.getByText("Score is a blend of AI estimate and 3 user rating(s)"),
    ).toBeTruthy();
  });

  it("describes blend state for 5+ ratings", async () => {
    const segments = buildFeatureCollection([90]);
    const detail = {
      segment_id: "seg-0",
      composite_score: 90,
      verified: true,
      rating_count: 6,
      vibe_tag_counts: {},
      factors: {
        tree_cover: 6,
      },
    };

    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => segments,
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => detail,
      });
    globalThis.fetch = fetchMock as typeof fetch;

    const { default: MapView } = await import("./MapView");
    render(<MapView />);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled();
    });

    const map = (window as { __walkmap__?: { map?: { __triggerClick?: (point: { x: number; y: number }) => void } } })
      .__walkmap__?.map;
    map?.__triggerClick?.({ x: 0, y: 0 });

    await screen.findByText("Segment Detail");
    fireEvent.click(screen.getByRole("button", { name: /score breakdown/i }));

    expect(
      screen.getByText("Score is based entirely on user ratings"),
    ).toBeTruthy();
  });
});
