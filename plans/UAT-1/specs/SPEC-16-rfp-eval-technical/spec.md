# SPEC-16: RFP evaluation: technical scores with evidence; agent progress summaries

Milestone: UAT-1 | Status: see `plans/STATUS.md` | Priority: Must | Layer: agent
Owner: Saad | Planned: 6 · Tue 24 Nov – 7 · Wed 25 Nov | Estimate: 1 ed (engineer-days)
Requirements: R-RFP-11, R-RFP-13 (defined in `plans/UAT-1/milestone.md`)
Branch: `feat/SPEC-16-rfp-eval-technical` | Depends on: SPEC-04, SPEC-14

## Goal

The agent suggests a 0–5 score per criterion with a quote from the proposal, and its own task summaries replace the kernel-posted progress lines.

## Scope

In:
- `rfp_evaluation` technical part: rubric rows from `rubric_template` (≥ 15 rows for IT services), `technical_criterion_scores` and `rfp_eval_technical` with a quoted evidence string per score that must appear in the proposal text (rule grader).
- Show scoring rubric works on the live artifact.
- M2-AG-04 result summaries: every task's `summary` is one or two plain sentences for people; `demo_rfp_progress.py` only with `AOS_DEMO=1`.

Out:
- Multi-evaluator moderation (deferred).

## Design

Evidence quotes are checked by substring match against the proposal artifact.

## Acceptance criteria

- AC1: Given three proposals, every technical score has evidence found in that vendor's proposal.
- AC2: Given the rubric, at least 15 rows for the IT category.
- AC3: Given supplier replies arriving, the thread shows agent summaries, not kernel text.

## Tests

- T-16-1 unit: Evidence grader.
- T-16-2 integration: Simulate technical scoring.
- T-16-3 e2e: J2 technical sheet and rubric.

Every spec also keeps `make check` green and adds its demo step to the journey spec it belongs to
(`web/e2e/journeys/quick-quote.spec.ts` or `rfp.spec.ts`) when it is user-visible.

## Observability

Summary per vendor scored.

## Files likely touched

- `packs/procurement_demo/skills/rfp_evaluation/`
- `packs/procurement_demo/skills/sourcing_assist/`
- `backend/src/aos/kernel/demo_rfp_progress.py`

## Dependencies

SPEC-04, SPEC-14
