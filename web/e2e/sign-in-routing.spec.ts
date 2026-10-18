import { expect, test } from "@playwright/test";
import { people, signInAs, signOut } from "./helpers";

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
    await signInAs(page, people.riskReviewer);
    await expect(page).toHaveURL("/console/audit");
  });

  test("sign-out does not leak deep link: platform admin then faisal", async ({ page }) => {
    await signInAs(page, people.platformAdmin);
    await expect(page).toHaveURL("/console/packs");
    await signOut(page);
    await signInAs(page, people.faisal);
    await expect(page).toHaveURL("/workspace");
  });

  test("deep link: signed out audit URL, then risk reviewer", async ({ page }) => {
    await page.goto("/console/audit");
    await expect(page).toHaveURL("/");
    await signInAs(page, people.riskReviewer);
    await expect(page).toHaveURL("/console/audit");
  });

  test("console deep link ignored for workspace user", async ({ page }) => {
    await page.goto("/console/packs");
    await expect(page).toHaveURL("/");
    await signInAs(page, people.faisal);
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

    let meGets = 0;
    page.on("response", (res) => {
      const path = new URL(res.url()).pathname;
      if (path.endsWith("/api/me") && res.request().method() === "GET") {
        meGets += 1;
      }
    });

    await page.evaluate(() => localStorage.setItem("aos.token", "bad"));
    await page.reload();

    await expect(page).toHaveURL("/");
    await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
    await expect.poll(() => meGets).toBe(1);
  });

  test("kernel unreachable shows retry", async ({ page }) => {
    await signInAs(page, people.platformAdmin);
    await expect(page).toHaveURL("/console/packs");

    await page.route("**/api/me", (route) => route.abort("failed"));
    await page.reload();

    await expect(page.getByText("Can't load your session")).toBeVisible();
    await expect(page.getByRole("button", { name: "Retry" })).toBeVisible();
  });
});
