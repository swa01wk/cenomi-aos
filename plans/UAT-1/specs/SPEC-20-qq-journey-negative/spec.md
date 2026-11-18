# SPEC-20: Quick Quote journey and negative cases; retire demo specs

Milestone: UAT-1 | Status: see `plans/STATUS.md` | Priority: Must | Layer: cross-cutting
Owner: Saad | Planned: 8 · Thu 26 Nov | Estimate: 1.5 ed (engineer-days)
Requirements: R-QQ-01, R-QQ-10, NFR-01 (defined in `plans/UAT-1/milestone.md`)
Branch: `feat/SPEC-20-qq-journey-negative` | Depends on: SPEC-05, SPEC-07, SPEC-08

## Goal

The Quick Quote journey (coordinator and direct starts) and the negative cases are green in CI.

## Scope

In:
- `web/e2e/journeys/quick-quote.spec.ts`: coordinator start, direct start, intake, brief, claim, shortlist, RFQ REWORK, send, quotes, price refusal, comparison and sheets, award, PR, closed.
- `web/e2e/journeys/negative.spec.ts`: requester price refusal, evaluator never sees price, non-participant 403, reload and stream drop with no duplicate turns (C10), injected vendor instruction treated as data (C06).
- Remove `--pass-with-no-tests` for `quick-quote` and `negative`.
- Delete `web/e2e/demo/01-…` and `02-…` (stale) and point `e2e/demo/README.md` to the journeys; keep the manual presenter steps.

Out:
- None

## Design

As SPEC-19.

## Acceptance criteria

- AC1: J1 and negative green twice in a row in CI.

## Tests

- T-20-1 e2e: J1.
- T-20-2 e2e: Negative cases.

Every spec also keeps `make check` green and adds its demo step to the journey spec it belongs to
(`web/e2e/journeys/quick-quote.spec.ts` or `rfp.spec.ts`) when it is user-visible.

## Observability

CI job summaries.

## Files likely touched

- `web/e2e/journeys/`
- `web/e2e/demo/`
- `.github/workflows/ci.yml`

## Dependencies

SPEC-05, SPEC-07, SPEC-08
