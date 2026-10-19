import { expect, test, type Page } from "@playwright/test";
import { runEvents, type RunEvent } from "./gate-db";
import { people, signInAs, signOut } from "./helpers";

// M1 exit gate on the real model: "Faisal starts a Quick Quote and chats on the real model; replies stream;
// brief v1 and v2 are saved as drafts." Runs only with E2E_GATE=1 (`make gate`), after stops 1–3 publish the
// pack and activate the Seat. The model's wording varies, so this checks what happened and what the brief holds,
// not what was said. Every check lands on a scorecard (annotation "gate-scorecard") that `make gate RUNS=n`
// tallies across runs; content and conduct checks are soft, so one run reports all of them.

const MODEL_TURN_MS = 180_000;
/** Model calls one reply may use before we call it a loop (the Seat allows 8). */
const MAX_MODEL_STEPS_PER_REPLY = 6;
/** Drafts one reply may save (normally one; two if it saves, learns something, and saves again). */
const MAX_SAVES_PER_REPLY = 2;

const NEED = "We need 40 cleaning trolleys for Mall A, same spec as Mall C";
const ANSWER =
  "Delivery by 15 November 2026 to the Mall A loading bay. Same specification as the Mall C order: " +
  "heavy-duty custodial trolleys with a mop bucket and bin. Budget guidance is internal, about SAR 20,000. " +
  "The Mall A facilities manager signs off on quality. That's everything; please update the brief.";
const BUDGET = 20_000;

const escapeRegExp = (v: string) => v.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
/** Faisal's own message: a paragraph whose whole text is the need (a reply may quote it). */
const NEED_EXACT = new RegExp(`^${escapeRegExp(NEED)}$`);
/** A reply that pastes JSON instead of talking (e.g. `{"content":{"title":...` or `brief: [{"title":...`). */
const LOOKS_LIKE_JSON = /[{[]\s*"[^"]+"\s*:/;

type Check = { check: string; ok: boolean; detail: string };

function scorecard() {
  const card: Check[] = [];
  const note = { type: "gate-scorecard", description: "[]" };
  test.info().annotations.push(note);
  return {
    card,
    /** Record a check; a failure fails the run at the end, after the other checks have been recorded. */
    check(check: string, ok: boolean, detail = "") {
      card.push({ check, ok, detail });
      note.description = JSON.stringify(card);
      expect.soft(ok, `${check}${detail ? ` (${detail})` : ""}`).toBe(true);
    },
  };
}

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

/** GET from the kernel as the signed-in person (the token the app keeps in localStorage). */
async function apiGet<T>(page: Page, path: string): Promise<T> {
  const token = await page.evaluate(() => localStorage.getItem("aos.token"));
  const res = await page.request.get(`/api${path}`, { headers: { Authorization: `Bearer ${token}` } });
  expect(res.ok(), `GET ${path}: ${res.status()}`).toBe(true);
  return (await res.json()) as T;
}

type Brief = Record<string, unknown>;

function amount(value: unknown): number | null {
  if (typeof value === "number") return value;
  if (value && typeof value === "object" && typeof (value as { amount?: unknown }).amount === "number") {
    return (value as { amount: number }).amount;
  }
  return null;
}

const text = (value: unknown) => (value == null ? "" : typeof value === "string" ? value : JSON.stringify(value));
const empty = (value: unknown) => value == null || (typeof value === "string" && value.trim() === "");

/** The brief: what Faisal said lands in the right fields, nothing is invented, the budget stays internal. */
function checkBrief(check: (name: string, ok: boolean, detail?: string) => void, first: Brief, last: Brief) {
  check(
    "first draft doesn't invent a delivery date",
    empty(first.delivery_date),
    `delivery_date=${text(first.delivery_date)}`,
  );
  check(
    "first draft doesn't invent who signs off",
    empty(first.quality_signoff),
    `quality_signoff=${text(first.quality_signoff)}`,
  );
  check("quantity is 40", Number(last.quantity) === 40, `quantity=${text(last.quantity)}`);
  check(
    "category is the ERP's janitorial category",
    /CAT-JAN-EQ|janitorial/i.test(text(last.category)),
    `category=${text(last.category)}`,
  );
  check("delivery date is 15 Nov 2026", text(last.delivery_date) === "2026-11-15", `delivery_date=${text(last.delivery_date)}`);
  check("delivery site is Mall A", /mall a/i.test(text(last.delivery_site)), `delivery_site=${text(last.delivery_site)}`);
  check(
    "quality sign-off is the facilities manager",
    /facilities manager/i.test(text(last.quality_signoff)),
    `quality_signoff=${text(last.quality_signoff)}`,
  );
  check(
    "budget is stored as budget_guidance",
    amount(last.budget_guidance) === BUDGET,
    `budget_guidance=${text(last.budget_guidance)}`,
  );
  const leaks = Object.entries(last)
    .filter(([key]) => key !== "budget_guidance")
    .filter(([, value]) => /20[,. ]?000|20k\b/i.test(text(value)))
    .map(([key]) => key);
  check("budget appears in no other field", leaks.length === 0, leaks.length ? `found in ${leaks.join(", ")}` : "");
}

/** The agent's conduct, from the job's execution events: no loops, no failures, no refusals. */
function checkConduct(check: (name: string, ok: boolean, detail?: string) => void, events: RunEvent[]) {
  const bad = events.filter((e) => ["TaskFailed", "BudgetExceeded", "ToolDenied", "AttemptFenced"].includes(e.type));
  check("no failed attempts, budget stops or denied tools", bad.length === 0, bad.map((e) => e.type).join(", "));

  const attempts = [...new Set(events.filter((e) => e.attemptId).map((e) => e.attemptId))];
  check("one attempt per message (no retries)", attempts.length === 2, `${attempts.length} attempts`);

  attempts.forEach((attemptId, i) => {
    const mine = events.filter((e) => e.attemptId === attemptId);
    const steps = mine.filter((e) => e.type === "ModelInvoked").length;
    check(`reply ${i + 1}: at most ${MAX_MODEL_STEPS_PER_REPLY} model steps`, steps <= MAX_MODEL_STEPS_PER_REPLY, `${steps} steps`);

    const requests = mine.filter((e) => e.type === "ToolRequested");
    const keys = requests.map((e) => `${e.tool}:${e.argsSha}`);
    const repeats = [...new Set(keys.filter((k, j) => keys.indexOf(k) !== j))].map((k) => k.split(":")[0]);
    check(`reply ${i + 1}: no repeated identical tool call`, repeats.length === 0, repeats.join(", "));

    const saves = requests.filter((e) => e.tool === "save_draft").length;
    check(`reply ${i + 1}: at most ${MAX_SAVES_PER_REPLY} brief saves`, saves <= MAX_SAVES_PER_REPLY, `${saves} saves`);
  });
}

test("M1 gate: Faisal chats on the real model; replies stream; brief v1 and v2 are saved", async ({ page }) => {
  const info = test.info();
  const { card, check } = scorecard();

  await signInAs(page, people.faisal);
  // SPA navigation from here on, so the observer stays installed until the reload.
  await watchStreamedTurns(page);

  await page.getByRole("link", { name: "New job" }).click();
  await page.locator('label input[type="radio"]').first().check();
  await page.getByLabel("Describe the need").fill(NEED);
  await page.getByRole("button", { name: "Start" }).click();
  await expect(page).toHaveURL(/\/workspace\/jobs\/.+/, { timeout: 60_000 });
  const instanceId = decodeURIComponent(new URL(page.url()).pathname.split("/").pop() ?? "");

  const conversation = page.getByRole("region", { name: "Conversation" });
  const replies = conversation.getByRole("article", { name: /^Reply from / });
  const workPanel = page.getByRole("complementary", { name: "Work in progress" });
  const docTab = workPanel.getByRole("tab", { selected: true });

  // Turn 1: the agent replies (usually with questions) and saves the first brief.
  await expect(replies.first()).toBeVisible({ timeout: MODEL_TURN_MS });
  check("replies are signed with the Seat's name", !/seat_/.test((await replies.first().getAttribute("aria-label")) ?? ""));
  await expect(docTab).toContainText(/\bv\d+\b/, { timeout: MODEL_TURN_MS });
  const firstVersion = await briefVersion(page);
  check("a brief draft is saved on the first turn", firstVersion >= 1, `v${firstVersion}`);
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
  check("the answer saves a newer brief version", finalVersion > firstVersion, `v${firstVersion} → v${finalVersion}`);
  await expect(workPanel.getByRole("combobox", { name: "Version" }).locator("option")).toHaveCount(finalVersion);
  await page.screenshot({ path: info.outputPath("2-second-reply.png"), fullPage: true });

  const streamed = await streamedTurns(page);
  check("reply text streams", streamed.length >= 1, `${streamed.length} of 2 replies streamed`);
  const replyTexts = await replies.allInnerTexts();
  check("no reply says it failed", !replyTexts.some((t) => /couldn't finish this reply/i.test(t)));
  const jsonReplies = replyTexts.filter((t) => LOOKS_LIKE_JSON.test(t));
  check(
    "replies are plain language, not JSON",
    jsonReplies.length === 0,
    jsonReplies.map((t) => t.replace(/\s+/g, " ").slice(0, 80)).join(" | "),
  );

  // Reload: the same conversation and brief come back from the snapshot.
  const url = page.url();
  const replyCount = await replies.count();
  await page.reload();
  await expect(page).toHaveURL(url);
  await expect(conversation.getByRole("paragraph").filter({ hasText: NEED_EXACT })).toBeVisible();
  await expect(conversation.getByText(ANSWER, { exact: true })).toBeVisible();
  await expect(replies).toHaveCount(replyCount);
  await expect(docTab).toContainText(`v${finalVersion}`);
  check("a reload rebuilds the conversation and brief", true);

  // What the brief holds, read as Faisal (the requester sees every field).
  const snapshot = await apiGet<{ artifacts: { artifact_id: string; artifact_type: string }[] }>(
    page,
    `/instances/${encodeURIComponent(instanceId)}`,
  );
  const brief = snapshot.artifacts.find((a) => a.artifact_type === "brief");
  check("the job has a brief", !!brief);
  if (brief) {
    const version = (v: number) =>
      apiGet<{ content: Brief }>(page, `/artifacts/${brief.artifact_id}/versions/${v}`).then((r) => r.content);
    checkBrief(check, await version(firstVersion), await version(finalVersion));
  }

  // How the agent got there, from the execution events.
  checkConduct(check, runEvents(instanceId));

  // The Seat's spend today includes the model calls (priced from AOS_MODEL_PRICE_*).
  await signOut(page);
  await signInAs(page, people.headOfProcurement);
  const seatsResponse = page.waitForResponse(
    (r) => r.request().method() === "GET" && new URL(r.url()).pathname.endsWith("/console/seats"),
  );
  await page.getByRole("link", { name: "Seats", exact: true }).click();
  const seats = (await (await seatsResponse).json()) as { items: { spend_today_usd?: number }[] };
  const spend = Math.max(0, ...seats.items.map((s) => s.spend_today_usd ?? 0));
  check("today's spend is above zero", spend > 0, `USD ${spend.toFixed(4)}`);
  await page.screenshot({ path: info.outputPath("3-seats-spend.png"), fullPage: true });

  const failed = card.filter((c) => !c.ok);
  const lines = card.map((c) => `  ${c.ok ? "✓" : "✗"} ${c.check}${c.detail ? `  (${c.detail})` : ""}`);
  console.log(
    `M1 gate ${failed.length ? "failed" : "passed"}: ${card.length - failed.length}/${card.length} checks; ` +
      `brief v${firstVersion} → v${finalVersion}; ${replyCount} replies, ${streamed.length} streamed; ` +
      `spend USD ${spend.toFixed(4)}. Screenshots: ${info.outputDir}\n${lines.join("\n")}`,
  );
});
