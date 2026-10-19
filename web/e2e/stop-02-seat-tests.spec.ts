import { expect, test } from "@playwright/test";
import { people, signInAs, signOut } from "./helpers";

test("stop 2: configure, evals, Risk approves, configurer activation refused", async ({ page }) => {
  await signInAs(page, people.platformAdmin);
  await page.getByRole("link", { name: "Seats", exact: true }).click();
  await expect(page).toHaveURL("/console/seats");

  const seatLink = page.locator("table tbody tr").first().getByRole("link").first();
  const displayName = await seatLink.locator("span").first().innerText();
  await seatLink.click();
  await expect(page.getByRole("heading", { level: 1, name: displayName })).toBeVisible();

  await page.getByRole("button", { name: "Configure" }).click();
  await expect(page.getByText(/Configuration checks · 6 of 6 pass/)).toBeVisible({ timeout: 30_000 });

  await page.getByRole("button", { name: "Run evals" }).click();
  await expect(page.getByText("running", { exact: false })).toBeVisible({ timeout: 15_000 }).catch(() => {});
  await expect
    .poll(
      async () => {
        const passed = await page.getByText(/\d+ \/ \d+/).count();
        return passed >= 1;
      },
      { timeout: 120_000 },
    )
    .toBe(true);

  await signOut(page);

  await signInAs(page, people.riskReviewer);
  await page.goto("/console/seats");
  await page.getByRole("link", { name: displayName }).first().click();
  await page.getByRole("button", { name: "Approve (Risk)" }).click();
  await expect(page.getByText("APPROVED")).toBeVisible({ timeout: 30_000 });

  await signOut(page);

  await signInAs(page, people.platformAdmin);
  await page.goto("/console/seats");
  await page.getByRole("link", { name: displayName }).first().click();
  await page.getByRole("button", { name: "Activate" }).click();
  await expect(page.getByText("You cannot activate a seat you configured")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("APPROVED")).toBeVisible();
});
