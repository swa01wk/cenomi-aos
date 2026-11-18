# SPEC-01: The job read path never changes state

Milestone: UAT-1 | Status: see `plans/STATUS.md` | Priority: Must | Layer: backend
Owner: Swaroop | Planned: 1 · Tue 17 Nov | Estimate: 1.5 ed (engineer-days)
Requirements: R-X-01, R-X-02, R-RFP-02, R-QQ-12 (defined in `plans/UAT-1/milestone.md`)
Branch: `feat/SPEC-01-read-only-job-read` | Depends on: SPEC-00

## Goal

Opening a job shows its state; it never heals, retries, completes tasks, polls mail or repins the pack.

## Scope

In:
- `GET /instances/{id}` (`api/routes.py` `get_instance`, ~L636): remove `heal_instance_pack_pin`, `refresh_decisions_for_viewer`, the IMAP poll, `quote_capture.sync_*`, `demo_rfp_acks.process_due_demo_rfp_acks` and the attribute syncs; it only builds the snapshot.
- `open_ready_decisions` (`kernel/decisions.py` ~L1600) only opens decisions whose state is ready. Remove every `heal_*` call from it.
- Delete `heal_po_create_after_payload`, `heal_po_create_after_budget_exhausted`, `heal_quote_comparison_after_quote`, `heal_intake_when_brief_valid` (replaced by SPEC-06/07 and honest task failure).
- Remaining heals that only repair demo data move to `kernel/demo_*` and run from the scheduler only when `AOS_DEMO=1`.
- Brief auto-confirm for the starter (`_auto_confirm_brief_for_job_starter`, ~L1869): run it on the write path when the intake task completes, as a pack option `auto_confirm: starter` on decision `brief_confirmed` (registry `kinds.py` + `validate.py`), recorded as a decision with actor = starter and reason `auto: starter is the decider`.
- Attribute syncs (`quote_count`, `proposal_count`, `ack_count`) run where artifacts are written (SPEC-05, SPEC-14), not on read.

Out:
- New features. Quote/proposal capture moves to SPEC-05 and SPEC-14.

## Design

A snapshot read is one read-only transaction (`SET TRANSACTION READ ONLY`) so any write fails loudly in tests. Decisions open from the transactions that make them ready (already called from `events.py`, `workflow.py`, `artifacts.py`, `task_retry.py`, `participants.py`). A failed task stays EXCEPTION and shows `Retry this step`; that is correct behaviour for UAT.

## Acceptance criteria

- AC1: Given any job, when `GET /instances/{id}` runs twice, then no row in `work.*`, `registry.*` or `evidence.*` changes (row counts and max `updated_at` equal).
- AC2: Given a `pr_create` task in EXCEPTION, when the job page is opened, then the task stays EXCEPTION and the job stays in `ordering`.
- AC3: Given an RFP job started by Noura, when `rfp_intake` completes, then `brief_confirmed` is recorded in the same transaction with actor `noura` and no card is shown to her.
- AC4: Given a Quick Quote job started by Faisal, when `request_intake` completes, then the Confirm the brief card is shown to Faisal (no auto-confirm).

## Tests

- T-01-1 functional: `test_snapshot_read_only.py`: snapshot twice, compare a DB fingerprint; the read runs in a READ ONLY transaction.
- T-01-2 functional: Failed `pr_create` stays EXCEPTION after GET.
- T-01-3 functional: Auto-confirm on intake completion for the starter; decision record actor and reason.
- T-01-4 unit: Pack validation accepts `auto_confirm: starter` and rejects unknown values.

Every spec also keeps `make check` green and adds its demo step to the journey spec it belongs to
(`web/e2e/journeys/quick-quote.spec.ts` or `rfp.spec.ts`) when it is user-visible.

## Observability

Log `decision.auto_confirmed` with instance, decision and actor.

## Files likely touched

- `backend/src/aos/api/routes.py`
- `backend/src/aos/kernel/decisions.py`
- `backend/src/aos/kernel/instances.py`
- `backend/src/aos/registry/kinds.py`
- `backend/src/aos/registry/validate.py`
- `packs/procurement_demo/workflows/sourcing_rfp.yaml`
- `backend/tests/`

## Dependencies

SPEC-00
