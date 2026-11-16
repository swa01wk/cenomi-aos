import { expect, test } from "@playwright/test";
import { people, signInAs } from "./helpers";

test("stop 4: Faisal starts a job and lands on the job page", async ({ page }) => {
  await signInAs(page, people.faisal);
  await expect(page).toHaveURL("/workspace");

  await expect(page.getByRole("heading", { name: "What can we help with?" })).toBeVisible({ timeout: 30_000 });

  const need = "We need equipment for the north site before the busy season.";
  // "Message" also names the example-messages list on the chat home, so ask for the textbox.
  await page.getByRole("textbox", { name: "Message" }).fill(need);
  await page.getByRole("button", { name: "Send" }).click();

  await expect(page).toHaveURL(/\/workspace\/people\/.+\/.+/, { timeout: 60_000 });
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Conversation" }).getByRole("paragraph").filter({ hasText: need }),
  ).toBeVisible({ timeout: 30_000 });
});
