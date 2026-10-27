# ADR 006 — Approval binding and chains

- **Status:** Proposed (awaiting sign-off at the M0 gate)
- **Owner:** Kernel engineer 2

## Context
An approval must authorise exactly the effect a person saw, and the person approving must not be the
one who asked for it.

## Decision
- Policies return `ALLOW`, `REQUIRE_APPROVAL`, `DENY` or `NEVER`. Every committed effect in a workflow
  must be governed by a policy (`E_UNGOVERNED_EFFECT`); `REQUIRE_APPROVAL` must name a chain
  (`E_NO_APPROVAL_CHAIN`).
- An approval request is **bound** to the hash of the proposed effect payload, the pinned definition
  versions and the requesting attempt. Any change to the payload voids the approval.
- Chains are ordered steps resolved to people from the instance's participant roles at request time.
  In the pack (`policies/quick_quote_gates.yaml`): RFQ send needs `participant:buyer`; PO create needs
  `participant:buyer` (content), then `participant:procurement_approver` on every PO. A step may carry a `when`
  condition; the demo pack's PO chain has none.
- Segregation of duties (`segregation: [not_requester, distinct_approvers]`): the requester cannot
  approve, and no person may approve two steps of the same request.
- Each decision is an audit record (ADR 008) and emits `decision.approved|rejected` with `by`.

## Alternatives considered
Approving a Task rather than an effect (too coarse; payload can change after approval).

## Verification
M3: approving, then editing the PO amount, invalidates the approval; the initiator's approve button is
disabled and the API refuses with 403.
