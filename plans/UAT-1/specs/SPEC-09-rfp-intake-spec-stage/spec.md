# SPEC-09: rfp_intake writes the brief and the spec stage

Milestone: UAT-1 | Status: see `plans/STATUS.md` | Priority: Must | Layer: agent
Owner: Saad | Planned: 4 · Fri 20 Nov | Estimate: 1 ed (engineer-days)
Requirements: R-RFP-01, R-RFP-02, R-RFP-03 (defined in `plans/UAT-1/milestone.md`)
Branch: `feat/SPEC-09-rfp-intake-spec-stage` | Depends on: SPEC-01, SPEC-04

## Goal

From the start prompt, the agent produces the brief and the four spec-stage documents the client saw, with the send-back to the requester in chat.

## Scope

In:
- `rfp_intake` produces `brief` plus `rfp_procurement_validation`, `rfp_template_compliance`, `scoring_method_agreement` (70/30, min technical 70) and `rfp_upload_manifest`, calling the `spec_checks` tool with the brief.
- Send-back: when validation flags a missing item (e.g. BoQ), the agent posts a turn addressed to the requester named in the brief and opens `ask_question`; Faisal is not a workflow participant, so the turn is visible to the buyer and quoted for forwarding.
- Fake script `rfp_intake.happy.yaml` and `rfp_intake.sendback.yaml`.
- Routing check: the start prompt from `docs/demo/rfp-start-prompt.md` gives an `RFP-` job (`intake_hints`).
- `SpecStageCallout.tsx` and the Documents tab render the live artifacts (no bootstrap-only fields).

Out:
- Making the requester a participant in `sourcing_rfp` (a later change request).

## Design

Spec-stage artifacts are produced in the intake task; `brief_confirmed` auto-confirms for the starter (SPEC-01).

## Acceptance criteria

- AC1: Given the RFP start prompt, when intake completes, then the job id starts `RFP-`, the brief is confirmed for Noura, and the four spec-stage documents exist.
- AC2: Given a brief without a BoQ, when validation runs, then a send-back turn names the requester and the missing item.
- AC3: Given the scoring agreement, then technical weight 0.7, commercial 0.3, minimum technical 70.

## Tests

- T-09-1 unit: `spec_checks` outputs for complete and incomplete briefs.
- T-09-2 integration: `aos simulate --workflow sourcing_rfp` through intake with the fake script.
- T-09-3 live: Eval scenarios: IT portal, facilities cleaning (SPEC-17).
- T-09-4 e2e: J2 start and spec stage.

Every spec also keeps `make check` green and adds its demo step to the journey spec it belongs to
(`web/e2e/journeys/quick-quote.spec.ts` or `rfp.spec.ts`) when it is user-visible.

## Observability

Task summary turn listing the four documents and any send-back item.

## Files likely touched

- `packs/procurement_demo/skills/rfp_intake/`
- `backend/src/aos/worker/scripts/`
- `web/src/workspace/job/views/SpecStageCallout.tsx`

## Dependencies

SPEC-01, SPEC-04
