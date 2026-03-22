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
  });

  afterEach(() => {
    cleanup();
  });

  it("builds the route suggest request body from form inputs", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
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

    const [, request] = fetchMock.mock.calls[0];
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

  it("shows a friendly error when the API fails", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      json: async () => ({
        detail: "No routes available for that request.",
      }),
    });
    globalThis.fetch = fetchMock as typeof fetch;

    renderPanel();
    fireEvent.click(screen.getByRole("button", { name: /find routes/i }));

    expect((await screen.findByRole("alert")).textContent).toContain(
      "No routes available for that request.",
    );
  });
});
