# CI and test automation (UAT slice)

Every test layer runs in GitHub Actions. The scripted model gates every PR; the real model runs nightly and before a
UAT release, and its results (eval report, journey videos) are the evidence handed to the client.

| Workflow | Trigger | Jobs | Gate |
| --- | --- | --- | --- |
| `ci.yml` | every PR, push to `main`, called by `uat-release.yml` | `backend`, `web`, `evals`, `e2e-core`, `e2e-journeys` (quick-quote, rfp, negative), `security` | Required checks on `main` |
| `live.yml` | 02:00 IST Mon–Fri, on demand, called by `uat-release.yml` | `live-evals`, `live-journeys` (quick-quote, rfp) | Eval thresholds; journeys: Quick Quote ≥ 80%, RFP ≥ 60% of runs |
| `uat-release.yml` | tag `v*-uat` | `ci` → `live` (5 runs each) → `release` (evidence zip) → `deploy-uat` (manual approval) | All of the above, then a reviewer approves the deploy |

Shared steps live in `.github/actions/aos-stack` (build, mint a worker token, start postgres, api, web, mock-erp,
mock-mail and worker with no `.env`, no real mailboxes, no auto-publish) and `.github/actions/aos-stack-teardown`
(log annotations on failure, logs artifact, `down -v`). `scripts/ci-summary.py` writes the results into each job's
summary, so the run page reads without downloading anything.

## What each job proves

| Job | Runs | Proves |
| --- | --- | --- |
| `backend` | `make test` (unit, functional against Postgres 16, contracts, pack-neutral, simulate), `aos validate`, ruff | Kernel, API, worker protocol and pack are consistent |
| `web` | API types match `openapi.yaml`, Vitest, type-check and build | UI builds against the current contract |
| `evals` | `make eval` on the scripted model, vendor simulator on | Every eval scenario's rule graders pass (100%) |
| `e2e-core` | Playwright stops 1–5 | Publish, Seat tests, activation, new job, chat |
| `e2e-journeys` | `playwright.journeys.config.ts`, one project per matrix entry | The two lifecycles end to end with `AOS_DEMO=0`, and the negative cases |
| `security` | gitleaks, dependency review (PRs) | No committed secrets; no new high-severity dependency |
| `live-evals` | `make eval LIVE=1 N=5` | Real-model pass rates per skill against the thresholds |
| `live-journeys` | journeys with `E2E_LIVE=1`, repeated | The lifecycles hold on the real model; videos for UAT |

## Test levels and where they run

| Level | What | Where |
| --- | --- | --- |
| Unit | Tools and formulas (price, 70/30, module variance, BAFO outliers, rubric, spec checks), verifiers, parsers; React views with Vitest, including fixtures recorded from live runs | `backend`, `web` |
| Functional | Every API route against Postgres 16: decisions, claim, send, inbound hook, artifacts, visibility | `backend` |
| Integration | `aos simulate` per workflow; full stack on the scripted model: vendor simulator → mock mail → inbound → triage task → artifact; demo parity check | `backend`, `evals`, `e2e-journeys` |
| Live | Eval scenarios on the real model, N runs, rule graders | `live-evals` |
| E2E | Playwright journeys, scripted in CI and real model nightly with video | `e2e-core`, `e2e-journeys`, `live-journeys` |

## Turning the gates on during the slice

Some jobs pass vacuously until the work they check lands. Each switch below is a one-line change in a PR.

| Slice day | Change |
| --- | --- |
| 1 | `backend` green (pack-neutral allowlist, heals off the read path). Add the required checks to the `main` ruleset: `backend`, `web`, `evals`, `e2e-core`, `e2e-journeys (quick-quote)`, `e2e-journeys (rfp)`, `e2e-journeys (negative)` |
| 2 | Verifier scopes fixed → set `CI_STRICT_WARNINGS: "1"` on the validate step, so a pack warning fails CI |
| 4 | `aos eval` lands → the `evals` job starts running by itself (it checks `aos eval --help`) |
| 8 | Both journey specs land → remove `--pass-with-no-tests` from `e2e-journeys` |
| 8 | Lint clean → remove `continue-on-error` from the ruff step |
| After UAT | gitleaks baseline reviewed (dev secrets in `.env.example` and compose allowlisted in `.gitleaks.toml`) → remove `continue-on-error` from the secret scan |

## Contract for `make eval` (built on slice day 4)

CI calls `make eval` (scripted) and `make eval LIVE=1 N=<runs>` (real model) with the stack up and
`AOS_API_URL=http://localhost:8000/api`. The Makefile runs:

```
aos eval packs/procurement_demo --org seed/org.yaml --out eval-results [--live --runs N]
```

- Reads every `EvalSuite` in `packs/procurement_demo/evals/`, runs each scenario through the worker lane, grades the
  task result with rule graders (never a model judge for must-checks).
- Exits non-zero if any skill misses its threshold.
- Writes `eval-results/report.json`, which `scripts/ci-summary.py evals` renders:

```json
{
  "mode": "scripted | live",
  "runs": 5,
  "thresholds": {"must": 1.0, "quality": 0.8, "safety_failures": 0},
  "skills": [
    {"skill": "quote_triage",
     "scenarios": [
       {"id": "injection", "runs": 5, "must_pass_rate": 1.0, "quality_pass_rate": 0.8, "safety_failures": 0,
        "failures": [{"run": 3, "check": "price_extracted", "transcript": "runs/quote_triage/injection/3.json"}]}
     ]}
  ]
}
```

## Repository setup

| Kind | Name | Used by |
| --- | --- | --- |
| Secret | `OPENAI_API_KEY`, `OPENAI_MODEL` | `live.yml` (worker on the real model) |
| Variable | `AOS_MODEL_PRICE_IN_PER_MTOK`, `AOS_MODEL_PRICE_OUT_PER_MTOK` | `live.yml` (the worker refuses to start without prices) |
| Secret | `UAT_HOST`, `UAT_USER`, `UAT_SSH_KEY`, `UAT_SSH_KNOWN_HOSTS` | `uat-release.yml` deploy |
| Variable | `UAT_URL`, `UAT_DIR` (default `/srv/cenomi-aos`) | `uat-release.yml` deploy and smoke check |
| Environment | `uat`, with required reviewers | `uat-release.yml` deploy approval |

Set a monthly spend cap on the model key. Live cost scales with scenarios × runs plus journeys × runs; check the cost
column in the eval report after the first nightly run and lower `eval_runs` or the schedule if needed.

## The UAT host

A single VM with Docker and Docker Compose, the repo cloned at `UAT_DIR`, and its own `.env`:

```
AOS_RUNTIME=langgraph
OPENAI_API_KEY=...            # spend-capped key
OPENAI_MODEL=...
AOS_MODEL_PRICE_IN_PER_MTOK=...
AOS_MODEL_PRICE_OUT_PER_MTOK=...
AOS_DEMO=0
AOS_VENDOR_SIM=1
AOS_DEMO_CLOCK=1
AOS_SYNC_PACK_ON_START=0
AOS_IMAP_POLL=0
AOS_SESSION_SECRET=<random 64 chars>
```

`uat-release.yml` checks out the tag and runs `make up`. Put the web port behind HTTPS with basic auth, since sign-in
is persona pick without passwords (known limitation for UAT).

## Running the same things locally

```
make test                                   # backend job
cd web && npm test && npm run build         # web job
make up && make eval                        # evals job (scripted)
make up && make e2e-journeys J=quick-quote  # one journey, scripted model
E2E_LIVE=1 make e2e-journeys J=rfp          # one journey on the real model (worker on langgraph)
```
