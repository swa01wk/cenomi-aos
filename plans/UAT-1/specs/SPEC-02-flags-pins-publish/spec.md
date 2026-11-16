# SPEC-02: Split the demo flag; honour pins; no auto-publish

Milestone: UAT-1 | Status: see `plans/STATUS.md` | Priority: Must | Layer: backend
Owner: Swaroop | Planned: 1 · Tue 17 Nov | Estimate: 1.5 ed (engineer-days)
Requirements: R-X-02, R-QQ-08, R-RFP-12 (defined in `plans/UAT-1/milestone.md`)
Branch: `feat/SPEC-02-flags-pins-publish` | Depends on: SPEC-00

## Goal

UAT runs with `AOS_DEMO=0` and still has short quote windows and the vendor simulator, on the pack version each job started with.

## Scope

In:
- `kernel/settings.py`: add `demo_clock` (`AOS_DEMO_CLOCK`) and `vendor_sim` (`AOS_VENDOR_SIM`); `AOS_DEMO` keeps only bootstrap, backup/restore and demo endpoints.
- `clock.configure(demo_enabled=...)` in `api/app.py` reads `demo_clock`; `workflow.py` timer `use_demo` reads `clock.demo_enabled()` only (drop the `AOS_RFQ_DEMO_SHORT_DEADLINE` env read; keep it as an alias in settings for one release).
- `/demo/clock/advance` is allowed when `AOS_DEMO_CLOCK=1` (platform admin only); other `/demo/*` routes stay behind `AOS_DEMO`.
- `sync_pack_on_start` default `False`; `bump_pack_manifest_version` never runs at startup.
- Remove `heal_instance_pack_pin` and `align_instance_pack_to_seat` from any non-demo path; a running job keeps its pinned version (ADR 009, C12).
- `test_pack_neutral.py`: add an explicit allowlist for `kernel/demo_*`, `connectors/demo_*` and the named web files, with an ADR (`docs/adr/016-uat-slice-flags-and-demo-allowlist.md`). Fix the hits in `decisions.py` and `instances.py` instead of allowlisting them. Remove the `"ven" + "dor-replies"` string split.
- **Backend CI green.** On `main`, CI runs 428 tests with 25 failures and 34 errors (BUG-03 in `plans/STATUS.md`). Fix or retire each: the `heal_*` tests go with SPEC-01; the publish-flow `setUpClass` errors come from `AOS_SYNC_PACK_ON_START` defaulting on; fix `test_mcp_read_tools_match_mock_server_schemas`, `test_validate_endpoint_matches_cli`, `test_demo_pack_is_valid`, `test_quick_quote_simulation_happy_path`, `test_dry_run_through_the_fake_model_with_verifiers` and the rest against the current pack. Retiring a test needs a one-line reason in the PR.
- `.env.example`: `AOS_DEMO=0`, `AOS_DEMO_CLOCK=1`, `AOS_VENDOR_SIM=1`, `AOS_SYNC_PACK_ON_START=0` with comments.

Out:
- Deleting demo modules (they stay for presenter demos).

## Design

Three independent flags, read once in `Settings`. Document each in `docs/ops/CI.md` (UAT host section) and `.env.example`.

## Acceptance criteria

- AC1: Given `AOS_DEMO=0, AOS_DEMO_CLOCK=1`, when RFQs are sent, then the quote window uses `demo_after` and the clock can be advanced by a platform admin.
- AC2: Given `AOS_DEMO=0`, when `/demo/rfp/bootstrap` is called, then it returns 404.
- AC3: Given a job pinned to pack v56 and v57 published, when the job continues, then it runs on v56.
- AC4: Given a fresh start, when the API boots, then no pack version is published and no file under `packs/` changes.
- AC5: `make test` is green including `test_pack_neutral.py`, and the CI `backend` job passes.

## Tests

- T-02-1 unit: Settings parse the three flags and the alias.
- T-02-2 functional: Demo routes 404 without `AOS_DEMO`; clock advance works with `AOS_DEMO_CLOCK`.
- T-02-3 functional: C12: pinned version honoured after a newer publish.
- T-02-4 unit: Pack-neutral allowlist is explicit and matches the ADR list.

Every spec also keeps `make check` green and adds its demo step to the journey spec it belongs to
(`web/e2e/journeys/quick-quote.spec.ts` or `rfp.spec.ts`) when it is user-visible.

## Observability

Startup log line listing the three flags.

## Files likely touched

- `backend/src/aos/kernel/settings.py`
- `backend/src/aos/api/app.py`
- `backend/src/aos/kernel/workflow.py`
- `backend/src/aos/kernel/pack_publish.py`
- `backend/src/aos/kernel/demo_pack_repin.py`
- `backend/src/aos/api/routes.py`
- `backend/tests/test_pack_neutral.py`
- `.env.example`
- `docs/adr/`

## Dependencies

SPEC-00
