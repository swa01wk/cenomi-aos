import { defineConfig, devices } from "@playwright/test";

/**
 * Presenter / full-journey demos. Does not replace `playwright.config.ts` (sign-in, M1 stops, gate).
 *
 * Run:  cd web && npm run e2e:demo
 * Needs: `make up`, worker running, `AOS_DEMO=1` on the API for vendor-reply injection.
 * Set `E2E_DEMO=1` to execute automation (otherwise specs are skipped — see e2e/demo/README.md for manual steps).
 */
const baseURL = process.env.E2E_BASE_URL ?? "http://localhost:8080";

export default defineConfig({
  testDir: "./e2e/demo",
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: 0,
  timeout: 600_000,
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report-demo" }]],
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "demo-chromium",
      testMatch: /\.spec\.ts$/,
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
