import { expect, test } from "@playwright/test";
import { people, signInAs } from "./helpers";

test("stop 5: agent reply streams, brief versions appear, reload keeps state", async ({ page }) => {
  await signInAs(page, people.faisal);
  await page.getByRole("link", { name: "New job" }).click();
  await page.locator('label input[type="radio"]').first().check();
  const need = "Need restock units for building north, same as last order if possible.";
  await page.getByLabel("Describe the need").fill(need);
  await page.getByRole("button", { name: "Start" }).click();
  await expect(page).toHaveURL(/\/workspace\/jobs\/.+/, { timeout: 60_000 });

  const conversation = page.getByRole("region", { name: "Conversation" });
  await expect(conversation.getByText(need)).toBeVisible();

  await expect(conversation.getByText(/Delivery date|budget|quality/i)).toBeVisible({ timeout: 120_000 });

  const workPanel = page.getByRole("complementary", { name: "Work in progress" });
  await expect(workPanel.getByRole("tab").first()).toBeVisible({ timeout: 120_000 });
  await expect(workPanel.getByText(/v1/i)).toBeVisible();

  const reply =
    "Delivery is 1 Nov to the north warehouse. Budget guidance is internal at 15000. Facilities manager signs off on quality.";
  await conversation.getByLabel("Message").fill(reply);
  await conversation.getByRole("button", { name: "Send" }).click();
  await expect(conversation.getByText(reply)).toBeVisible();

  await expect(conversation.getByText(/updated|Thanks/i)).toBeVisible({ timeout: 120_000 });
  await expect(workPanel.getByText(/v2/i)).toBeVisible({ timeout: 120_000 });

  const url = page.url();
  await page.reload();
  await expect(page).toHaveURL(url);
  await expect(conversation.getByText(need)).toBeVisible();
  await expect(conversation.getByText(reply)).toBeVisible();
  await expect(workPanel.getByText(/v2/i)).toBeVisible();
});
