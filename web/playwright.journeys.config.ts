import { defineConfig, devices } from "@playwright/test";

/**
 * Lifecycle journeys for the UAT slice (Quick Quote request → closed, full RFP request → award) and their negative
 * cases. Runs in CI on the scripted model; E2E_LIVE=1 runs the same specs on the real model with longer timeouts and
 * a video of every run (UAT evidence).
 *
 *   cd web && npm run e2e:journeys -- --project=quick-quote
 *   cd web && E2E_LIVE=1 npm run e2e:journeys -- --project=rfp --repeat-each=2
 *
 * Needs the stack up with AOS_DEMO=0 and AOS_VENDOR_SIM=1 (`make up` + .env, or .github/actions/aos-stack in CI).
 * Specs live in e2e/journeys/: quick-quote*.spec.ts, rfp*.spec.ts, negative*.spec.ts.
 * Stops 1–3 run first as setup: they publish the pack and activate the Seat on a fresh stack.
 */
const baseURL = process.env.E2E_BASE_URL ?? "http://localhost:8080";
const live = !!process.env.E2E_LIVE;

const setup = (name: string, file: RegExp, deps: string[] = []) => ({
  name,
  testMatch: file,
  dependencies: deps,
  fullyParallel: false,
  retries: 0,
  timeout: 180_000,
  use: { ...devices["Desktop Chrome"] },
});

const journey = (name: string, file: RegExp) => ({
  name,
  testMatch: file,
  dependencies: ["stop-03"],
  fullyParallel: false,
  // Scripted model: a whole journey in minutes. Real model: long RFP runs with many agent turns.
  timeout: live ? 2_400_000 : 900_000,
  use: { ...devices["Desktop Chrome"] },
});

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  // A retry on the scripted model hides real flakiness; journeys must pass first time.
  retries: 0,
  reporter: process.env.CI
    ? [
        ["github"],
        ["list"],
        ["html", { open: "never", outputFolder: "playwright-report-journeys" }],
        ["json", { outputFile: "journey-results/results.json" }],
      ]
    : [["list"], ["html", { open: "never", outputFolder: "playwright-report-journeys" }]],
  outputDir: "journey-results/artifacts",
  use: {
    baseURL,
    trace: live ? "on" : "retain-on-failure",
    screenshot: "only-on-failure",
    video: live ? "on" : "retain-on-failure",
  },
  projects: [
    setup("stop-01", /stop-01-publish\.spec\.ts/),
    setup("stop-02", /stop-02-seat-tests\.spec\.ts/, ["stop-01"]),
    setup("stop-03", /stop-03-seat-activate\.spec\.ts/, ["stop-02"]),
    journey("quick-quote", /journeys\/quick-quote.*\.spec\.ts/),
    journey("rfp", /journeys\/rfp.*\.spec\.ts/),
    journey("negative", /journeys\/negative.*\.spec\.ts/),
  ],
});
