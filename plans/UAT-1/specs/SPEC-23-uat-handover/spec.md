# SPEC-23: UAT handover pack and demo rehearsal

Milestone: UAT-1 | Status: see `plans/STATUS.md` | Priority: Must | Layer: docs
Owner: Saad | Planned: Sat 28 Nov – 10 · Mon 30 Nov | Estimate: 1 ed (engineer-days)
Requirements: R-QQ-01, R-RFP-01 (defined in `plans/UAT-1/milestone.md`)
Branch: `feat/SPEC-23-uat-handover` | Depends on: SPEC-21

## Goal

The client gets a UAT script, known limitations, release notes and a demo of the live flow.

## Scope

In:
- Finalise `plans/UAT-1/uat-script.md` (one case per R-xx, steps, expected, pass/fail).
- Finalise `plans/UAT-1/known-limitations.md`.
- `docs/ops/RELEASE_NOTES.md` and `CHANGELOG.md` for `v0.3.0-uat`.
- Rehearse the demo on the live flow on the UAT host (Sat 28 Nov); keep `make demo-client-full` only as fallback.
- Re-label the client roadmap to match what ships.
- Agree the bug route and severities with the client.

Out:
- None

## Design

Docs in client language.

## Acceptance criteria

- AC1: Client walkthrough done on 30 Nov; handover signed.

## Tests

- T-23-1 e2e: Rehearsal run recorded.

Every spec also keeps `make check` green and adds its demo step to the journey spec it belongs to
(`web/e2e/journeys/quick-quote.spec.ts` or `rfp.spec.ts`) when it is user-visible.

## Observability

—

## Files likely touched

- `plans/UAT-1/`
- `docs/ops/`
- `CHANGELOG.md`

## Dependencies

SPEC-21
