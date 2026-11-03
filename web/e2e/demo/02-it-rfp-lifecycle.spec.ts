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

test.describe("Journey 2: IT service RFP (master RFP → evaluation → award)", () => {
  test.skip(!demoEnabled(), "Set E2E_DEMO=1 to run — see e2e/demo/README.md for manual steps");

  test("RFP: Noura intake through master RFP, proposals, evaluation, award", async ({ page }) => {
    const need =
      "Run an RFP for a bilingual customer web portal and REST API for mall tenants and operations in Saudi Arabia. " +
      "KSA hosting, pilot one mall then rollout. Proposals due in 5 days (demo timing). I am Noura and sign off on quality.";

    await test.step("1–3: Noura starts sourcing_rfp job", async () => {
      await signInAs(page, demoPeople.noura);
      await startFromNewJob(page, need);
      const id = instanceIdFromUrl(page.url());
      expect(id).toMatch(/^RFP-/);
    });

    await test.step("4: RFP intake and confirm brief (buyer)", async () => {
      await sendChat(
        page,
        "Use category for custom software / web development. Delivery go-live 2026-12-15. Vendor reply window 5 days. Scope as discussed — ready to confirm.",
      );
      await waitForDecision(page, "Confirm the brief", 420_000);
      await confirmDecision(page, /^Confirm the brief/);
    });

    await test.step("5: Shortlist ≥3 integrators", async () => {
      await waitForDecision(page, "Confirm the shortlist", 420_000);
      const group = page.getByRole("group", { name: "Confirm the shortlist" });
      const boxes = group.getByRole("checkbox");
      const n = await boxes.count();
      for (let i = 0; i < Math.min(3, n); i++) {
        await boxes.nth(i).check();
      }
      await confirmDecision(page, /^Confirm the shortlist/);
    });

    await test.step("6–7: Master RFP draft; Khalid (procurement approver) approves", async () => {
      await expect(page.getByText(/Master RFP|master_rfp/i).first()).toBeVisible({ timeout: 420_000 });
      const jobUrl = page.url();
      await page.getByRole("button", { name: "Sign out" }).click();
      await signInAs(page, "Samir Al-Farsi");
      await page.goto(jobUrl);
      await waitForDecision(page, "Approve master RFP before invitations", 420_000);
      await confirmDecision(page, /^Approve master RFP before invitations/);
      await page.getByRole("button", { name: "Sign out" }).click();
      await signInAs(page, demoPeople.noura);
      await page.goto(jobUrl);
    });

    await test.step("8–9: RFP invitations and send", async () => {
      await expect(page.getByText(/Awaiting proposals|Send RFP|RFP invitations/i).first()).toBeVisible({
        timeout: 420_000,
      });
    });

    const instanceId = instanceIdFromUrl(page.url());
    const nouraToken = await mintSessionToken("noura");

    await test.step("10: Supplier proposals via demo vendor-replies", async () => {
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
        "No open_rfqs in demo state — inject proposal replies manually (see README)",
      );
      for (const t of threads) {
        const body =
          vendorQuoteBody(instanceId, t.supplier_id, { unit: 850000, total: 850000 }) +
          "\n\nWe include 12-month support and KSA hosting in our proposal.";
        await simulateVendorReply(nouraToken, t.conversation_id, t.supplier_id, body);
      }
    });

    await test.step("11: Advance proposal deadline timer", async () => {
      const adminToken = await mintSessionToken("platform_admin");
      await advanceDemoClockToNextTimer(adminToken);
    });

    await test.step("12–13: Evaluation and award RFP", async () => {
      await expect(page.getByText(/Evaluation|rfp_evaluation/i).first()).toBeVisible({ timeout: 420_000 });
      await waitForDecision(page, /Award this RFP/, 420_000);
      const group = page.getByRole("group", { name: /Award this RFP/i });
      await group.getByRole("checkbox").first().check();
      await confirmDecision(page, /^Award to this vendor/);
    });

    await test.step("14: PO create and close", async () => {
      await expect(page.getByText(/Closed|Ordering/i).first()).toBeVisible({ timeout: 420_000 });
    });
  });
});
