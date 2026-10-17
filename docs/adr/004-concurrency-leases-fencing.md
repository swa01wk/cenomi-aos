# ADR 004 — Concurrency: leases, heartbeats and fencing

- **Status:** Proposed (awaiting sign-off at the M0 gate)
- **Owner:** Kernel lead

## Context
Workers crash, stall and come back late. A stale worker must never overwrite the result of the
attempt that replaced it.

## Decision
- At most one **active attempt** per Task (partial unique index on `work.attempts(task_id)` where
  status is active).
- Claiming an attempt grants a **lease** (default 90 s) and a monotonically increasing
  **fencing token** per Task.
- The worker heartbeats every `lease/3`. A missed lease lets the scheduler expire the attempt and
  create the next one with a higher token.
- Every worker call (heartbeat, event, submit, fail) carries the token. The kernel rejects a call whose
  token is not the Task's current one with `Fenced`; the worker stops immediately
  (`Worker.run_once()` returns `fenced`).

## Alternatives considered
Advisory locks held for the attempt's lifetime (lost on connection drop, invisible to audit);
optimistic version checks only at submit (a stale worker could still emit events and effects).

## Assumptions
Clock skew between worker and kernel is well under the lease length; the kernel's clock decides.

## Verification
`test_worker_protocol` — including the stalled worker that is fenced on return (M0). M2: chaos test
that pauses a worker past its lease.
