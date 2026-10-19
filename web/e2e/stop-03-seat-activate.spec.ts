import { expect, test } from "@playwright/test";
import { people, signInAs } from "./helpers";

test("stop 3: Seat owner activates to ACTIVE and AVAILABLE", async ({ page }) => {
  await signInAs(page, people.headOfProcurement);
  await page.getByRole("link", { name: "Seats", exact: true }).click();

  const seatLink = page.locator("table tbody tr").first().getByRole("link").first();
  const displayName = await seatLink.locator("span").first().innerText();
  await seatLink.click();

  await page.getByRole("button", { name: "Activate" }).click();
  await expect(page.getByText("ACTIVE")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("AVAILABLE")).toBeVisible();
  await expect(page.getByRole("heading", { level: 1, name: displayName })).toBeVisible();
});
