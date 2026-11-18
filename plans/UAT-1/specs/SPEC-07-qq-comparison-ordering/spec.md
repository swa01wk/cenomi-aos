# SPEC-07: Quick Quote comparison, five eval sheets, PR on receipt

Milestone: UAT-1 | Status: see `plans/STATUS.md` | Priority: Must | Layer: agent
Owner: Swaroop | Planned: 4 · Fri 20 Nov | Estimate: 1.5 ed (engineer-days)
Requirements: R-QQ-09, R-QQ-11, R-QQ-12 (defined in `plans/UAT-1/milestone.md`)
Branch: `feat/SPEC-07-qq-comparison-ordering` | Depends on: SPEC-04, SPEC-05, SPEC-06

## Goal

From the real quotes the agent builds the comparison and the same five evaluation sheets the client saw, and the order closes on an ERP receipt.

## Scope

In:
- `quote_comparison` skill uses `price_calculator` to write `comparison`, `quote_line_matrix`, `quote_line_scores`, `quote_eval_commercial`, `quote_eval_technical`, `quote_evaluation` (and the criterion score artifacts the sheets read) from the quote artifacts; verifier `score_recompute`.
- Fake scripts `quote_comparison.happy.yaml`, `pr_create.happy.yaml` (reworked: no hard-coded supplier; reads the award decision).
- `pr_create` uses `request_action create_pr`; `ordering -> closed` on `task.completed.pr_create` only after the receipt.
- `demo_qq_client_heal.py` runs only with `AOS_DEMO=1`.
- Journey J1 steps for comparison, sheets, award, PR, closed (append to `web/e2e/journeys/quick-quote.spec.ts`).

Out:
- QQ bootstrap content (stays for presenter demos).

## Design

Sheet artifacts keep the exact content shape `EvalSheetView.tsx` and `SupplierQuotesView.tsx` render today; record one live run's artifacts as Vitest fixtures (SPEC-19).

## Acceptance criteria

- AC1: Given three real quotes, when comparison runs, then all five sheets exist and every number matches `price_calculator`.
- AC2: Given Noura awards one row, when ordering runs, then exactly one PR exists in mock ERP and the job closes with the handover.
- AC3: Given `AOS_DEMO=0`, when QQ runs start to end on the scripted model, then no heal or bootstrap code executes (assert via a log counter).

## Tests

- T-07-1 unit: Comparison content builder from quotes.
- T-07-2 integration: `aos simulate --workflow quick_quote` reaches closed with receipts.
- T-07-3 live: Eval scenarios: 3 quotes, tie, missing lead time (SPEC-13).
- T-07-4 e2e: J1 comparison -> closed.

Every spec also keeps `make check` green and adds its demo step to the journey spec it belongs to
(`web/e2e/journeys/quick-quote.spec.ts` or `rfp.spec.ts`) when it is user-visible.

## Observability

Task summaries: 'Compared 3 quotes; lowest total from <supplier>' (buyer audience).

## Files likely touched

- `packs/procurement_demo/skills/quote_comparison/`
- `backend/src/aos/worker/scripts/`
- `backend/src/aos/kernel/demo_qq_client_heal.py`
- `web/e2e/journeys/`

## Dependencies

SPEC-04, SPEC-05, SPEC-06
