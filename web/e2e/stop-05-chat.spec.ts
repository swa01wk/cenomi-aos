import { expect, test } from "@playwright/test";
import { people, signInAs } from "./helpers";

test.afterEach(async ({ page }, testInfo) => {
  // CI artifacts are not always reachable; print what the page showed so the log alone explains a failure.
  if (testInfo.status !== testInfo.expectedStatus) {
    console.log(`--- page at failure: ${page.url()} ---\n${await page.locator("body").innerText().catch(() => "")}`);
  }
});

test("stop 5: agent reply streams, brief versions appear, reload keeps state", async ({ page }) => {
  await signInAs(page, people.faisal);
  // Message the sourcing specialist directly so the job runs request intake (the chat home routes small talk and
  // vague needs to the workspace coordinator first; stop 4 covers that path).
  await page.goto("/workspace/people/seat_sourcing_poc");
  const need = "Need restock units for building north, same as last order if possible.";
  await page.getByRole("textbox", { name: /^Message / }).fill(need);
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page).toHaveURL(/\/workspace\/people\/seat_sourcing_poc\/.+/, { timeout: 60_000 });

  const conversation = page.getByRole("region", { name: "Conversation" });
  await expect(conversation.getByRole("paragraph").filter({ hasText: need })).toBeVisible();

  // Quick Quote opens in conversation: the specialist acknowledges first, and intake starts on the next message
  // once the thread carries request detail.
  await expect(conversation.getByText(/I'll help you shape this/).first()).toBeVisible({ timeout: 120_000 });
  const detail = "4 heavy-duty cleaning trolleys for the north warehouse, please.";
  await conversation.getByRole("textbox", { name: "Message" }).fill(detail);
  await conversation.getByRole("button", { name: "Send" }).click();
  await expect(conversation.getByText(detail, { exact: true })).toBeVisible();

  // Intake attempt 1 (fake script): saves the first draft, then asks three questions. They arrive over the stream,
  // without a reload.
  await expect(conversation.getByText(/Delivery date/).first()).toBeVisible({ timeout: 120_000 });

  // The work panel opens on the first draft; open it by hand if it did not.
  const docsButton = page.getByRole("button", { name: "Documents", exact: true });
  if (await docsButton.isVisible()) await docsButton.click();
  const workPanel = page.getByRole("complementary", { name: "Work in progress" });
  await expect(workPanel.getByText("v1 · latest")).toBeVisible({ timeout: 120_000 });

  const reply =
    "Delivery is 1 Nov to the north warehouse. Budget guidance is internal at 15000. Facilities manager signs off on quality.";
  await conversation.getByRole("textbox", { name: "Message" }).fill(reply);
  await conversation.getByRole("button", { name: "Send" }).click();
  await expect(conversation.getByText(reply, { exact: true })).toBeVisible();

  // Attempt 2: saves v2, passes brief_schema, and the requester is asked to confirm the brief (stop 6 confirms it).
  const confirmBrief = conversation.getByRole("button", { name: "Confirm the brief", exact: true });
  await expect(confirmBrief).toBeVisible({ timeout: 120_000 });
  await expect(workPanel.getByText("v2 · latest")).toBeVisible({ timeout: 120_000 });
  await expect(workPanel.getByRole("combobox", { name: "Version" }).locator("option")).toHaveCount(2);

  const url = page.url();
  await page.reload();
  await expect(page).toHaveURL(url);
  await expect(conversation.getByRole("paragraph").filter({ hasText: need })).toBeVisible();
  await expect(conversation.getByText(reply, { exact: true })).toBeVisible();
  await expect(confirmBrief).toBeVisible({ timeout: 30_000 });
  await expect(workPanel.getByText("v2 · latest")).toBeVisible({ timeout: 30_000 });
});
