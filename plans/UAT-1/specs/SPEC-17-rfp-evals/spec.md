# SPEC-17: Eval scenarios for the RFP skills

Milestone: UAT-1 | Status: see `plans/STATUS.md` | Priority: Must | Layer: agent
Owner: Swaroop | Planned: 7 · Wed 25 Nov | Estimate: 1 ed (engineer-days)
Requirements: NFR-01, R-RFP-03, R-RFP-05, R-RFP-08, R-RFP-09, R-RFP-13, R-RFP-15 (defined in `plans/UAT-1/milestone.md`)
Branch: `feat/SPEC-17-rfp-evals` | Depends on: SPEC-11

## Goal

Every RFP skill has scenarios with rule graders that pass scripted and meet thresholds live.

## Scope

In:
- Suites for `rfp_intake`, `master_rfp_authoring`, `rfp_authoring`, `proposal_triage`, `rfp_evaluation`, `bafo_negotiation` with the scenarios in `milestone.md`.
- Injection and leak cases in each suite where text comes from outside.
- Live run and prompt fixes.

Out:
- None

## Design

As SPEC-13.

## Acceptance criteria

- AC1: Scripted: all RFP scenarios pass.
- AC2: Live N=5: thresholds met or failures triaged into Sev levels.

## Tests

- T-17-1 integration: `make eval` in CI.
- T-17-2 live: `live.yml` report.

Every spec also keeps `make check` green and adds its demo step to the journey spec it belongs to
(`web/e2e/journeys/quick-quote.spec.ts` or `rfp.spec.ts`) when it is user-visible.

## Observability

Report per skill.

## Files likely touched

- `packs/procurement_demo/evals/`
- `backend/src/aos/worker/scripts/`

## Dependencies

SPEC-11
