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
  await expect(conversation.getByRole("paragraph").filter({ hasText: need })).toBeVisible();

  // Attempt 1 (fake script): saves the first draft, then asks three questions. They arrive over the stream,
  // without a reload.
  await expect(conversation.getByText(/Delivery date/).first()).toBeVisible({ timeout: 120_000 });

  const workPanel = page.getByRole("complementary", { name: "Work in progress" });
  const docTab = workPanel.getByRole("tab", { selected: true });
  await expect(docTab).toContainText("v1", { timeout: 120_000 });

  const reply =
    "Delivery is 1 Nov to the north warehouse. Budget guidance is internal at 15000. Facilities manager signs off on quality.";
  await conversation.getByLabel("Message").fill(reply);
  await conversation.getByRole("button", { name: "Send" }).click();
  await expect(conversation.getByText(reply, { exact: true })).toBeVisible();

  // Attempt 2: saves v2 and streams its reply; the completed turn replaces the streamed text.
  await expect(conversation.getByText("Thanks, your brief is updated.", { exact: true })).toBeVisible({
    timeout: 120_000,
  });
  await expect(docTab).toContainText("v2", { timeout: 120_000 });
  await expect(workPanel.getByRole("combobox", { name: "Version" }).locator("option")).toHaveCount(2);

  const url = page.url();
  await page.reload();
  await expect(page).toHaveURL(url);
  await expect(conversation.getByRole("paragraph").filter({ hasText: need })).toBeVisible();
  await expect(conversation.getByText(reply, { exact: true })).toBeVisible();
  await expect(conversation.getByText("Thanks, your brief is updated.", { exact: true })).toBeVisible();
  await expect(docTab).toContainText("v2");
});
