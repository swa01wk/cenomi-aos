# SPEC-04: Compute tools from the demo formulas; score_recompute; verifier scopes

Milestone: UAT-1 | Status: see `plans/STATUS.md` | Priority: Must | Layer: backend
Owner: Swaroop | Planned: 2 · Wed 18 Nov | Estimate: 1.5 ed (engineer-days)
Requirements: R-QQ-09, R-RFP-03, R-RFP-13, R-RFP-15, R-RFP-05 (defined in `plans/UAT-1/milestone.md`)
Branch: `feat/SPEC-04-compute-tools` | Depends on: SPEC-02

## Goal

The agent calls deterministic tools for every number and check; the code does the arithmetic, the agent does the judgement.

## Scope

In:
- Enable `class: compute` in `kernel/worker_tools.authorize_tool_call` (today refused as `gateway.compute_not_in_m1`): execute builtin implementations under the allowed prefix `aos.tools.` in-process, record the call like a read tool, mark output trusted.
- New package `backend/src/aos/tools/` with pure functions promoted from `connectors/demo_eval_rubrics.py`, `demo_rfp_modules.py`, `demo_qq_lines.py`, `demo_rfp_spec_stage.py`, taking inputs instead of canned data: `price_calculator` (line totals, lowest-price commercial score `lowest/price*100`, weighted `tech*w_t + comm*w_c`), `module_scoring` (fair benchmark, variance %, module score), `bafo_outliers`, `rubric_template` (criteria rows per category), `spec_checks` (procurement validation, template compliance, scoring agreement, upload manifest from a brief).
- Declare them in `packs/procurement_demo/connectors/procurement_tools.yaml` (`transport: builtin`) and grant them to the skills that use them.
- `aos/verifiers/score_recompute.py`: recompute the comparison/evaluation scores with `aos.tools` from the inputs in the artifact and fail on any difference > 0.01.
- Verifier scopes: `leak_check.applies_to` += `master_rfp`, `rfp_invitation`, `bafo_email`; `recipient_check.applies_to` += `rfp_invitation`, `bafo_email`. `aos validate` has 0 warnings; set `CI_STRICT_WARNINGS: "1"` in `ci.yml`.
- `leak_check_diff` stays declared but unused (remove the grant if no skill needs it).

Out:
- Skills calling the tools (SPEC-07, -09, -15, -16, -18).

## Design

Tools are pure and typed (input/output JSON Schemas next to each module). The old `demo_*` builders call the new tools with their canned data, so the bootstrap still works.

## Acceptance criteria

- AC1: Given a task contract granting `price_calculator`, when the worker calls it, then the kernel returns the result and records the tool call.
- AC2: Given three quotes, when `price_calculator` runs, then commercial scores equal `lowest/price*100` to 2 dp.
- AC3: Given a comparison artifact with a tampered score, when `score_recompute` runs, then it returns FAIL with the row.
- AC4: Given the demo pack, when `aos validate` runs, then 0 errors and 0 warnings.

## Tests

- T-04-1 unit: Each tool against the old demo outputs (golden values) and new inputs.
- T-04-2 unit: `score_recompute` PASS and FAIL cases.
- T-04-3 functional: Worker callTool of a compute tool: allowed with grant, 403 without.
- T-04-4 unit: `aos validate` 0 warnings.

Every spec also keeps `make check` green and adds its demo step to the journey spec it belongs to
(`web/e2e/journeys/quick-quote.spec.ts` or `rfp.spec.ts`) when it is user-visible.

## Observability

Tool calls appear in the attempt's events like read tools.

## Files likely touched

- `backend/src/aos/tools/`
- `backend/src/aos/kernel/worker_tools.py`
- `backend/src/aos/verifiers/`
- `backend/src/aos/connectors/demo_*.py`
- `packs/procurement_demo/connectors/procurement_tools.yaml`
- `packs/procurement_demo/verifiers/`
- `.github/workflows/ci.yml`

## Dependencies

SPEC-02
