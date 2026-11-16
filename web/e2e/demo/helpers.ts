import type { Page } from "@playwright/test";
import { expect } from "@playwright/test";
import { pickPerson, signInAs } from "../helpers";

export { pickPerson, signInAs };

export const demoPeople = {
  faisal: "Faisal",
  noura: "Noura",
  platformAdmin: "Platform admin",
} as const;

const apiBase = () => process.env.E2E_API_URL ?? "http://localhost:8000";

export async function mintSessionToken(personId: string): Promise<string> {
  const res = await fetch(`${apiBase()}/api/auth/session`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ person_id: personId }),
  });
  if (!res.ok) {
    throw new Error(`session mint failed: ${res.status} ${await res.text()}`);
  }
  const body = (await res.json()) as { token: string };
  return body.token;
}

type OpenRfq = {
  instance_id: string;
  conversation_id: string;
  supplier_id: string;
  supplier?: string;
  replied?: boolean;
};

export async function fetchDemoState(consoleToken: string): Promise<{ open_rfqs?: OpenRfq[] }> {
  const res = await fetch(`${apiBase()}/api/demo/state`, {
    headers: { Authorization: `Bearer ${consoleToken}` },
  });
  if (!res.ok) {
    throw new Error(`demo state failed: ${res.status} ${await res.text()}`);
  }
  return (await res.json()) as { open_rfqs?: OpenRfq[] };
}

/** Paste-ready supplier reply (include [SUP-…] and labeled SAR lines for triage). */
export function vendorQuoteBody(instanceId: string, supplierId: string, opts?: { unit?: number; total?: number }) {
  const unit = opts?.unit ?? 4200;
  const total = opts?.total ?? unit * 5;
  return [
    `Reference: ${instanceId}:${supplierId}`,
    "",
    "We can supply as requested.",
    "",
    `Unit price (SAR): ${unit}`,
    `Total (SAR): ${total}`,
    "Lead time: 5 business days",
    "Warranty: 12 months",
  ].join("\n");
}

export async function simulateVendorReply(
  userToken: string,
  conversationId: string,
  supplierId: string,
  body: string,
): Promise<void> {
  const res = await fetch(`${apiBase()}/api/demo/vendor-replies`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${userToken}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ conversation_id: conversationId, supplier_id: supplierId, body }),
  });
  if (!res.ok) {
    throw new Error(`vendor-replies failed: ${res.status} ${await res.text()}`);
  }
}

export async function advanceDemoClockToNextTimer(consoleToken: string): Promise<void> {
  const res = await fetch(`${apiBase()}/api/demo/clock/advance`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${consoleToken}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ to_next_timer: true }),
  });
  if (!res.ok) {
    throw new Error(`clock advance failed: ${res.status} ${await res.text()}`);
  }
}

export async function waitForDecision(page: Page, title: string | RegExp, timeoutMs = 300_000): Promise<void> {
  await expect(page.getByRole("group", { name: title })).toBeVisible({ timeout: timeoutMs });
}

export async function confirmDecision(page: Page, buttonName: string | RegExp): Promise<void> {
  await page.getByRole("button", { name: buttonName }).click();
  await expect(page.getByRole("button", { name: buttonName })).not.toBeVisible({ timeout: 60_000 });
}

export async function sendChat(page: Page, text: string): Promise<void> {
  const conversation = page.getByRole("region", { name: "Conversation" });
  await conversation.getByLabel("Message").fill(text);
  await conversation.getByRole("button", { name: "Send" }).click();
  await expect(conversation.getByText(text, { exact: false })).toBeVisible({ timeout: 30_000 });
}

/** Start QQ or RFP via the sourcing specialist (same as POST /workspace/intake). */
export async function startFromNewJob(page: Page, need: string): Promise<void> {
  await page.goto("/workspace/people/seat_sourcing_poc");
  const composer = page.getByLabel("Message");
  await expect(composer).toBeVisible({ timeout: 30_000 });
  await composer.fill(need);
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page).toHaveURL(/\/(QQ-|RFP-)/, { timeout: 180_000 });
}

export function instanceIdFromUrl(url: string): string {
  const m = url.match(/\/(QQ-\d+|RFP-\d+)(?:\?|$|\/)/) ?? url.match(/\/(QQ-\d+|RFP-\d+)/);
  if (!m) {
    throw new Error(`no instance id in url: ${url}`);
  }
  return m[1];
}

export const demoEnabled = (): boolean => process.env.E2E_DEMO === "1";
