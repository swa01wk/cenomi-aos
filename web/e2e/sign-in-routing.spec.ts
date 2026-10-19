import { expect, test } from "@playwright/test";
import { people, pickPerson, signInAs, signOut } from "./helpers";

test.describe("sign-in and routing", () => {
  test("platform admin lands on /console/packs", async ({ page }) => {
    await signInAs(page, people.platformAdmin);
    await expect(page).toHaveURL("/console/packs");
    await expect(page.getByRole("heading", { name: "Domain packs" })).toBeVisible();
  });

  test("risk reviewer lands on /console/audit", async ({ page }) => {
    await signInAs(page, people.riskReviewer);
    await expect(page).toHaveURL("/console/audit");
    await expect(page.getByRole("heading", { name: "Audit log" })).toBeVisible();
  });

  test("head of procurement lands on /console/packs", async ({ page }) => {
    await signInAs(page, people.headOfProcurement);
    await expect(page).toHaveURL("/console/packs");
    await expect(page.getByRole("heading", { name: "Domain packs" })).toBeVisible();
  });

  test("faisal lands on workspace; console route shows not available", async ({ page }) => {
    await signInAs(page, people.faisal);
    await expect(page).toHaveURL("/workspace");
    await page.goto("/console/packs");
    await expect(page.getByRole("heading", { name: "Console not available" })).toBeVisible();
  });

  test("sign-out does not leak deep link: faisal then risk reviewer", async ({ page }) => {
    await signInAs(page, people.faisal);
    await expect(page).toHaveURL("/workspace");
    await signOut(page);
    // No page.goto: the bug carried the previous page to `/` in router state, which a reload would clear.
    await pickPerson(page, people.riskReviewer);
    await expect(page).toHaveURL("/console/audit");
  });

  test("sign-out does not leak deep link: platform admin on org, then head of procurement", async ({ page }) => {
    await signInAs(page, people.platformAdmin);
    await page.getByRole("link", { name: "Organization", exact: true }).click();
    await expect(page).toHaveURL("/console/org");
    await signOut(page);
    // Console to Console, so a leaked /console/org would be honoured instead of the default /console/packs.
    await pickPerson(page, people.headOfProcurement);
    await expect(page).toHaveURL("/console/packs");
  });

  // Deep-link tests open a page that isn't the person's default landing, so they fail if the link is dropped.
  test("deep link: signed out org URL, then risk reviewer", async ({ page }) => {
    await page.goto("/console/org");
    await expect(page).toHaveURL("/");
    await pickPerson(page, people.riskReviewer);
    await expect(page).toHaveURL("/console/org");
  });

  test("deep link: signed out audit URL, then platform admin", async ({ page }) => {
    await page.goto("/console/audit");
    await expect(page).toHaveURL("/");
    await pickPerson(page, people.platformAdmin);
    await expect(page).toHaveURL("/console/audit");
    await expect(page.getByRole("heading", { name: "Audit log" })).toBeVisible();
  });

  test("console deep link ignored for workspace user", async ({ page }) => {
    await page.goto("/console/packs");
    await expect(page).toHaveURL("/");
    await pickPerson(page, people.faisal);
    await expect(page).toHaveURL("/workspace");
  });

  test("old hash link redirects to real path", async ({ page }) => {
    await signInAs(page, people.platformAdmin);
    await page.goto("/#/console/org");
    await expect(page).toHaveURL("/console/org");
    await expect(page.getByRole("heading", { name: "Procurement demo organization" })).toBeVisible();
  });

  test("reload keeps session and path; direct org URL works", async ({ page }) => {
    await signInAs(page, people.riskReviewer);
    await expect(page).toHaveURL("/console/audit");
    await page.reload();
    await expect(page).toHaveURL("/console/audit");
    await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

    await page.goto("/console/org");
    await expect(page).toHaveURL("/console/org");
    await expect(page.getByRole("heading", { name: "Procurement demo organization" })).toBeVisible();
  });

  test("bad token clears session after one 401 on /api/me", async ({ page }) => {
    await signInAs(page, people.platformAdmin);
    await expect(page).toHaveURL("/console/packs");

    const meStatuses: number[] = [];
    page.on("response", (res) => {
      const path = new URL(res.url()).pathname;
      if (path.endsWith("/api/me") && res.request().method() === "GET") {
        meStatuses.push(res.status());
      }
    });

    await page.evaluate(() => localStorage.setItem("aos.token", "bad"));
    await page.reload();

    await expect(page).toHaveURL("/");
    await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
    // Let any late or repeated /me calls happen before counting.
    await page.waitForLoadState("networkidle");
    expect(meStatuses).toEqual([401]);
    expect(await page.evaluate(() => localStorage.getItem("aos.token"))).toBeNull();
  });

  test("kernel unreachable shows retry", async ({ page }) => {
    await signInAs(page, people.platformAdmin);
    await expect(page).toHaveURL("/console/packs");

    await page.route("**/api/me", (route) => route.abort("failed"));
    await page.reload();

    await expect(page.getByText("Can't load your session")).toBeVisible();
    await expect(page.getByRole("button", { name: "Try again" })).toBeVisible();
  });
});
