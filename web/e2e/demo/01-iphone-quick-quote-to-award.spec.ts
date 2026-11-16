import { expect, test } from "@playwright/test";
import {
  advanceDemoClockToNextTimer,
  confirmDecision,
  demoEnabled,
  demoPeople,
  fetchDemoState,
  instanceIdFromUrl,
  mintSessionToken,
  sendChat,
  signInAs,
  simulateVendorReply,
  startFromNewJob,
  vendorQuoteBody,
  waitForDecision,
} from "./helpers";

test.describe.configure({ mode: "serial" });

test.describe("Journey 1: iPhone Quick Quote through award", () => {
  test.skip(!demoEnabled(), "Set E2E_DEMO=1 to run — see e2e/demo/README.md for manual steps");

  test("QQ: Faisal intake → Noura RFQ → quotes → award", async ({ page }) => {
    const need =
      "We need 5 iPhone 15 phones, 128 GB black, without charger, for facilities. " +
      "Deliver to Riyadh north warehouse by 2026-12-01. Vendors have 2 days to quote. " +
      "Facilities manager signs off on quality.";

    await test.step("1–2: Faisal starts Quick Quote", async () => {
      await signInAs(page, demoPeople.faisal);
      await startFromNewJob(page, need);
      expect(instanceIdFromUrl(page.url())).toMatch(/^QQ-/);
    });

    await test.step("3–5: Intake chat and confirm brief (requester)", async () => {
      await sendChat(
        page,
        "Delivery 2026-12-01 to north warehouse. Budget guidance 25000 SAR internal. Ready to confirm when the brief looks right.",
      );
      await waitForDecision(page, "Confirm the brief");
      await confirmDecision(page, /^Confirm the brief/);
    });

    await test.step("6: Hand off to Noura (buyer)", async () => {
      await page.getByRole("button", { name: "Sign out" }).click();
      await signInAs(page, demoPeople.noura);
      await page.goto(page.url());
      await expect(page.getByRole("region", { name: "Conversation" })).toBeVisible({ timeout: 60_000 });
    });

    await test.step("7: Confirm shortlist (≥3 suppliers)", async () => {
      await waitForDecision(page, "Confirm the shortlist", 420_000);
      const group = page.getByRole("group", { name: "Confirm the shortlist" });
      const boxes = group.getByRole("checkbox");
      const n = await boxes.count();
      for (let i = 0; i < Math.min(3, n); i++) {
        await boxes.nth(i).check();
      }
      await confirmDecision(page, /^Confirm the shortlist/);
    });

    await test.step("8–9: RFQ draft and send (worker)", async () => {
      await expect(page.getByText(/Awaiting quotes|RFQ sending|RFQ drafting/i).first()).toBeVisible({
        timeout: 420_000,
      });
    });

    const instanceId = instanceIdFromUrl(page.url());
    const nouraToken = await mintSessionToken("noura");

    await test.step("10: Inject vendor quotes (demo API)", async () => {
      const adminToken = await mintSessionToken("platform_admin");
      let state = await fetchDemoState(adminToken);
      let threads = state.open_rfqs?.filter((r) => r.instance_id === instanceId && !r.replied) ?? [];
      if (threads.length === 0) {
        await page.waitForTimeout(15_000);
        state = await fetchDemoState(adminToken);
        threads = state.open_rfqs?.filter((r) => r.instance_id === instanceId && !r.replied) ?? [];
      }
      test.skip(
        threads.length === 0,
        "No open_rfqs in demo state — inject replies manually (see README) or enable mock_mail thread listing in demo state",
      );
      for (const t of threads) {
        await simulateVendorReply(
          nouraToken,
          t.conversation_id,
          t.supplier_id,
          vendorQuoteBody(instanceId, t.supplier_id, { unit: 4000 + threads.indexOf(t) * 100, total: 20000 }),
        );
      }
    });

    await test.step("11: Advance quote timer", async () => {
      const adminToken = await mintSessionToken("platform_admin");
      await advanceDemoClockToNextTimer(adminToken);
    });

    await test.step("12–13: Comparison and award", async () => {
      await waitForDecision(page, /Award this order|Award this RFP/, 420_000);
      const awardGroup = page.getByRole("group", { name: /Award this order/i });
      await awardGroup.getByRole("checkbox").first().check();
      await confirmDecision(page, /^Award to this vendor/);
    });

    await test.step("14: PO / closed", async () => {
      await expect(page.getByText(/Closed|Ordering|Purchase order/i).first()).toBeVisible({ timeout: 420_000 });
    });
  });
});
