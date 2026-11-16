# SPEC-21: Live runs and Sev 1/2 fixes

Milestone: UAT-1 | Status: see `plans/STATUS.md` | Priority: Must | Layer: cross-cutting
Owner: Both | Planned: 9 · Fri 27 Nov | Estimate: 2 ed (engineer-days)
Requirements: NFR-01 (defined in `plans/UAT-1/milestone.md`)
Branch: `feat/SPEC-21-live-runs-fixes` | Depends on: SPEC-19, SPEC-20, SPEC-13, SPEC-17

## Goal

Real-model runs meet the handover targets and every Sev 1/2 found is fixed.

## Scope

In:
- Run `live.yml` on demand (eval N=5, journeys 5 runs).
- Triage each failure: prompt/skill fix, test fix (only if the test is wrong), or a bug with severity in STATUS.md.
- Fix Sev 1 and 2 only; log Sev 3/4 for after UAT.

Out:
- New features (code freeze).

## Design

Fix prompts, not tests.

## Acceptance criteria

- AC1: Quick Quote closes in ≥ 4/5 live runs; RFP reaches award in ≥ 3/5.
- AC2: No open Sev 1 or 2 in STATUS.md.

## Tests

- T-21-1 live: `live.yml` run report.

Every spec also keeps `make check` green and adds its demo step to the journey spec it belongs to
(`web/e2e/journeys/quick-quote.spec.ts` or `rfp.spec.ts`) when it is user-visible.

## Observability

Evidence artifacts kept 30 days.

## Files likely touched

- `packs/procurement_demo/skills/`
- `plans/STATUS.md`

## Dependencies

SPEC-19, SPEC-20, SPEC-13, SPEC-17
