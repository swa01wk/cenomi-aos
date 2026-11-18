# SPEC-24: Award and regret letters

Milestone: UAT-1 | Status: see `plans/STATUS.md` | Priority: Should | Layer: agent
Owner: Saad | Planned: after day 8, if time | Estimate: 0.5 ed (engineer-days)
Requirements: R-RFP-17 (defined in `plans/UAT-1/milestone.md`)
Branch: `feat/SPEC-24-award-letters` | Depends on: SPEC-18

## Goal

After the recommendation, the agent drafts the award letter and regret letters, never quoting another vendor's price.

## Scope

In:
- New artifact types `award_letter`, `regret_letter`; draft in `rfp_pr_create` or a new task; send via SPEC-08.

Out:
- None

## Design

Not in the client demo; lifecycle doc only.

## Acceptance criteria

- AC1: One award and N-1 regret drafts, `leak_check` pass.

## Tests

- T-24-1 integration: Simulate.

Every spec also keeps `make check` green and adds its demo step to the journey spec it belongs to
(`web/e2e/journeys/quick-quote.spec.ts` or `rfp.spec.ts`) when it is user-visible.

## Observability

—

## Files likely touched

- `packs/procurement_demo/`

## Dependencies

SPEC-18
