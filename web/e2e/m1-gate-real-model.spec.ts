import { expect, test, type Page } from "@playwright/test";
import { people, signInAs, signOut } from "./helpers";

// M1 exit gate on the real model: "Faisal starts a Quick Quote and chats on the real model; replies stream;
// brief v1 and v2 are saved as drafts." Runs only with E2E_GATE=1 (`make gate`), after stops 1–3 publish the
// pack and activate the Seat. The model's wording varies, so this checks what happened, not what was said.

const MODEL_TURN_MS = 180_000;

const NEED = "We need 40 cleaning trolleys for Mall A, same spec as Mall C";
const ANSWER =
  "Delivery by 15 November 2026 to the Mall A loading bay. Same specification as the Mall C order: " +
  "heavy-duty custodial trolleys with a mop bucket and bin. Budget guidance is internal, about SAR 20,000. " +
  "The Mall A facilities manager signs off on quality. That's everything; please update the brief.";

/**
 * Record every turn whose reply text arrived over the stream. Streamed text is shown in a `[data-turn-id]` span
 * only while the reply is in flight, so a poll could miss a short reply; an observer sees every change.
 */
async function watchStreamedTurns(page: Page): Promise<void> {
  await page.evaluate(() => {
    const w = window as unknown as { __aosStreamedTurns?: string[] };
    w.__aosStreamedTurns = [];
    const scan = () => {
      document.querySelectorAll<HTMLElement>("[data-turn-id]").forEach((el) => {
        const id = el.dataset.turnId ?? "";
        if (id && (el.textContent ?? "").trim() && !w.__aosStreamedTurns!.includes(id)) {
          w.__aosStreamedTurns!.push(id);
        }
      });
    };
    new MutationObserver(scan).observe(document.body, { subtree: true, childList: true, characterData: true });
  });
}

async function streamedTurns(page: Page): Promise<string[]> {
  return page.evaluate(() => (window as unknown as { __aosStreamedTurns?: string[] }).__aosStreamedTurns ?? []);
}

/** The brief's latest version, from the work panel's tab label ("Brief v2"). */
async function briefVersion(page: Page): Promise<number> {
  const tab = page.getByRole("complementary", { name: "Work in progress" }).getByRole("tab", { selected: true });
  if ((await tab.count()) === 0) return 0;
  const versions = (await tab.innerText()).match(/\bv\d+\b/g) ?? [];
  return versions.length ? Number(versions[versions.length - 1].slice(1)) : 0;
}

test("M1 gate: Faisal chats on the real model; replies stream; brief v1 and v2 are saved", async ({ page }) => {
  const info = test.info();

  await signInAs(page, people.faisal);
  // SPA navigation from here on, so the observer stays installed until the reload.
  await watchStreamedTurns(page);

  await page.getByRole("link", { name: "New job" }).click();
  await page.locator('label input[type="radio"]').first().check();
  await page.getByLabel("Describe the need").fill(NEED);
  await page.getByRole("button", { name: "Start" }).click();
  await expect(page).toHaveURL(/\/workspace\/jobs\/.+/, { timeout: 60_000 });

  const conversation = page.getByRole("region", { name: "Conversation" });
  const replies = conversation.getByRole("article", { name: /^Reply from / });
  const workPanel = page.getByRole("complementary", { name: "Work in progress" });
  const docTab = workPanel.getByRole("tab", { selected: true });

  // Turn 1: the agent replies (usually with questions) and saves the first brief.
  await expect(replies.first()).toBeVisible({ timeout: MODEL_TURN_MS });
  // The reply is signed with the Seat's display name, not its id.
  await expect(replies.first()).not.toHaveAttribute("aria-label", /seat_/);
  await expect(docTab).toContainText(/\bv\d+\b/, { timeout: MODEL_TURN_MS });
  const firstVersion = await briefVersion(page);
  expect(firstVersion, "a brief draft is saved on the first turn").toBeGreaterThanOrEqual(1);
  const repliesAfterFirst = await replies.count();
  await page.screenshot({ path: info.outputPath("1-first-reply.png"), fullPage: true });

  // Turn 2: answer everything; the agent saves a newer version and replies again.
  await conversation.getByLabel("Message").fill(ANSWER);
  await conversation.getByRole("button", { name: "Send" }).click();
  await expect(conversation.getByText(ANSWER, { exact: true })).toBeVisible();
  await expect(replies).toHaveCount(repliesAfterFirst + 1, { timeout: MODEL_TURN_MS });
  await expect
    .poll(() => briefVersion(page), { message: "the answer saves a newer brief version", timeout: MODEL_TURN_MS })
    .toBeGreaterThan(firstVersion);
  const finalVersion = await briefVersion(page);
  await expect(workPanel.getByRole("combobox", { name: "Version" }).locator("option")).toHaveCount(finalVersion);
  await page.screenshot({ path: info.outputPath("2-second-reply.png"), fullPage: true });

  const streamed = await streamedTurns(page);
  expect(
    streamed.length,
    "at least one reply's text arrived over the stream (both turns ended in tool calls if not; see make diag)",
  ).toBeGreaterThanOrEqual(1);

  // Reload: the same conversation and brief come back from the snapshot.
  const url = page.url();
  const replyCount = await replies.count();
  await page.reload();
  await expect(page).toHaveURL(url);
  await expect(conversation.getByRole("paragraph").filter({ hasText: NEED })).toBeVisible();
  await expect(conversation.getByText(ANSWER, { exact: true })).toBeVisible();
  await expect(replies).toHaveCount(replyCount);
  await expect(docTab).toContainText(`v${finalVersion}`);

  // The Seat's spend today includes the model calls (priced from AOS_MODEL_PRICE_*).
  await signOut(page);
  await signInAs(page, people.headOfProcurement);
  const seatsResponse = page.waitForResponse(
    (r) => r.request().method() === "GET" && new URL(r.url()).pathname.endsWith("/console/seats"),
  );
  await page.getByRole("link", { name: "Seats", exact: true }).click();
  const seats = (await (await seatsResponse).json()) as { items: { spend_today_usd?: number }[] };
  const spend = Math.max(0, ...seats.items.map((s) => s.spend_today_usd ?? 0));
  expect(spend, "today's spend is above zero").toBeGreaterThan(0);
  await page.screenshot({ path: info.outputPath("3-seats-spend.png"), fullPage: true });

  const summary =
    `brief v${firstVersion} → v${finalVersion}; ${replyCount} agent replies, ${streamed.length} streamed; ` +
    `spend today USD ${spend.toFixed(4)}. Screenshots: ${info.outputDir}`;
  info.annotations.push({ type: "M1 gate", description: summary });
  console.log(`M1 gate passed: ${summary}`);
});
