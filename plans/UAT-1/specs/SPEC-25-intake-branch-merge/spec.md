# SPEC-25: Merge the intake-task branch with the coordinator chat

Milestone: UAT-1 | Status: see `plans/STATUS.md` | Priority: Should | Layer: backend
Owner: Swaroop | Planned: after UAT unless decided day 1 | Estimate: 2 ed (engineer-days)
Requirements: R-QQ-02 (defined in `plans/UAT-1/milestone.md`)
Branch: `feat/SPEC-25-intake-branch-merge` | Depends on: SPEC-01

## Goal

Swaroop's `m2/ag-01-intake-task` (intake Task with resume-on-input, `turn_routing.py`) is reconciled with Saad's coordinator chat.

## Scope

In:
- Decide which intake model stays.
- Resolve conflicts in `kernel/decisions.py`, `kernel/instances.py`, `quick_quote.yaml`, tests.
- Re-run the conversation suite.

Out:
- None

## Design

See the unmerged-work note in the milestone plan.

## Acceptance criteria

- AC1: Conversation suite green; no regressions in J1.

## Tests

- T-25-1 functional: Existing intake tests.

Every spec also keeps `make check` green and adds its demo step to the journey spec it belongs to
(`web/e2e/journeys/quick-quote.spec.ts` or `rfp.spec.ts`) when it is user-visible.

## Observability

—

## Files likely touched

- `backend/src/aos/kernel/`

## Dependencies

SPEC-01
