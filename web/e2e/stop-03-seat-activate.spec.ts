import { expect, test, type Page } from "@playwright/test";
import { people, signInAs, signOut } from "./helpers";

test.describe.configure({ mode: "serial" });

const seatStatus = (page: Page) => page.getByRole("group", { name: "Seat status" });

test("stop 3: Seat owner activates to ACTIVE and AVAILABLE", async ({ page }) => {
  await signInAs(page, people.headOfProcurement);
  await page.getByRole("link", { name: "Seats", exact: true }).click();
  await page.locator("table tbody tr").first().getByRole("link").first().click();

  await expect(seatStatus(page).getByText("APPROVED", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Activate", exact: true }).click();
  await expect(seatStatus(page).getByText("ACTIVE", { exact: true })).toBeVisible({ timeout: 30_000 });
  await expect(seatStatus(page).getByText("AVAILABLE", { exact: true })).toBeVisible();
  await expect(page.getByRole("note")).toHaveCount(0);
});

// The workspace landing (stop 4) messages the workspace coordinator, so its Seat must be active too. Seats are
// listed by name, so stops 2–3 above only cover the first one. The coordinator Seat declares no eval suites, so
// Run evals promotes it to TESTING at once.
test("stop 3b: workspace coordinator Seat configured, approved and active", async ({ page }) => {
  const seatPath = "/console/seats/seat_workspace_coordinator";

  await signInAs(page, people.platformAdmin);
  await page.goto(seatPath);
  await expect(seatStatus(page).getByText("DRAFT", { exact: true })).toBeVisible({ timeout: 30_000 });
  await page.getByRole("button", { name: "Configure", exact: true }).click();
  await expect(seatStatus(page).getByText("CONFIGURED", { exact: true })).toBeVisible({ timeout: 30_000 });
  // No suites to run: Run evals moves the Seat straight to TESTING, ready for Risk approval.
  await page.getByRole("button", { name: "Run evals", exact: true }).click();
  await expect(seatStatus(page).getByText("TESTING", { exact: true })).toBeVisible({ timeout: 30_000 });
  await signOut(page);

  await signInAs(page, people.riskReviewer);
  await page.goto(seatPath);
  await page.getByRole("button", { name: "Approve (Risk)", exact: true }).click();
  await expect(seatStatus(page).getByText("APPROVED", { exact: true })).toBeVisible({ timeout: 30_000 });
  await signOut(page);

  await signInAs(page, people.headOfProcurement);
  await page.goto(seatPath);
  await page.getByRole("button", { name: "Activate", exact: true }).click();
  await expect(seatStatus(page).getByText("ACTIVE", { exact: true })).toBeVisible({ timeout: 30_000 });
  await expect(seatStatus(page).getByText("AVAILABLE", { exact: true })).toBeVisible();
});
