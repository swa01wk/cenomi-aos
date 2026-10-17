# ADR 003 — Task Contract and context envelope schemas

- **Status:** Proposed (awaiting sign-off at the M0 gate)
- **Owner:** Runtime lead

## Context
A worker must be able to run an attempt from what the kernel hands it, without reading the database.
What it receives must be versioned and auditable so a run can be replayed (ADR 009).

## Decision
On claim, the kernel returns an `Attempt` (`backend/src/aos/worker/protocol.py`):
`attempt_id`, `task_id`, `fencing_token`, `lease_seconds` and a **Task Contract**.

The contract is frozen at Task creation and carries:
- the pinned definition refs (`pack@version`, Seat, Skill, verifier, artifact type);
- the objective and acceptance criteria from the Skill;
- the tool allow-list and budget from the Seat grant;
- the **context envelope**: inputs resolved by the declared resolvers
  (`job_snapshot`, `running_summary`, `recent_messages`, `pending_items`), each with a source ref and
  a content hash, plus the classification ceiling for the attempt.

The worker returns a `Submission` (artifact payload conforming to the artifact type, proposed effects,
token usage). The kernel validates it against the artifact type before the verifier runs.

## Alternatives considered
Passing ids and letting the worker fetch context. Rejected: breaks ADR 001 and makes replay depend on
current data.

## Assumptions
Envelopes stay small (tens of KB); large inputs are passed as object-store refs.

## Verification
M1: a contract round-trips through JSON schema validation; the same contract replayed with the
`FakeModel` produces the same submission.
