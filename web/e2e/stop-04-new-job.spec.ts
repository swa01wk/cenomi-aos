import { expect, test } from "@playwright/test";
import { people, signInAs } from "./helpers";

test("stop 4: Faisal starts a job and lands on the job page", async ({ page }) => {
  await signInAs(page, people.faisal);
  await expect(page).toHaveURL("/workspace");

  await page.getByRole("link", { name: "New job" }).click();
  await expect(page).toHaveURL("/workspace/new");

  const workerCard = page.locator(".ws-worker-card").first();
  await expect(workerCard).toBeVisible({ timeout: 30_000 });

  const workflowTitle = page.locator('label input[type="radio"]').first();
  await workflowTitle.check();

  const need = "We need equipment for the north site before the busy season.";
  await page.getByLabel("Describe the need").fill(need);
  await page.getByRole("button", { name: "Start" }).click();

  await expect(page).toHaveURL(/\/workspace\/jobs\/.+/, { timeout: 60_000 });
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  // The need also titles the job (heading and rail), so check the person's turn in the conversation.
  await expect(page.getByRole("region", { name: "Conversation" }).getByText(need, { exact: true })).toBeVisible({
    timeout: 30_000,
  });
});
