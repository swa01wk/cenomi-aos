import { expect, test } from "@playwright/test";
import { people, signInAs, signOut } from "./helpers";

test("stop 1: publish pack through Risk and owner approvals", async ({ page }) => {
  await signInAs(page, people.platformAdmin);
  await expect(page).toHaveURL("/console/packs");

  const packName = await page.getByRole("heading", { level: 2 }).first().innerText();
  const packPanel = page.getByRole("region", { name: packName });

  await packPanel.getByRole("button", { name: "Sync from folder" }).click();
  await expect(packPanel.getByText(/Stored as|Already stored/)).toBeVisible({ timeout: 60_000 });

  await packPanel.getByRole("button", { name: "Validate" }).click();
  await expect(packPanel.getByText(/Valid|Not valid/)).toBeVisible({ timeout: 60_000 });

  await packPanel.getByRole("button", { name: "Request publish" }).click();
  await expect(packPanel.getByText(/Publish request/)).toBeVisible({ timeout: 30_000 });

  await signOut(page);

  await signInAs(page, people.riskReviewer);
  await page.goto("/console/packs");
  const riskPanel = page.getByRole("region", { name: packName });
  const policiesRow = riskPanel.locator("li").filter({ hasText: /Policies/ });
  await policiesRow.getByRole("button", { name: "Approve" }).click();
  await expect(policiesRow.getByText(/approved/i)).toBeVisible({ timeout: 30_000 });

  await signOut(page);

  await signInAs(page, people.headOfProcurement);
  await page.goto("/console/packs");
  const ownerPanel = page.getByRole("region", { name: packName });
  const seatsRow = ownerPanel.locator("li").filter({ hasText: /Seats and workflows/ });
  await seatsRow.getByRole("button", { name: "Approve" }).click();
  await expect(ownerPanel.getByText("published", { exact: false })).toBeVisible({ timeout: 60_000 });
});
