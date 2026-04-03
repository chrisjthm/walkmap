import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { RouteSuggestion } from "./routePlanner";

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

const ROUTE_FIXTURES: RouteSuggestion[] = [
  {
    routeId: "route-1",
    segmentIds: ["seg-a", "seg-b"],
    geometry: {
      type: "LineString",
      coordinates: [
        [-74.0431, 40.7178],
        [-74.041, 40.719],
      ],
    },
    distanceM: 1600,
    durationS: 1200,
    avgScore: 92,
    verifiedCount: 3,
    unverifiedCount: 1,
  },
  {
    routeId: "route-2",
    segmentIds: ["seg-c", "seg-d"],
    geometry: {
      type: "LineString",
      coordinates: [
        [-74.047, 40.715],
        [-74.045, 40.718],
      ],
    },
    distanceM: 1750,
    durationS: 1260,
    avgScore: 88,
    verifiedCount: 2,
    unverifiedCount: 2,
  },
  {
    routeId: "route-3",
    segmentIds: ["seg-e", "seg-f"],
    geometry: {
      type: "LineString",
      coordinates: [
        [-74.05, 40.713],
        [-74.048, 40.716],
      ],
    },
    distanceM: 1900,
    durationS: 1320,
    avgScore: 84,
    verifiedCount: 1,
    unverifiedCount: 3,
  },
];

function SeedRoutes({
  routes = ROUTE_FIXTURES,
  useRoutePlanner,
}: {
  routes?: RouteSuggestion[];
  useRoutePlanner: typeof import("./routePlanner").useRoutePlanner;
}) {
  const { setRoutes } = useRoutePlanner();

  useEffect(() => {
    setRoutes(routes);
    // Seed once for the test; re-seeding on every provider rerender resets selection.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return null;
}

const renderMapViewWithRoutes = async (routes: RouteSuggestion[] = ROUTE_FIXTURES) => {
  const data = buildFeatureCollection([72, 80, 88, 94]);
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => data,
  });
  globalThis.fetch = fetchMock as typeof fetch;

  const { RoutePlannerProvider, useRoutePlanner } = await import("./routePlanner");
  const { default: MapView } = await import("./MapView");
  const view = render(
    <RoutePlannerProvider>
      <SeedRoutes routes={routes} useRoutePlanner={useRoutePlanner} />
      <MapView />
    </RoutePlannerProvider>,
  );

  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalled();
  });

  return view;
}

describe("MapView gradient refresh", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.stubEnv("VITE_E2E_MOCK_MAP", "true");
    vi.stubEnv("VITE_E2E", "true");
    Object.defineProperty(window, "scrollTo", {
      value: vi.fn() as unknown as typeof window.scrollTo,
      writable: true,
    });
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
    Object.defineProperty(window, "scrollTo", {
      value: vi.fn() as unknown as typeof window.scrollTo,
      writable: true,
    });
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

describe("MapView route suggestions", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.stubEnv("VITE_E2E_MOCK_MAP", "true");
    vi.stubEnv("VITE_E2E", "true");
    Object.defineProperty(window, "scrollTo", {
      value: vi.fn() as unknown as typeof window.scrollTo,
      writable: true,
    });
  });

  afterEach(() => {
    cleanup();
  });

  it("highlights the selected route card and de-emphasizes the others", async () => {
    const { container } = await renderMapViewWithRoutes();

    await screen.findByText(/suggested routes/i);

    const cards = container.querySelectorAll<HTMLButtonElement>(".route-results-card");
    expect(cards).toHaveLength(3);

    const [route1, route2, route3] = Array.from(cards);

    expect(route1.getAttribute("data-active")).toBe("true");
    expect(route2.getAttribute("data-active")).toBe("false");
    expect(route3.getAttribute("data-active")).toBe("false");

    fireEvent.click(route2);

    await waitFor(() => {
      const updatedCards = container.querySelectorAll<HTMLButtonElement>(".route-results-card");
      expect(updatedCards[0]?.getAttribute("data-active")).toBe("false");
      expect(updatedCards[1]?.getAttribute("data-active")).toBe("true");
      expect(updatedCards[2]?.getAttribute("data-active")).toBe("false");
    });
  });

  it("renders route cards with distinct route colors", async () => {
    const { container } = await renderMapViewWithRoutes();

    await screen.findByText(/suggested routes/i);

    const swatches = container.querySelectorAll<HTMLElement>(".planner-route-swatch");
    expect(swatches).toHaveLength(3);

    const colors = Array.from(swatches).map((swatch) => swatch.style.background);
    expect(new Set(colors).size).toBe(3);
    expect(colors).toEqual(["rgb(92, 166, 255)", "rgb(240, 138, 71)", "rgb(193, 123, 255)"]);
  });
});
