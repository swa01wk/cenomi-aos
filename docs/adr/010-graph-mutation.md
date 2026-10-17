# ADR 010 — Graph mutation

- **Status:** Proposed (awaiting sign-off at the M0 gate)
- **Owner:** Runtime lead

## Context
The reference architecture lets an agent propose amendments to a running workflow (add a Task, skip a
step). That power needs its own governance.

## Decision
None in the POC. Workflow graphs are exactly what the published definition says (ADR 002). An agent
that thinks the plan is wrong submits an artifact with a `REWORK`/exception note; a person decides.

Agent-proposed amendments, with approval and audit, are deferred to MVP.

## Verification
`aos validate` has no amendment kind; the kernel API exposes no endpoint that changes an instance's
Task set.
