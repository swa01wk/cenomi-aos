# ADR 012 — Context freshness, visibility and memory writes

- **Status:** Proposed
- **Owner:** Kernel lead

## Decision
- The kernel assembles a new `ContextEnvelope` before every model step; the worker never reads the database.
- Visibility is enforced once, in `artifacts.project()`, and used for both API reads and envelopes. Fields above the
  participant's visibility or the contract's classification ceiling are removed and listed in `redactions`.
- RFQ contracts use a `shareable` ceiling, so internal fields such as `budget_guidance` never reach the model there.
- No shared agent memory in the POC. The only durable writes are artifact versions (with inputs and sources) and
  turns. `running_summary` is marked lossy; requirements, approvals and failures live in kernel records.
- Freshness: `submit` carries the input versions used; a mismatch makes the verdict STALE and starts a new attempt.

## Verification
Refusal eval: `unit_price`, `total` and `po_amount` appear only in `redactions` for requester envelopes. C09 test:
brief edited during inference → STALE → re-run on the new version.
