import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests drive the real browser against the real API. Nothing is
 * stubbed: if the agent graphs, the MCP gateway or the database are broken,
 * these fail. Both servers are assumed to be running (see `scripts/dev.sh`)
 * unless PLAYWRIGHT_MANAGED_SERVERS is set.
 */
// 3000 to match scripts/dev.sh, CORS_ORIGINS in .env.example, the README and CI.
// This defaulted to 3010, which nothing else in the repo serves — so the
// documented local flow (`scripts/dev.sh` then `make e2e`) hit an empty port,
// and CI only passed because it sets E2E_BASE_URL explicitly.
const WEB = process.env.E2E_BASE_URL ?? "http://127.0.0.1:3000";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  reporter: process.env.CI ? [["github"], ["list"]] : [["list"]],
  use: {
    baseURL: WEB,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } },
    { name: "mobile", use: { ...devices["Pixel 7"] } },
  ],
});
