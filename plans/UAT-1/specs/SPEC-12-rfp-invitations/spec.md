# SPEC-12: RFP invitations drafted and sent

Milestone: UAT-1 | Status: see `plans/STATUS.md` | Priority: Must | Layer: agent
Owner: Saad | Planned: 5 · Mon 23 Nov | Estimate: 0.5 ed (engineer-days)
Requirements: R-RFP-07 (defined in `plans/UAT-1/milestone.md`)
Branch: `feat/SPEC-12-rfp-invitations` | Depends on: SPEC-08, SPEC-10

## Goal

After Samir approves, the agent drafts one invitation per vendor with the vendor RFP; Noura approves and sends.

## Scope

In:
- `rfp_invitation_draft` writes one `rfp_invitation` per shortlisted vendor with the shareable RFP and acknowledgement deadline; `leak_check`, `recipient_check`.
- `rfp_send` completes on receipts via SPEC-08; quote window timer starts.
- Fake scripts `rfp_invitation_draft.happy.yaml`, `rfp_send.happy.yaml`.
- Drafts tab shows three `Invite · …` items (existing UI).

Out:
- None

## Design

Invitation `key` = supplier id so versions stack per vendor.

## Acceptance criteria

- AC1: Given approval of the master RFP, when drafting completes, then three invitations exist and pass both verifiers.
- AC2: Given Approve and send, then the job moves to Awaiting proposals and the simulator starts.

## Tests

- T-12-1 integration: Simulate through `rfp_send`.
- T-12-2 live: Eval: 3 vendors; vendor with two contacts (SPEC-17).
- T-12-3 e2e: J2 invitations.

Every spec also keeps `make check` green and adds its demo step to the journey spec it belongs to
(`web/e2e/journeys/quick-quote.spec.ts` or `rfp.spec.ts`) when it is user-visible.

## Observability

Summary turn: 'Drafted 3 invitations; waiting for your approval to send'.

## Files likely touched

- `packs/procurement_demo/skills/rfp_authoring/`
- `backend/src/aos/worker/scripts/`

## Dependencies

SPEC-08, SPEC-10
