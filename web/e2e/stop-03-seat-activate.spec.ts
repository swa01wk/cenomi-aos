import { expect, test } from "@playwright/test";
import { people, signInAs } from "./helpers";

test("stop 3: Seat owner activates to ACTIVE and AVAILABLE", async ({ page }) => {
  await signInAs(page, people.headOfProcurement);
  await page.getByRole("link", { name: "Seats", exact: true }).click();
  await page.locator("table tbody tr").first().getByRole("link").first().click();

  const seatStatus = page.getByRole("group", { name: "Seat status" });
  await expect(seatStatus.getByText("APPROVED", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Activate", exact: true }).click();
  await expect(seatStatus.getByText("ACTIVE", { exact: true })).toBeVisible({ timeout: 30_000 });
  await expect(seatStatus.getByText("AVAILABLE", { exact: true })).toBeVisible();
  await expect(page.getByRole("note")).toHaveCount(0);
});
