# SPEC-19: RFP journey, integration suite, UI fixtures and demo parity

Milestone: UAT-1 | Status: see `plans/STATUS.md` | Priority: Must | Layer: cross-cutting
Owner: Swaroop | Planned: 8 · Thu 26 Nov | Estimate: 1.5 ed (engineer-days)
Requirements: R-RFP-01, R-RFP-18, NFR-01 (defined in `plans/UAT-1/milestone.md`)
Branch: `feat/SPEC-19-rfp-journey-parity` | Depends on: SPEC-09, SPEC-10, SPEC-12, SPEC-14, SPEC-15, SPEC-16, SPEC-18

## Goal

The full RFP journey is green in CI on the scripted model and the live job passes the same parity check as the bootstrapped demo.

## Scope

In:
- `web/e2e/journeys/rfp.spec.ts`: one `test.step` per R-RFP step (the specs above append their steps; this spec stabilises and completes it). Writes the job id to `journey-results/rfp-instance.txt`.
- Update `scripts/verify-demo-rfp.sh` needles to what the live agent writes; CI runs it on the journey job (already wired in `ci.yml`).
- Vitest fixtures recorded from a live run for `EvalSheetView`, `SpecStageCallout`, `SupplierQuotesView`, RFP responses table; tests render them.
- Remove `--pass-with-no-tests` for the `rfp` project in `ci.yml`.

Out:
- None

## Design

Journey asserts on cards, tabs and snapshot state, never on model wording.

## Acceptance criteria

- AC1: J2 green twice in a row in CI.
- AC2: Demo parity check passes on the journey's job.
- AC3: Vitest renders every live fixture without errors.

## Tests

- T-19-1 e2e: J2.
- T-19-2 integration: Parity check.
- T-19-3 unit: Vitest fixtures.

Every spec also keeps `make check` green and adds its demo step to the journey spec it belongs to
(`web/e2e/journeys/quick-quote.spec.ts` or `rfp.spec.ts`) when it is user-visible.

## Observability

CI job summary for the journey.

## Files likely touched

- `web/e2e/journeys/`
- `scripts/verify-demo-rfp.sh`
- `web/src/workspace/job/`
- `.github/workflows/ci.yml`

## Dependencies

SPEC-09, SPEC-10, SPEC-12, SPEC-14, SPEC-15, SPEC-16, SPEC-18
