# SPEC-10: Master and vendor RFP drafted live; CDO edit and send-back

Milestone: UAT-1 | Status: see `plans/STATUS.md` | Priority: Must | Layer: agent
Owner: Saad | Planned: Sat 21 Nov | Estimate: 1 ed (engineer-days)
Requirements: R-RFP-05, R-RFP-06 (defined in `plans/UAT-1/milestone.md`)
Branch: `feat/SPEC-10-master-rfp` | Depends on: SPEC-04, SPEC-09

## Goal

The agent drafts the master RFP (70/30 QCBS) and the shareable vendor copy; Samir edits or sends back, and his approval binds to the version he saw.

## Scope

In:
- `master_rfp_draft` writes `master_rfp` with internal and shareable sections; `leak_check` (SPEC-04 scope) blocks internal values in the vendor copy -> REWORK.
- Use `demo_master_rfp_content.py` text as a few-shot example in `skills/master_rfp_authoring/instructions.md`, not as output.
- Send-back: a 'Send back' option on `master_rfp_confirmed` with a comment re-runs `master_rfp_draft` with the comment in the envelope.
- Samir's edit in `EditableDocumentView` saves a new version; the open approval re-binds to it (decisions void on new version, M2-BE-04).
- Fake scripts `master_rfp_draft.happy.yaml`, `.leak.yaml`, `.sendback.yaml`.

Out:
- Criteria-version lock (deferred).

## Design

The decision card shows the version it approves; approving an older version is 409.

## Acceptance criteria

- AC1: Given a confirmed shortlist, when drafting completes, then `master_rfp` v1 exists with 70/30 evaluation text and passes `leak_check`.
- AC2: Given Samir sends back with 'add SLA section', when the redraft completes, then v2 contains an SLA section and the card shows v2.
- AC3: Given Samir edits v2 to v3 and approves, then the decision records v3 and invitations start.

## Tests

- T-10-1 functional: Approval re-binds to the edited version; stale approve 409.
- T-10-2 integration: REWORK on leak, then pass.
- T-10-3 live: Eval: standard, incumbent/budget notes, send-back comment (SPEC-17).
- T-10-4 e2e: J2 master RFP, send-back, edit, approve.

Every spec also keeps `make check` green and adds its demo step to the journey spec it belongs to
(`web/e2e/journeys/quick-quote.spec.ts` or `rfp.spec.ts`) when it is user-visible.

## Observability

Summary turn names the version and what changed on redraft.

## Files likely touched

- `packs/procurement_demo/skills/master_rfp_authoring/`
- `packs/procurement_demo/workflows/sourcing_rfp.yaml`
- `backend/src/aos/kernel/demo_master_rfp_content.py`
- `backend/src/aos/worker/scripts/`

## Dependencies

SPEC-04, SPEC-09
