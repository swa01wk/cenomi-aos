# SPEC-00: CI for every test layer

Milestone: UAT-1 | Status: see `plans/STATUS.md` | Priority: Must | Layer: cross-cutting
Owner: Swaroop | Planned: Mon 16 Nov | Estimate: 0 ed (engineer-days)
Requirements: NFR-01, NFR-02 (defined in `plans/UAT-1/milestone.md`)
Branch: `chore/uat-1-plan-and-ci` | Depends on: None

## Goal

Every test layer (unit, functional, integration, live, e2e) runs in GitHub Actions, so nobody tests by hand.

## Scope

In:
- `ci.yml`: backend, web, evals (scripted), e2e-core, e2e-journeys (quick-quote, rfp, negative), security.
- `live.yml`: nightly and on-demand real-model evals and journeys with video; pass-rate gates.
- `uat-release.yml`: tag `v*-uat` -> ci -> live -> release with evidence -> approved deploy.
- Composite actions for the Compose stack; `.env` optional; `AOS_VENDOR_SIM` and `AOS_DEMO_CLOCK` passed through.
- `scripts/ci-summary.py`, `docs/ops/CI.md`, `web/playwright.journeys.config.ts`, Makefile `eval`, `e2e-journeys`.

Out:
- Repository secrets and the `uat` environment (set by a repo admin; list in `docs/ops/CI.md`).

## Design

Already implemented in this PR. See `docs/ops/CI.md` for the gate switch-on schedule.

## Acceptance criteria

- AC1: Given a PR, when it is opened, then backend, web, evals, e2e-core and e2e-journeys run and post a job summary.
- AC2: Given no `.env`, when the e2e job starts the stack, then Compose starts (env_file optional).
- AC3: Given a `v0.3.0-uat` tag, when it is pushed, then CI, live runs, the release and the gated deploy run in order.

## Tests

- T-00-1 integration: First PR run green for backend-independent jobs (web, security); backend turns green with SPEC-01/02.

Every spec also keeps `make check` green and adds its demo step to the journey spec it belongs to
(`web/e2e/journeys/quick-quote.spec.ts` or `rfp.spec.ts`) when it is user-visible.

## Observability

Job summaries per job; stack logs uploaded as artifacts.

## Files likely touched

- `.github/`
- `deploy/docker-compose.yml`
- `scripts/ci-summary.py`
- `docs/ops/CI.md`
- `web/playwright.journeys.config.ts`
- `Makefile`

## Dependencies

None
