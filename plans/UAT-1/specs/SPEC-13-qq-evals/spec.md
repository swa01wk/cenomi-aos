# SPEC-13: Eval scenarios for the Quick Quote skills

Milestone: UAT-1 | Status: see `plans/STATUS.md` | Priority: Must | Layer: agent
Owner: Swaroop | Planned: 5 · Mon 23 Nov – 6 · Tue 24 Nov | Estimate: 1 ed (engineer-days)
Requirements: NFR-01, R-QQ-02, R-QQ-04, R-QQ-05, R-QQ-07, R-QQ-09, R-QQ-10 (defined in `plans/UAT-1/milestone.md`)
Branch: `feat/SPEC-13-qq-evals` | Depends on: SPEC-11

## Goal

Every Quick Quote skill has scenarios with rule graders that pass on the scripted model and meet thresholds live.

## Scope

In:
- Suites for `request_intake`, `supplier_lookup`, `rfq_authoring`, `quote_triage`, `quote_comparison` (incl. `pr_create`), `sourcing_assist`, `workspace_coordinate`, with the scenarios listed in `milestone.md` (Eval suite table).
- Fake scripts for each scenario so `make eval` is deterministic.
- First live run (`make eval LIVE=1 N=5`) and prompt fixes to reach thresholds.

Out:
- None

## Design

Safety checks: no budget in shareable fields, no price to requester, injected instructions not followed.

## Acceptance criteria

- AC1: Given the scripted model, all QQ scenarios pass.
- AC2: Given the live model N=5, all QQ skills meet the ADR thresholds.

## Tests

- T-13-1 integration: `make eval` in CI.
- T-13-2 live: `live.yml` report.

Every spec also keeps `make check` green and adds its demo step to the journey spec it belongs to
(`web/e2e/journeys/quick-quote.spec.ts` or `rfp.spec.ts`) when it is user-visible.

## Observability

Report per skill.

## Files likely touched

- `packs/procurement_demo/evals/`
- `backend/src/aos/worker/scripts/`
- `packs/procurement_demo/skills/`

## Dependencies

SPEC-11
