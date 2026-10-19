import { expect, test } from "@playwright/test";
import { people, signInAs, signOut } from "./helpers";

test("stop 1: publish pack through Risk and owner approvals", async ({ page }) => {
  await signInAs(page, people.platformAdmin);
  await expect(page).toHaveURL("/console/packs");

  // Each pack is a Panel (a region named after the pack); the first one is the pack under test.
  const packName = await page.getByRole("heading", { level: 2 }).first().innerText();
  const packPanel = page.getByRole("region", { name: packName, exact: true });

  await packPanel.getByRole("button", { name: "Sync from folder" }).click();
  await expect(packPanel.getByText(/^(Stored as|Already stored)/)).toBeVisible({ timeout: 60_000 });
  // While an action runs, the page's buttons are disabled with a reason (which joins their accessible name),
  // and a click on them is ignored. Wait until Validate is enabled again before clicking it.
  await expect(packPanel.getByRole("button", { name: "Validate", exact: true })).toBeVisible({ timeout: 30_000 });

  await packPanel.getByRole("button", { name: "Validate", exact: true }).click();
  // Wait for the action to finish (the busy label also matches "Valid…"), then read the report.
  await expect(packPanel.getByRole("button", { name: /^Validating/ })).toHaveCount(0, { timeout: 60_000 });
  await expect(packPanel.getByText("Valid", { exact: true })).toBeVisible();

  await packPanel.getByRole("button", { name: "Request publish", exact: true }).click();
  const requestPanel = packPanel.getByRole("region", { name: /^Publish request / });
  await expect(requestPanel).toBeVisible({ timeout: 30_000 });

  await signOut(page);

  await signInAs(page, people.riskReviewer);
  await page.goto("/console/packs");
  const policiesRow = page
    .getByRole("region", { name: /^Publish request / })
    .getByRole("listitem")
    .filter({ hasText: "Policies" });
  await policiesRow.getByRole("button", { name: "Approve", exact: true }).click();
  await expect(policiesRow).toContainText("approved", { timeout: 30_000 });

  await signOut(page);

  await signInAs(page, people.headOfProcurement);
  await page.goto("/console/packs");
  const seatsRow = page
    .getByRole("region", { name: /^Publish request / })
    .getByRole("listitem")
    .filter({ hasText: "Seats and workflows" });
  await seatsRow.getByRole("button", { name: "Approve", exact: true }).click();
  await expect(seatsRow).toContainText("approved", { timeout: 30_000 });
  // The version's status pill reads exactly "published".
  await expect(
    page.getByRole("region", { name: packName, exact: true }).getByText("published", { exact: true }),
  ).toBeVisible({ timeout: 30_000 });
});
