# ADR 001 — State ownership

- **Status:** Proposed (awaiting sign-off at the M0 gate)
- **Owner:** Kernel lead

## Context
Two components hold state about a running workflow: the AOS kernel (instances, tasks, attempts,
approvals) and LangGraph (checkpoints inside a graph run). If both are allowed to decide what happens
next, they will disagree after a crash, a retry or a late result.

## Decision
The kernel's finite-state machine is the only authority on lifecycle, permission and progression.
A LangGraph checkpoint is working memory for one Task attempt and nothing more:

- A graph never advances a workflow state, creates a Task or commits an external effect itself. It
  ends by submitting an artifact or a proposed effect to the kernel.
- Checkpoints live in the `lg_checkpoints` schema. The `aos_worker` database role can reach only that
  schema (migration `0002_grants.sql`); business state is reachable only through the kernel API.
- A retry or a REWORK starts a fresh LangGraph thread; it may read the prior attempt's artifacts
  through the context envelope, never its checkpoint.
- A resume after an approval or an answer is a new attempt that continues the interrupted thread from
  its checkpoint, with a freshly assembled context and a fresh policy check before any effect.

## Alternatives considered
- LangGraph as the workflow engine (interrupts for approvals, checkpoint as the system of record).
  Rejected: approvals, segregation of duties and fencing would live in graph code per workflow.
- Temporal or another durable-execution engine. Rejected for the POC: a second state authority to
  reconcile with the kernel, and more infrastructure than the scenario needs.

## Assumptions
One attempt is short (minutes), so losing its checkpoint costs at most a re-run of that attempt.

## Verification
`test_worker_role_cannot_read_business_state` (M0). In M2: kill a worker mid-attempt; the kernel
expires the lease, starts attempt 2 and the instance timeline shows one completed attempt.
