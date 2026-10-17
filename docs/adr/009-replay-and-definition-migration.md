# ADR 009 — Replay modes and definition migration

- **Status:** Proposed (awaiting sign-off at the M0 gate)
- **Owner:** Kernel lead

## Context
Definitions change while instances are running, and investigating an outcome means re-running what
the agent saw.

## Decision
- Publishing a pack creates an immutable `registry.pack_versions` row; a trigger forbids changing
  definitions of a published version.
- An instance **pins** the pack version it started on and runs to completion on it. No in-flight
  migration in the POC.
- Replay modes:
  - **Exact** — re-run an attempt from its stored contract and recorded model/tool responses; must
    reproduce the submission byte for byte.
  - **Re-evaluate** — same contract, live model, recorded tool responses; used by evals to compare
    versions.
- Replays never commit effects; the gateway refuses committed tools in replay mode.

## Alternatives considered
Migrating running instances to new versions (needs state mapping; MVP).

## Verification
`test_published_definitions_are_immutable` (M0). M4: exact replay of a QQ-0001 attempt reproduces
its artifact hash.
