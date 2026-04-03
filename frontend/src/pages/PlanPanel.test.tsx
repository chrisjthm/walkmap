import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import PlanPanel from "./PlanPanel";
import { RoutePlannerProvider } from "../components/routePlanner";

const renderPanel = () =>
  render(
    <RoutePlannerProvider>
      <PlanPanel />
    </RoutePlannerProvider>,
  );

describe("PlanPanel", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    Object.defineProperty(window, "scrollTo", {
      value: vi.fn() as unknown as typeof window.scrollTo,
      writable: true,
    });
  });

  afterEach(() => {
    cleanup();
  });

  it("builds the route suggest request body from form inputs", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      void init;
      const url = String(input);
      if (url.includes("/routes/suggest")) {
        return {
          ok: true,
          json: async () => ({
            routes: [
              {
                segment_ids: ["a", "b"],
                geometry: {
                  type: "LineString",
                  coordinates: [
                    [-74.0431, 40.7178],
                    [-74.04, 40.72],
                  ],
                },
                distance_m: 4320,
                duration_s: 1800,
                avg_score: 88,
                verified_count: 3,
                unverified_count: 1,
              },
            ],
          }),
        } as Response;
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    globalThis.fetch = fetchMock as typeof fetch;

    renderPanel();

    fireEvent.click(screen.getByText("Destination").closest("button") as HTMLButtonElement);
    fireEvent.change(screen.getByLabelText(/start location/i), {
      target: { value: "40.71780, -74.04310" },
    });
    fireEvent.change(screen.getByLabelText(/end location/i), {
      target: { value: "40.72000, -74.04000" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^Duration$/ }));
    fireEvent.change(screen.getByRole("slider"), {
      target: { value: "90" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^Run$/ }));
    fireEvent.click(
      screen.getByText("Dining & Shopping").closest("button") as HTMLButtonElement,
    );
    fireEvent.click(screen.getByRole("button", { name: /find routes/i }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });

    const [, request] = fetchMock.mock.calls[0] as [RequestInfo | URL, RequestInit | undefined];
    expect(request).toMatchObject({
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
    });
    expect(JSON.parse(String(request?.body))).toEqual({
      start: { lat: 40.7178, lng: -74.0431 },
      end: { lat: 40.72, lng: -74.04 },
      mode: "point-to-destination",
      distance_m: 12960,
      activity: "run",
      priority: "dining",
    });
  });

  it("searches for a destination suggestion and uses its coordinates in the route request", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      void init;
      const url = String(input);
      if (url.includes("/locations/search")) {
        return {
          ok: true,
          json: async () => ({
            results: [
              {
                id: "nominatim:razza",
                label: "Razza",
                lat: 40.728,
                lng: -74.05,
                kind: "business",
                secondary_text: "Jersey City, New Jersey",
              },
            ],
          }),
        } as Response;
      }
      if (url.includes("/routes/suggest")) {
        return {
          ok: true,
          json: async () => ({
            routes: [
              {
                segment_ids: ["a", "b"],
                geometry: {
                  type: "LineString",
                  coordinates: [[-74.0431, 40.7178], [-74.05, 40.728]],
                },
                distance_m: 2400,
                duration_s: 1600,
                avg_score: 91,
                verified_count: 2,
                unverified_count: 1,
              },
            ],
          }),
        } as Response;
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    globalThis.fetch = fetchMock as typeof fetch;

    renderPanel();

    fireEvent.click(screen.getByText("Destination").closest("button") as HTMLButtonElement);
    const endInput = screen.getByLabelText(/end location/i);
    fireEvent.focus(endInput);
    fireEvent.change(endInput, {
      target: { value: "Razza" },
    });

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });

    const suggestion = await screen.findByRole("button", { name: /razza/i });
    fireEvent.mouseDown(suggestion);
    fireEvent.click(screen.getByRole("button", { name: /find routes/i }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(2);
    });

    const routeCall = fetchMock.mock.calls.find(([input]) => String(input).includes("/routes/suggest")) as
      | [RequestInfo | URL, RequestInit | undefined]
      | undefined;
    expect(routeCall).toBeTruthy();
    expect(JSON.parse(String(routeCall?.[1]?.body))).toMatchObject({
      start: { lat: 40.7178, lng: -74.0431 },
      end: { lat: 40.728, lng: -74.05 },
      mode: "point-to-destination",
    });
  });

  it("uses browser geolocation to populate the start field", async () => {
    const getCurrentPosition = vi.fn((success: PositionCallback) => {
      success({
        coords: {
          latitude: 40.71,
          longitude: -74.05,
        },
      } as GeolocationPosition);
    });

    Object.defineProperty(globalThis.navigator, "geolocation", {
      value: { getCurrentPosition },
      configurable: true,
    });

    renderPanel();

    fireEvent.click(screen.getByRole("button", { name: /use my location/i }));

    await waitFor(() => {
      expect(getCurrentPosition).toHaveBeenCalled();
    });
    expect(
      (screen.getByLabelText(/start location/i) as HTMLInputElement).value,
    ).toBe("Current location · 40.71000, -74.05000");
  });

  it("accepts pasted coordinates without hitting location search", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      void init;
      const url = String(input);
      if (url.includes("/routes/suggest")) {
        return {
          ok: true,
          json: async () => ({
            routes: [
              {
                segment_ids: ["a"],
                geometry: {
                  type: "LineString",
                  coordinates: [[-74.05, 40.71], [-74.04, 40.72]],
                },
                distance_m: 1000,
                duration_s: 700,
                avg_score: 80,
                verified_count: 1,
                unverified_count: 0,
              },
            ],
          }),
        } as Response;
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    globalThis.fetch = fetchMock as typeof fetch;

    renderPanel();

    fireEvent.change(screen.getByLabelText(/start location/i), {
      target: { value: "40.71000, -74.05000" },
    });
    fireEvent.click(screen.getByRole("button", { name: /find routes/i }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });
    expect(String(fetchMock.mock.calls[0][0])).toContain("/routes/suggest");
  });

  it("blocks route search when typed destination is not selected from suggestions", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      void init;
      const url = String(input);
      if (url.includes("/locations/search")) {
        return {
          ok: true,
          json: async () => ({
            results: [
              {
                id: "nominatim:grove",
                label: "Grove Street PATH",
                lat: 40.7196,
                lng: -74.0431,
                kind: "landmark",
                secondary_text: "Jersey City, New Jersey",
              },
            ],
          }),
        } as Response;
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    globalThis.fetch = fetchMock as typeof fetch;

    renderPanel();

    fireEvent.click(screen.getByText("Destination").closest("button") as HTMLButtonElement);
    const endInput = screen.getByLabelText(/end location/i);
    fireEvent.focus(endInput);
    fireEvent.change(endInput, {
      target: { value: "Grove Street" },
    });
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });

    fireEvent.change(endInput, {
      target: { value: "Grove Street maybe" },
    });
    fireEvent.click(screen.getByRole("button", { name: /find routes/i }));

    expect((await screen.findByRole("alert")).textContent).toContain(
      "Choose an end point from the suggestions or paste coordinates before searching.",
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("shows a friendly error when location search fails", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      void init;
      const url = String(input);
      if (url.includes("/locations/search")) {
        return {
          ok: false,
          json: async () => ({
            detail: "Location search is temporarily unavailable.",
          }),
        } as Response;
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    globalThis.fetch = fetchMock as typeof fetch;

    renderPanel();
    const startInput = screen.getByLabelText(/start location/i);
    fireEvent.focus(startInput);
    fireEvent.change(startInput, {
      target: { value: "Razza Pizza" },
    });

    expect((await screen.findByRole("alert")).textContent).toContain(
      "Location search is temporarily unavailable.",
    );
  });
});
