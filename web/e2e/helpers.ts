import type { Page } from "@playwright/test";
import { expect } from "@playwright/test";

const signInHeading = (page: Page) => page.getByRole("heading", { name: "Sign in" });

/**
 * Click a seeded person on the sign-in page the browser is already showing.
 * Doesn't navigate, so router state carried to `/` (a deep link, or the sign-out flag) is kept.
 * Matches the person's name exactly, not the team and role text on the same button.
 */
export async function pickPerson(page: Page, personName: string): Promise<void> {
  await expect(signInHeading(page)).toBeVisible();
  await page
    .getByRole("button")
    .filter({ has: page.getByText(personName, { exact: true }) })
    .click();
  await expect(signInHeading(page)).not.toBeVisible({ timeout: 20_000 });
}

/** Open the sign-in page fresh and sign in. Use pickPerson when the test is about state carried to `/`. */
export async function signInAs(page: Page, personName: string): Promise<void> {
  await page.goto("/");
  await pickPerson(page, personName);
}

export async function signOut(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL("/");
  await expect(signInHeading(page)).toBeVisible();
}

export const people = {
  platformAdmin: "Platform admin",
  riskReviewer: "Risk reviewer",
  headOfProcurement: "Head of Procurement",
  faisal: "Faisal",
} as const;
