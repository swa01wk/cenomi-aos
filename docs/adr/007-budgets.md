# ADR 007 — Budget reservations and limits

- **Status:** Proposed (awaiting sign-off at the M0 gate)
- **Owner:** Runtime lead

## Context
An agent attempt spends model tokens and tool calls. Without limits a looping graph costs money and
time before anyone notices.

## Decision
- The Seat grant sets per-attempt limits (tokens, tool calls, wall time) and a per-Seat daily cap.
- The kernel **reserves** the attempt limit from the daily cap at claim time (admission gate) and
  settles to actual usage on submit or fail; expired attempts settle at the reservation.
- The worker reports usage with each event. Crossing the attempt limit fails the attempt with failure
  class `budget_exhausted`; the Task goes to an exception, not an automatic retry.

## Alternatives considered
Post-hoc accounting only (no prevention); provider-side spend limits (too coarse, not per Seat).

## Assumptions
Token counts reported by the model client are accurate enough for the POC.

## Verification
M2: a scripted `FakeModel` that loops trips `budget_exhausted`; the Seat's daily figure on the Console
shows the reservation then the settled amount.

## Amendment (2026-10-17)
Reserve at **admission** when the attempt row is written (`admit_attempt`), not at worker claim. Claim only
assigns the lease. Settlement still runs once when the attempt ends (submit, fail, or expiry).
