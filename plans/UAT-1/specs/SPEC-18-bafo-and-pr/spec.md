# SPEC-18: BAFO round live; RFP requisition on receipt

Milestone: UAT-1 | Status: see `plans/STATUS.md` | Priority: Must | Layer: agent
Owner: Saad | Planned: 7 · Wed 25 Nov – 8 · Thu 26 Nov | Estimate: 1.5 ed (engineer-days)
Requirements: R-RFP-15, R-RFP-16, R-RFP-17 (defined in `plans/UAT-1/milestone.md`)
Branch: `feat/SPEC-18-bafo-and-pr` | Depends on: SPEC-06, SPEC-08, SPEC-15

## Goal

The BAFO round the client saw runs live: outliers, drafts, sends, vendor replies, re-score; then the recommendation and the PR.

## Scope

In:
- `bafo_authoring` uses `bafo_outliers` and `module_scoring` on real proposals; drafts one `bafo_email` per outlier asking about the module gap vs the benchmark (no other vendor's price); `leak_check`, `recipient_check`.
- `bafo_send_approved` sends via SPEC-08; simulator replies (SPEC-03); `proposal_triage` files the revised pricing as a new proposal version.
- `bafo_round_complete` re-runs commercial scoring (SPEC-15) and returns to Evaluation.
- `vendor_recommended` (Rami) -> `rfp_pr_create` with `request_action create_pr` -> closed on receipt.
- `kernel/demo_bafo.py` and `demo_rfp_po_heal.py` only with `AOS_DEMO=1`.
- Fake scripts for `bafo_authoring` and the reworked `rfp_pr_create`.

Out:
- Award and regret letters (SPEC-24, Should).

## Design

Cut line: if this is not green on the scripted model by end of day 7, live RFP runs stop at recommendation (see milestone).

## Acceptance criteria

- AC1: Given one outlier, one BAFO draft for that vendor only, with no other vendor's price.
- AC2: Given the vendor's reply, Complete BAFO round updates the module scores and weighted ranking.
- AC3: Given Rami's recommendation, one PR in mock ERP and the job closes.

## Tests

- T-18-1 unit: Outlier selection.
- T-18-2 integration: Simulate BAFO loop and ordering.
- T-18-3 live: BAFO eval (SPEC-17).
- T-18-4 e2e: J2 BAFO to closed.

Every spec also keeps `make check` green and adds its demo step to the journey spec it belongs to
(`web/e2e/journeys/quick-quote.spec.ts` or `rfp.spec.ts`) when it is user-visible.

## Observability

Summary turns per BAFO send and round.

## Files likely touched

- `packs/procurement_demo/skills/bafo_negotiation/`
- `packs/procurement_demo/skills/rfp_evaluation/`
- `backend/src/aos/kernel/demo_bafo.py`
- `backend/src/aos/kernel/demo_rfp_po_heal.py`
- `backend/src/aos/worker/scripts/`

## Dependencies

SPEC-06, SPEC-08, SPEC-15
