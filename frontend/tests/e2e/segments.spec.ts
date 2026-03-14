import { expect, test } from "@playwright/test";

const segmentsResponse = {
  type: "FeatureCollection",
  features: [
    {
      type: "Feature",
      geometry: {
        type: "LineString",
        coordinates: [
          [-74.041, 40.7165],
          [-74.0355, 40.721],
        ],
      },
      properties: {
        segment_id: "seg-verified",
        composite_score: 88,
        verified: true,
        rating_count: 12,
        vibe_tag_counts: { waterfront: 6, scenic: 4 },
      },
    },
    {
      type: "Feature",
      geometry: {
        type: "LineString",
        coordinates: [
          [-74.048, 40.719],
          [-74.043, 40.723],
        ],
      },
      properties: {
        segment_id: "seg-unverified",
        composite_score: 42,
        verified: false,
        rating_count: 2,
        vibe_tag_counts: { cafes: 2 },
      },
    },
  ],
};

const segmentDetail = {
  segment_id: "seg-verified",
  composite_score: 88,
  verified: true,
  rating_count: 12,
  vibe_tag_counts: { waterfront: 6, scenic: 4 },
};

const waitForMap = async (page: import("@playwright/test").Page) => {
  await page.waitForFunction(() => {
    const hook = (window as any).__walkmap__;
    return Boolean(hook && (hook.ready || hook.error));
  });

  const mapError = await page.evaluate(() => (window as any).__walkmap__?.error ?? null);
  expect(mapError, mapError ?? "Map failed to load").toBeNull();
};

const waitForSegments = async (page: import("@playwright/test").Page) => {
  await page.waitForFunction(() => {
    const map = (window as any).__walkmap__?.map;
    const source = map?.getSource?.("segments");
    const data = source?._data;
    return Boolean(data && data.features && data.features.length >= 2);
  });
};

test("loads segments and respects overlay toggles", async ({ page }) => {
  let bboxRequests = 0;
  await page.route("**/segments?bbox=**", async (route) => {
    bboxRequests += 1;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(segmentsResponse),
    });
  });

  await page.goto("/");
  await waitForMap(page);
  await waitForSegments(page);

  const visibility = await page.evaluate(() => {
    const map = (window as any).__walkmap__?.map;
    return {
      verified: map.getLayoutProperty("segments-verified", "visibility"),
      unverified: map.getLayoutProperty("segments-unverified", "visibility"),
    };
  });

  expect(visibility.verified).toBe("visible");
  expect(visibility.unverified).toBe("visible");

  await page.getByRole("button", { name: "Overlay On" }).click();

  await page.waitForFunction(() => {
    const map = (window as any).__walkmap__?.map;
    return (
      map.getLayoutProperty("segments-verified", "visibility") === "none" &&
      map.getLayoutProperty("segments-unverified", "visibility") === "none"
    );
  });

  await page.getByRole("button", { name: "Overlay Off" }).click();

  await page.waitForFunction(() => {
    const map = (window as any).__walkmap__?.map;
    return (
      map.getLayoutProperty("segments-verified", "visibility") === "visible" &&
      map.getLayoutProperty("segments-unverified", "visibility") === "visible"
    );
  });

  await page.getByRole("button", { name: "Verified Only" }).click();

  await page.waitForFunction(() => {
    const map = (window as any).__walkmap__?.map;
    return (
      map.getLayoutProperty("segments-verified", "visibility") === "visible" &&
      map.getLayoutProperty("segments-unverified", "visibility") === "none"
    );
  });

  expect(bboxRequests).toBeGreaterThan(0);
});

test("clicking a segment opens the detail panel", async ({ page }) => {
  await page.route("**/segments?bbox=**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(segmentsResponse),
    });
  });

  await page.route("**/segments/seg-verified", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(segmentDetail),
    });
  });

  await page.goto("/");
  await waitForMap(page);
  await waitForSegments(page);

  const clickPoint = await page.evaluate(() => {
    const map = (window as any).__walkmap__?.map;
    const rect = map.getContainer().getBoundingClientRect();
    const point = map.project([-74.041, 40.7165]);
    return { x: rect.left + point.x, y: rect.top + point.y };
  });

  const usedMock = await page.evaluate(() => {
    const map = (window as any).__walkmap__?.map;
    if (map?.__isMock) {
      map.__triggerClick({ x: 0, y: 0 });
      return true;
    }
    return false;
  });

  if (!usedMock) {
    await page.mouse.click(clickPoint.x, clickPoint.y);
  }

  await expect(page.getByText("Segment Detail")).toBeVisible();
  await expect(page.getByText("Score:")).toBeVisible();
  await expect(page.getByText("Status: Verified")).toBeVisible();
  await expect(page.getByText("Ratings: 12")).toBeVisible();

  const breakdownButton = page.getByRole("button", { name: "Score breakdown" });
  await expect(breakdownButton).toBeVisible();
  await breakdownButton.click();
  await expect(page.getByText("AI factors", { exact: true })).toBeVisible();
  await breakdownButton.click();
  await expect(page.getByText("AI factors", { exact: true })).not.toBeVisible();
});

test("debounces fetch on map moveend", async ({ page }) => {
  let bboxRequests = 0;
  await page.route("**/segments?bbox=**", async (route) => {
    bboxRequests += 1;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(segmentsResponse),
    });
  });

  await page.goto("/");
  await waitForMap(page);
  await waitForSegments(page);

  const before = bboxRequests;

  await page.evaluate(() => {
    const map = (window as any).__walkmap__?.map;
    map.panBy([180, 0], { animate: false });
  });

  await page.waitForTimeout(400);
  expect(bboxRequests).toBeGreaterThan(before);
});
