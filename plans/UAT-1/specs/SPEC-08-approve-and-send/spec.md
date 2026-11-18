# SPEC-08: Approve and send for every outbound mail

Milestone: UAT-1 | Status: see `plans/STATUS.md` | Priority: Must | Layer: backend
Owner: Saad | Planned: 3 · Thu 19 Nov | Estimate: 1 ed (engineer-days)
Requirements: R-QQ-06, R-RFP-07, R-RFP-09, R-RFP-15 (defined in `plans/UAT-1/milestone.md`)
Branch: `feat/SPEC-08-approve-and-send` | Depends on: SPEC-01

## Goal

Whatever the agent drafts for vendors (RFQs, invitations, clarification answers, BAFO asks) goes out once, after a person approves, with receipts.

## Scope

In:
- Generalise `connectors/outbound_mail.py` and `POST /instances/{id}/send-rfqs` into a send for any mail artifact type the workflow marks sendable: `rfq_email`, `rfp_invitation`, `clarification_answer` (to all invited vendors), `bafo_email`. Keep the existing route as an alias; add the generic route to `openapi.yaml` and regenerate web types.
- Per-message idempotency key `sha256(instance, artifact_id, version, recipient)`; receipts stored on the artifact version and in an execution event.
- The send task (`rfq_send`, `rfp_send`) completes from the receipts in the same transaction (replaces `heal_rfq_send_after_receipts`).
- Clarification approval (`clarification_*_approved`) and `bafo_send_approved` decisions trigger the send for their bound artifact version.
- Mail stays in mock_mail unless `AOS_RFQ_TEST_ROUTE_ALL` / test inbox settings are set (UAT host).

Out:
- Approval chains and segregation of duties (deferred).

## Design

One code path for all outbound mail; the work panel's Approve and send dock calls it with the artifact versions shown.

## Acceptance criteria

- AC1: Given three approved RFQs, when Approve and send is clicked twice, then three messages are sent once each and `rfq_send` completes.
- AC2: Given an approved commercial clarification answer, when the decision is recorded, then one answer goes to every invited vendor and the thread shows it.
- AC3: Given a draft edited after approval, when sent, then the send refuses with 409 and asks for re-approval of the new version.

## Tests

- T-08-1 functional: Idempotent send per recipient; task completes on receipts.
- T-08-2 functional: Clarification answer fan-out to all bidders.
- T-08-3 functional: Version mismatch -> 409.
- T-08-4 e2e: J1 send step; J2 invitations and clarification steps.

Every spec also keeps `make check` green and adds its demo step to the journey spec it belongs to
(`web/e2e/journeys/quick-quote.spec.ts` or `rfp.spec.ts`) when it is user-visible.

## Observability

Execution events `mail.sent` with artifact, version, recipient, message id.

## Files likely touched

- `backend/src/aos/connectors/outbound_mail.py`
- `backend/src/aos/api/routes.py`
- `docs/specs/contracts/openapi.yaml`
- `web/src/workspace/job/WorkPanelSendRfqs.tsx`
- `packs/procurement_demo/workflows/`

## Dependencies

SPEC-01
