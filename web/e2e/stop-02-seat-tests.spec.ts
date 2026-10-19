import { expect, test, type Page } from "@playwright/test";
import { people, signInAs, signOut } from "./helpers";

const seatStatus = (page: Page) => page.getByRole("group", { name: "Seat status" });

test("stop 2: configure, evals, Risk approves, configurer activation refused", async ({ page }) => {
  await signInAs(page, people.platformAdmin);
  await page.getByRole("link", { name: "Seats", exact: true }).click();
  await expect(page).toHaveURL("/console/seats");

  // Publishing created the Seat; open the first one and remember its page.
  await page.locator("table tbody tr").first().getByRole("link").first().click();
  await expect(page).toHaveURL(/\/console\/seats\/.+/);
  const seatUrl = new URL(page.url()).pathname;
  await expect(seatStatus(page).getByText("DRAFT", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Configure", exact: true }).click();
  await expect(page.getByText(/^Configuration checks · (\d+) of \1 pass$/)).toBeVisible({ timeout: 30_000 });
  await expect(seatStatus(page).getByText("CONFIGURED", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Run evals", exact: true }).click();
  const evals = page.getByRole("region", { name: "Evaluation runs in the sandbox" });
  await expect(evals.getByText("No evaluation runs yet.")).toHaveCount(0, { timeout: 30_000 });
  // Every suite finishes (the page polls while any run is running) and none failed.
  await expect(evals.getByText("running", { exact: true })).toHaveCount(0, { timeout: 120_000 });
  await expect(evals.getByText("failed", { exact: true })).toHaveCount(0);
  await expect(evals.getByText("passed", { exact: true }).first()).toBeVisible();

  await signOut(page);

  await signInAs(page, people.riskReviewer);
  await page.goto(seatUrl);
  await page.getByRole("button", { name: "Approve (Risk)", exact: true }).click();
  await expect(seatStatus(page).getByText("APPROVED", { exact: true })).toBeVisible({ timeout: 30_000 });

  await signOut(page);

  // The platform admin configured the Seat, so the kernel refuses their activation.
  await signInAs(page, people.platformAdmin);
  await page.goto(seatUrl);
  await page.getByRole("button", { name: "Activate", exact: true }).click();
  await expect(page.getByRole("note")).toContainText("You cannot activate a seat you configured", {
    timeout: 30_000,
  });
  await expect(seatStatus(page).getByText("APPROVED", { exact: true })).toBeVisible();
});
