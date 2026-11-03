# Procurement demo — E2E steps (Quick Quote + full RFP)

Two presenter journeys for the `procurement_demo` pack. These steps match the optional Playwright specs in this folder (`01-iphone-quick-quote-to-award.spec.ts`, `02-it-rfp-lifecycle.spec.ts`).

## Before you start

| Requirement | Notes |
|-------------|--------|
| Stack | `make up` from repo root (API, web on **http://localhost:8080**, Postgres, mock ERP/mail, **worker**). |
| Pack | `make sync-pack-docker` after pack changes. |
| Worker | Real model: `OPENAI_API_KEY` in `.env`, worker healthy (`docker logs aos-poc-worker-1`). Scripted path: `AOS_FAKE_SCRIPT=request_intake.happy.yaml` (intake only; not full journey). |
| Demo API | Set **`AOS_DEMO=1`** on the API service to inject vendor replies via `POST /api/demo/vendor-replies`. |
| Demo timers | Quote/proposal deadlines use **`demo_after: 90s`** in the pack; advance with **Platform admin** → Demo controls, or `POST /api/demo/clock/advance` `{ "to_next_timer": true }`. |

**Run automated demos (optional):**

```bash
cd web
E2E_DEMO=1 npm run e2e:demo
```

Without `E2E_DEMO=1`, specs stay **skipped**; use this README for manual demos.

---

## Journey 1 — iPhone purchase → vendor award (Quick Quote `QQ-…`)

**Workflow:** `quick_quote`  
**Story:** Facilities request iPhones; sourcing runs RFQ, collects quotes, compares, and awards one vendor.

### Personas

| Step | Person | Org role |
|------|--------|----------|
| Start job, confirm brief | **Faisal** | Requester (`end_user`) |
| Shortlist, RFQ, quotes, compare, award | **Noura** | Buyer (`sourcing_user`) |
| Advance demo clock (optional) | **Platform admin** | Console |
| Approve master RFP; co-approve RFP send & PO | **Samir Al-Farsi** | **`cdo`** — `procurement_approver` on **`RFP-`** jobs (`team_owner(procurement/procurement)`) |

Sign-in shows **Samir Al-Farsi** under Workspace with roles **cdo, executive approver** (same area as Noura and Faisal). **Khalid** remains for procurement ops but is not the executive approver on new jobs.

### Steps

1. **Sign in as Faisal** → workspace home.
2. Start the purchase either way:
   - **Coordinator (story):** **New job** → message the coordinator with the need below; when they hand off, you land on the sourcing specialist and a **`QQ-`** job.
   - **Direct (faster):** **People** → **Sourcing specialist** → **Send** the need (same as `POST /workspace/intake` while signed in as Faisal).
   Example need:  
   *“We need 5 iPhone 15 units, 128 GB black, without charger, for facilities staff. Deliver to Riyadh north warehouse. Suppliers have 2 days to quote. Facilities manager signs off on quality.”*
3. **Chat with the sourcing specialist** until the **brief** appears in the right panel (title, category, quantity, delivery, reply deadline).
4. If you see **Retry: Intake**, click **Retry this step** and wait for the worker; answer any follow-up in chat (delivery date at least **3 days** from today, category from ERP browse).
5. When **Confirm the brief** appears in the conversation, click it (Faisal is the requester). If the card is hidden, send a short chat line so **your** message is last, or wait until intake fully completes (`intake_ready_for_confirm`).
6. **Sign out → sign in as Noura** → open the job from **My jobs** or **Team queue**.
7. **Shortlisting:** In the side panel, review the supplier list. When **Confirm the shortlist** appears, select **at least 3** vendors and confirm.
8. **RFQ drafting:** Wait for the worker to draft RFQ emails (side panel **RFQ** view). Review for leaks; task completes when verifier passes.
9. **RFQ sending:** Worker sends mail to shortlisted suppliers. State moves to **Awaiting quotes**.
10. **Supplier quotes** (choose one):
    - **Demo API:** For each thread, `POST /api/demo/vendor-replies` with `conversation_id`, `supplier_id`, and a body like:
      ```
      Reference: QQ-XXXX:SUP-11632

      Unit price (SAR): 4200
      Total (SAR): 21000
      Lead time: 5 business days
      ```
    - **Live inbox:** Reply to the RFQ email with the same **`[SUP-…]`** reference and labeled SAR lines.
11. Wait until **quote** artifacts appear (or `quote_count` catches up). If the deadline has not passed, **Platform admin** → advance demo clock **to next timer**, or wait **~90s** for the demo deadline.
12. **Comparison:** Worker builds the comparison table. Open the comparison view in the panel.
13. **Award:** When **Award this order** / **Award to this vendor** appears, pick **one** row and confirm.
14. **Ordering:** Worker creates the PO payload; job moves to **Closed** when complete.

### Success checks

- Job id prefix **`QQ-`**
- Stages visited: intake → shortlisting → RFQ → awaiting quotes → comparison → ordering → closed
- One supplier awarded; PO payload visible before close

---

## Journey 2 — IT service RFP (master RFP → evaluation → award)

**Workflow:** `sourcing_rfp`  
**Story:** Buyer runs a formal RFP for a customer web portal and REST API (services / custom dev).

### Personas

| Step | Person |
|------|--------|
| Entire buyer path | **Noura** (`sourcing_user`) |
| Demo clock | **Platform admin** (optional) |

### Steps

1. **Sign in as Noura** → **People** → **Sourcing specialist** (or **New job** through the coordinator).
2. Use clear **RFP / web service** wording so routing picks `sourcing_rfp`, for example:  
   *“Run an RFP for a bilingual customer web portal and REST API for mall tenants and operations in Saudi Arabia. Need proposals from integrators; reply deadline 5 days (demo: treat as minutes). I sign off on quality.”*
3. Confirm the job id prefix is **`RFP-`** (not `QQ-`). If you get `QQ-`, rephrase with “RFP”, “proposal”, “web service”, “API”, “portal”.
4. **Intake:** Complete **rfp_intake** (chat + brief in panel). **Confirm the brief** as **buyer** when the card appears.
5. **Shortlisting:** Confirm **at least 3** suppliers (IT/dev vendors from discovery, e.g. category **CAT-IT-DEV** when available).
6. **Master RFP drafting:** Side panel shows the generated **`master_rfp`** document (scope, requirements, evaluation criteria — not the brief).
7. **CDO review (before any vendor mail):** Sign out → sign in as **Samir Al-Farsi** → **Team queue** (or **My jobs**) → open the **RFP-** job. Edit the **Master RFP** in the work panel if needed, then **Review and approve master RFP** in the thread. Vendor invitation drafts only start after this step.
8. **RFP invitations:** Sign in as **Noura** again. Worker drafts **`rfp_invitation`** emails (with the master RFP). **Approve and send** as Noura — no second executive send approval; the CDO already signed the RFP document.
9. **Awaiting proposals:** Inject **proposals** like quotes:
    - Demo API vendor reply on each `conversation_id` / `supplier_id`, with RFP reference `RFP-XXXX:SUP-…` and pricing/scoping text the **proposal_triage** skill can parse.
    - Or real mail replies on the invitation threads.
10. Advance demo clock or wait for **proposal_count ≥ invited_count** (or timer **quotes_closed**).
11. **Evaluation:** Worker fills **rfp_evaluation** in the panel (scores / recommendation).
12. **Award this RFP:** Select the winning vendor and confirm.
13. **Ordering:** **rfp_po_create** completes → **Closed**.

### Quick Quote (`QQ-`) vs full RFP (`RFP-`)

| | **QQ-0101-style Quick Quote** | **RFP- sourcing_rfp** |
|--|-------------------------------|------------------------|
| After shortlist | **RFQ email** drafts (commodity quotes) | **Master RFP** doc, then **RFP invitation** docs |
| “Generated RFP” | RFQ message per supplier | `master_rfp` + `rfp_invitation` artifact types |
| Executive approve | Not in workflow | **Samir (CDO)** reviews/edits master RFP before invitations |

Your current job **QQ-0101** is Quick Quote. Confirm the shortlist to continue toward **RFQ** mail — not master RFP. For the IT portal demo with master RFP, start a **new** job with RFP wording and confirm the id is **`RFP-…`**.

### Success checks

- Job id prefix **`RFP-`**
- Artifacts: brief → supplier_list → **master_rfp** → **rfp_invitation** → **proposal**(s) → **rfp_evaluation** → PO payload
- Decisions: brief confirmed → shortlist → **master RFP approved** → supplier selected

---

## Playwright mapping

| Manual step | Automation helper / spec |
|-------------|-------------------------|
| Sign in | `signInAs(page, demoPeople.faisal \| noura)` |
| Start QQ (Faisal) | `startViaCoordinatorNewJob(page, need)` |
| Start RFP (Noura) | `startViaSourcingSpecialist(page, need)` |
| Chat | `sendChat(page, text)` |
| Decision cards | `waitForDecision` + `confirmDecision(page, /Confirm the brief/)` |
| Vendor replies | `simulateVendorReply(token, conversationId, supplierId, vendorQuoteBody(...))` |
| Timer | `advanceDemoClockToNextTimer(platformAdminToken)` |
| Job id | `instanceIdFromUrl(page.url())` |

Specs are **best-effort** with a live worker and real model: timeouts are long (10 min). For a reliable CI path, use the existing **stop-01–05** chain with `AOS_FAKE_SCRIPT` (intake only).

## npm scripts

```bash
npm run e2e          # default config (sign-in, M1 stops)
npm run e2e:demo     # this folder only (requires E2E_DEMO=1 to run)
```
