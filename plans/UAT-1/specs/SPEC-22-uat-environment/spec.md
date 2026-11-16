# SPEC-22: UAT environment and release

Milestone: UAT-1 | Status: see `plans/STATUS.md` | Priority: Must | Layer: ops
Owner: Swaroop | Planned: Sat 28 Nov – 10 · Mon 30 Nov | Estimate: 1 ed (engineer-days)
Requirements: NFR-02, R-X-02 (defined in `plans/UAT-1/milestone.md`)
Branch: `feat/SPEC-22-uat-environment` | Depends on: SPEC-21

## Goal

The client opens a hosted UAT stack running the tagged build with evidence attached.

## Scope

In:
- VM with Docker, repo at `UAT_DIR`, `.env` per `docs/ops/CI.md` (UAT host).
- HTTPS with basic auth in front of the web port.
- Repo secrets and `uat` environment set; tag `v0.3.0-uat`; `uat-release.yml` green; deploy approved.
- Seed personas and synthetic supplier data; daily DB backup.
- `docs/ops/RUNBOOK.md` (start, stop, reset, restore, logs, rotate key).

Out:
- SSO (deferred).

## Design

Same Compose stack as CI.

## Acceptance criteria

- AC1: UAT URL healthy; release has evidence zip; runbook rehearsed once.

## Tests

- T-22-1 integration: Smoke check in `uat-release.yml`.

Every spec also keeps `make check` green and adds its demo step to the journey spec it belongs to
(`web/e2e/journeys/quick-quote.spec.ts` or `rfp.spec.ts`) when it is user-visible.

## Observability

Healthz; logs via `make logs` on the host.

## Files likely touched

- `docs/ops/`
- `.github/workflows/uat-release.yml`

## Dependencies

SPEC-21
