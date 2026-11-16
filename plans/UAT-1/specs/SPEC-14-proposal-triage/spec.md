# SPEC-14: proposal_triage: acks, questions, proposals and clarifications

Milestone: UAT-1 | Status: see `plans/STATUS.md` | Priority: Must | Layer: agent
Owner: Saad | Planned: 5 · Mon 23 Nov – 6 · Tue 24 Nov | Estimate: 1.5 ed (engineer-days)
Requirements: R-RFP-08, R-RFP-09, R-RFP-10, R-RFP-12 (defined in `plans/UAT-1/milestone.md`)
Branch: `feat/SPEC-14-proposal-triage` | Depends on: SPEC-03, SPEC-08, SPEC-12

## Goal

The agent reads every vendor email, files it as an ack, a question or a proposal, routes questions to the right person with a draft answer, and keeps each vendor's history.

## Scope

In:
- `proposal_triage` classifies the message; splits multi-question mail into one question each; tags each `technical` or `commercial` (rules in `demo_proposal_fill.classify_question_lane` become a hint in instructions, not the decision); drafts an answer from the master RFP with a page reference.
- Question -> opens `clarification_send_approved` for the category manager (technical) or `clarification_commercial_approved` for the buyer (commercial); the draft sits in Notes (`ClarificationNotesEditor.tsx`) and edits save a new version.
- Proposal -> `proposal` artifact keyed by supplier with module pricing extracted; versions stack per vendor for the RFP responses table and version dropdown.
- `ack_count`, `proposal_count` updated where artifacts are accepted; `all_proposals_received` fires when all invited vendors have a proposal.
- Fake scripts per message type plus injection.
- `kernel/demo_clarifications.py` and kernel progress lines run only with `AOS_DEMO=1`.

Out:
- Reference-client checks, extension for all bidders (deferred).

## Design

Commercial questions never appear on Rami's queue (participant projection).

## Acceptance criteria

- AC1: Given an email with three questions, when triaged, then three question records exist with lanes and drafts.
- AC2: Given a technical question, then only Rami sees the card; commercial only Noura.
- AC3: Given an approved answer, then it is mailed once to all invited vendors (SPEC-08) and shown in the thread.
- AC4: Given three proposals, then the RFP responses table lists ack, questions and proposal per vendor with versions.

## Tests

- T-14-1 unit: Question splitting and lane hints.
- T-14-2 integration: Simulator timeline -> all artifacts and decisions, scripted model.
- T-14-3 functional: Lane routing by participant.
- T-14-4 e2e: J2 acks, clarifications, proposals, responses table.

Every spec also keeps `make check` green and adds its demo step to the journey spec it belongs to
(`web/e2e/journeys/quick-quote.spec.ts` or `rfp.spec.ts`) when it is user-visible.

## Observability

Summary turns per vendor: 'SUP-x acknowledged', 'SUP-x asked 3 questions (2 technical, 1 commercial)'.

## Files likely touched

- `packs/procurement_demo/skills/proposal_triage/`
- `backend/src/aos/kernel/demo_clarifications.py`
- `backend/src/aos/connectors/demo_proposal_fill.py`
- `web/src/workspace/job/views/ClarificationNotesEditor.tsx`
- `backend/src/aos/worker/scripts/`

## Dependencies

SPEC-03, SPEC-08, SPEC-12
