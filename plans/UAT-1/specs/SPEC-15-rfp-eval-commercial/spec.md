# SPEC-15: RFP evaluation: commercial, module and weighted scores

Milestone: UAT-1 | Status: see `plans/STATUS.md` | Priority: Must | Layer: agent
Owner: Swaroop | Planned: 6 · Tue 24 Nov – 7 · Wed 25 Nov | Estimate: 1 ed (engineer-days)
Requirements: R-RFP-13, R-RFP-14 (defined in `plans/UAT-1/milestone.md`)
Branch: `feat/SPEC-15-rfp-eval-commercial` | Depends on: SPEC-04, SPEC-14

## Goal

From the real proposals, the commercial sheet, module comparison, module scores and the 70/30 weighted ranking are computed by tools.

## Scope

In:
- `rfp_evaluation` writes `rfp_module_matrix`, `rfp_module_scores`, `commercial_criterion_scores`, `rfp_eval_commercial`, `rfp_evaluation` (weighted) and `eval_scoring_policy` using `module_scoring` and `price_calculator`; `score_recompute` verifies.
- Prices are visible only to buyer and procurement roles; evaluators and requester never see them (existing classification).
- Vendors under 70 technical never have their price opened (guard in the skill and checked by the verifier).
- `Confirm commercial module review` decision moves to BAFO (existing).

Out:
- Sealed price store (deferred).

## Design

Module names come from the proposal artifacts, not the demo list.

## Acceptance criteria

- AC1: Given three proposals, every commercial and weighted number matches the tools.
- AC2: Given a vendor at 65 technical, its commercial score is absent and its price unread.

## Tests

- T-15-1 unit: Builders from proposal fixtures.
- T-15-2 integration: Simulate through evaluation.
- T-15-3 e2e: J2 commercial and weighted sheets.

Every spec also keeps `make check` green and adds its demo step to the journey spec it belongs to
(`web/e2e/journeys/quick-quote.spec.ts` or `rfp.spec.ts`) when it is user-visible.

## Observability

Summary: 'Commercial review ready; 1 vendor more than 8% above the module benchmark'.

## Files likely touched

- `packs/procurement_demo/skills/rfp_evaluation/`
- `backend/src/aos/worker/scripts/`
- `web/src/workspace/job/views/EvalSheetView.tsx`

## Dependencies

SPEC-04, SPEC-14
