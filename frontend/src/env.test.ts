import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("frontend env helpers", () => {
  it("returns an empty API base when VITE_API_BASE_URL is unset", async () => {
    const { getApiBase } = await import("./env");

    expect(getApiBase()).toBe("");
  });

  it("trims a trailing slash from VITE_API_BASE_URL", async () => {
    vi.stubEnv("VITE_API_BASE_URL", "https://walkmap-api.up.railway.app/");

    const { getApiBase } = await import("./env");

    expect(getApiBase()).toBe("https://walkmap-api.up.railway.app");
  });

  it("uses the OpenFreeMap style by default", async () => {
    const { getMapStyleUrl } = await import("./env");

    expect(getMapStyleUrl()).toBe("https://tiles.openfreemap.org/styles/liberty");
  });

  it("uses VITE_MAP_STYLE_URL when provided", async () => {
    vi.stubEnv("VITE_MAP_STYLE_URL", "https://tiles.example.com/styles/custom");

    const { getMapStyleUrl } = await import("./env");

    expect(getMapStyleUrl()).toBe("https://tiles.example.com/styles/custom");
  });
});
