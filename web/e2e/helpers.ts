import type { Page } from "@playwright/test";
import { expect } from "@playwright/test";

/** Pick a seeded person on the sign-in page (fresh context each test). */
export async function signInAs(page: Page, personName: string): Promise<void> {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  const pick = page.getByRole("button", { name: personName });
  await pick.click();
  await expect(page.getByRole("heading", { name: "Sign in" })).not.toBeVisible({ timeout: 20_000 });
}

export async function signOut(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL("/");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
}

export const people = {
  platformAdmin: "Platform admin",
  riskReviewer: "Risk reviewer",
  headOfProcurement: "Head of Procurement",
  faisal: "Faisal",
} as const;
