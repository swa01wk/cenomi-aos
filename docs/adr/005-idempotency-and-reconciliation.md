# ADR 005 — Action idempotency and reconciliation per connector

- **Status:** Proposed (awaiting sign-off at the M0 gate)
- **Owner:** Kernel engineer 2

## Context
Creating a PO or sending an RFQ email is a committed effect. A timeout after the remote side commits
leaves the outcome unknown; retrying blindly creates duplicates.

## Decision
- The kernel assigns each approved effect an **action id** and an **idempotency key**
  (`<instance>:<template>:<effect>:<n>`). The gateway passes both to the connector.
- Every committed-effect tool declares `reconcile_with` in its connector YAML (validated, `E_RECONCILE`):
  `create_po` → `find_po(reference)`, `send_message` → `find_message`.
- On timeout or connection loss the action goes to `unknown`. The reconciler calls the lookup tool:
  found → `committed` with the remote id; not found after the window → safe to retry with the same key;
  still ambiguous → exception to a human.
- Mock connectors honour the key (repeat calls return the original result) and expose fault switches
  (`timeout_after_commit`, `fail_validation`) to exercise these paths.

## Alternatives considered
Two-phase commit with connectors (not available from real ERPs); retry-without-lookup (duplicates).

## Assumptions
Every POC target system offers a lookup by our reference.

## Verification
`test_connectors`: idempotent `create_po`, timeout-after-commit then `find_po` returns the PO (M0).
M3: end-to-end reconciliation shown on the instance timeline.
