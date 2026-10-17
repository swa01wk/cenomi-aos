# ADR 008 — Evidence, retention and audit chain

- **Status:** Proposed (awaiting sign-off at the M0 gate)
- **Owner:** Kernel lead

## Context
Auditors need to show who did what, under which definition, and prove the record was not edited.

## Decision
- One append-only **hash chain per organization** in `evidence.audit_events`
  (`backend/src/aos/kernel/audit.py`). `record_hash = sha256(prev_hash + "\n" + canonical_json)`;
  genesis is 64 zeros. Canonical JSON sorts keys and has no whitespace.
- Appends take a row lock on `evidence.audit_heads` for the org, so sequence numbers are gap-free.
- A trigger rejects `UPDATE` and `DELETE` on audit rows; the `aos_kernel` role has only `SELECT` and
  `INSERT` on the evidence schema.
- `verify()` walks the chain and names the first broken record (changed content, broken link, gap).
  The Console exposes it as "Verify chain".
- Large evidence (prompts, model outputs, artifacts) goes to the object store; the audit record carries
  its content hash.
- Retention in the POC: keep everything. Retention classes are recorded on artifact types for MVP.

## Alternatives considered
External ledger or WORM storage (MVP option); signing each record (adds key management now).

## Verification
`test_kernel_foundations`: tamper, delete and re-hashed forgery are all detected; the chain
round-trips through Postgres; UPDATE/DELETE are refused (M0).
