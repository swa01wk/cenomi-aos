import { defineConfig, devices } from "@playwright/test";

const baseURL = process.env.E2E_BASE_URL ?? "http://localhost:8080";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      testMatch: /sign-in-routing\.spec\.ts/,
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "stop-01",
      testMatch: /stop-01-publish\.spec\.ts/,
      fullyParallel: false,
      retries: 0,
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "stop-02",
      testMatch: /stop-02-seat-tests\.spec\.ts/,
      dependencies: ["stop-01"],
      fullyParallel: false,
      retries: 0,
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "stop-03",
      testMatch: /stop-03-seat-activate\.spec\.ts/,
      dependencies: ["stop-02"],
      fullyParallel: false,
      retries: 0,
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
