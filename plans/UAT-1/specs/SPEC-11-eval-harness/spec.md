# SPEC-11: aos eval: behavioural eval runner

Milestone: UAT-1 | Status: see `plans/STATUS.md` | Priority: Must | Layer: agent
Owner: Swaroop | Planned: Sat 21 Nov – 5 · Mon 23 Nov | Estimate: 1.5 ed (engineer-days)
Requirements: NFR-01 (defined in `plans/UAT-1/milestone.md`)
Branch: `feat/SPEC-11-eval-harness` | Depends on: SPEC-00

## Goal

`make eval` runs every skill's scenarios through the real worker lane and grades them with rules; `LIVE=1 N=5` gives pass rates.

## Scope

In:
- `aos eval <pack> --org <org> --out eval-results [--live --runs N]` in `aos/cli.py`; the contract (args, exit code, `report.json` shape) is in `docs/ops/CI.md`.
- Runner admits each scenario as a task against the running stack (`AOS_API_URL`), waits for the result, grades with rule graders: field present/equals/regex, artifact count, verifier verdict, no tool call matching X, refusal text present, no restricted value in shareable output.
- Scenario format: `EvalSuite` YAML per skill in `packs/procurement_demo/evals/` with `scenarios: [{id, input, expect: {must: [...], quality: [...], safety: [...]}}]`; extend `registry/kinds.py` and validation.
- ADR `docs/adr/017-eval-thresholds.md`: must 100%, quality ≥ 80%, safety failures 0; N=5 live.
- Report includes tokens and cost per scenario.

Out:
- Model-graded checks (none for must-checks).

## Design

Reuse `aos/evals/runner.py` result shape; scripted mode uses the fake runtime so CI is deterministic.

## Acceptance criteria

- AC1: Given the scripted model, when `make eval` runs, then every scenario passes and `report.json` matches the contract.
- AC2: Given `LIVE=1 N=5`, then each scenario runs five times and the report shows pass rates and cost.
- AC3: Given a failing must-check, then exit code is non-zero and the failure includes the transcript path.

## Tests

- T-11-1 unit: Graders.
- T-11-2 integration: Runner against the stack with one suite (CI `evals` job turns on).

Every spec also keeps `make check` green and adds its demo step to the journey spec it belongs to
(`web/e2e/journeys/quick-quote.spec.ts` or `rfp.spec.ts`) when it is user-visible.

## Observability

Report JSON and HTML; CI job summary via `scripts/ci-summary.py evals`.

## Files likely touched

- `backend/src/aos/cli.py`
- `backend/src/aos/evals/`
- `backend/src/aos/registry/`
- `packs/procurement_demo/evals/`
- `docs/adr/`

## Dependencies

SPEC-00
