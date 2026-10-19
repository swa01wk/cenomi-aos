import { defineConfig, devices } from "@playwright/test";

const baseURL = process.env.E2E_BASE_URL ?? "http://localhost:8080";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 1 : undefined,
  // In CI, also report failures as GitHub annotations (readable without downloading the HTML report).
  reporter: process.env.CI
    ? [["github"], ["list"], ["html", { open: "never" }]]
    : [["list"], ["html", { open: "never" }]],
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
      // Whole walkthrough steps (evals, agent turns); the default 30 s per test is too short in CI.
      timeout: 180_000,
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "stop-02",
      testMatch: /stop-02-seat-tests\.spec\.ts/,
      dependencies: ["stop-01"],
      fullyParallel: false,
      retries: 0,
      // Whole walkthrough steps (evals, agent turns); the default 30 s per test is too short in CI.
      timeout: 180_000,
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "stop-03",
      testMatch: /stop-03-seat-activate\.spec\.ts/,
      dependencies: ["stop-02"],
      fullyParallel: false,
      retries: 0,
      // Whole walkthrough steps (evals, agent turns); the default 30 s per test is too short in CI.
      timeout: 180_000,
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "stop-04",
      testMatch: /stop-04-new-job\.spec\.ts/,
      dependencies: ["stop-03"],
      fullyParallel: false,
      retries: 0,
      // Whole walkthrough steps (evals, agent turns); the default 30 s per test is too short in CI.
      timeout: 180_000,
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "stop-05",
      testMatch: /stop-05-chat\.spec\.ts/,
      dependencies: ["stop-04"],
      fullyParallel: false,
      retries: 0,
      // Whole walkthrough steps (evals, agent turns); the default 30 s per test is too short in CI.
      timeout: 180_000,
      use: { ...devices["Desktop Chrome"] },
    },
    // M1 exit gate on the real model (`make gate`). Only with E2E_GATE=1, so CI and a plain `npm run e2e`
    // (scripted model) never run it. Running it also runs stops 1–3 first, on a fresh stack.
    ...(process.env.E2E_GATE
      ? [
          {
            name: "gate",
            testMatch: /m1-gate-real-model\.spec\.ts/,
            dependencies: ["stop-03"],
            fullyParallel: false,
            retries: 0,
            // Two real-model turns and the checks around them.
            timeout: 600_000,
            use: { ...devices["Desktop Chrome"] },
          },
        ]
      : []),
  ],
});
