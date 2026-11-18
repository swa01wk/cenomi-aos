# SPEC-06: request_action for ERP writes, exactly once

Milestone: UAT-1 | Status: see `plans/STATUS.md` | Priority: Must | Layer: backend
Owner: Swaroop | Planned: 3 · Thu 19 Nov | Estimate: 1 ed (engineer-days)
Requirements: R-QQ-12, R-RFP-17 (defined in `plans/UAT-1/milestone.md`)
Branch: `feat/SPEC-06-request-action` | Depends on: SPEC-01

## Goal

The agent writes the PR/PO to the ERP through the kernel once, with a receipt, and the job closes only on that receipt.

## Scope

In:
- Implement `requestAction` (`POST /worker/attempts/{id}/actions`, already in `openapi.yaml`, x-milestone M3) without policy or approvals: authorize the tool is a `committed_effect` granted in the contract; persist intent; call the connector through the gateway with the idempotency key; store the receipt.
- Migration `0007_action_executions.sql`: `work.action_executions` from `docs/specs/backend/ddl/0005_m3_governed_actions.sql` without the `gov.approvals` FK (keep `approval_id` nullable, no FK). Remove the table from the reference DDL and `TABLES` in `test_reference_ddl.py`.
- Idempotency key = `sha256(task_id, tool, args_hash)`; on timeout or error, state UNKNOWN and look up `reconcile_with` (`find_pr`, `find_po`) before any retry.
- Worker: `request_action` tool handler in `worker/graphs/tool_handlers.py` and the fake runtime; `http_client.request_action`.
- `pr_create` / `po_create` / `rfp_pr_create` tasks complete only when an action execution for them is SUCCEEDED or RECONCILED (checked in `worker_submit`).

Out:
- Policy engine, approval chains, Console actions page (deferred by the client).

## Design

Effects never run inside the kernel transaction: intent row commits, gateway call, then receipt commit (ADR 001 pattern).

## Acceptance criteria

- AC1: Given a `po_create` attempt, when it requests `create_po` twice with the same args, then one PO exists and both calls return the same receipt.
- AC2: Given the ERP times out after creating the PO, when the attempt retries, then `find_po` reconciles and no second PO is created (C04).
- AC3: Given a task without a SUCCEEDED action, when it submits, then the verdict is FAIL with 'no ERP receipt'.
- AC4: Given an attempt asks for `create_po` not in its contract, then 403 before any connector call (C02).

## Tests

- T-06-1 functional: Idempotent create; same receipt on replay.
- T-06-2 integration: Timeout after write -> UNKNOWN -> reconcile -> RECONCILED (C04).
- T-06-3 functional: Submit without receipt fails.
- T-06-4 functional: Not-granted tool -> 403, no connector call (C02).

Every spec also keeps `make check` green and adds its demo step to the journey spec it belongs to
(`web/e2e/journeys/quick-quote.spec.ts` or `rfp.spec.ts`) when it is user-visible.

## Observability

`action.intended`, `action.succeeded`, `action.unknown`, `action.reconciled` execution events.

## Files likely touched

- `backend/src/aos/api/routes.py`
- `backend/src/aos/kernel/`
- `backend/migrations/`
- `docs/specs/backend/ddl/`
- `backend/src/aos/worker/`
- `backend/tests/`

## Dependencies

SPEC-01
