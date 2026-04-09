import { defineConfig } from "@playwright/test";

const playwrightApiBaseUrl = process.env.PLAYWRIGHT_API_BASE_URL ?? "http://127.0.0.1:8000";

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 60_000,
  expect: {
    timeout: 10_000,
  },
  use: {
    baseURL: "http://127.0.0.1:5173",
    trace: "retain-on-failure",
    launchOptions: {
      args: ["--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"],
    },
  },
  webServer: {
    command: "npm run dev -- --host 127.0.0.1 --port 5173",
    url: "http://127.0.0.1:5173",
    reuseExistingServer: true,
    env: {
      VITE_API_BASE_URL: playwrightApiBaseUrl,
      VITE_MAP_STYLE_URL: "http://127.0.0.1:5173/test-style.json",
      VITE_E2E: "true",
      VITE_E2E_MOCK_MAP: "true",
    },
  },
});
