# Lifecycle journeys (UAT slice)

Playwright specs that walk the two lifecycles end to end, the way a client will in UAT. CI runs them on every PR with
the scripted model (`.github/workflows/ci.yml`, job `e2e-journeys`); the nightly `live` workflow runs them on the real
model and keeps a video of every run.

Config: `web/playwright.journeys.config.ts`. Stops 1–3 run first as setup (publish the pack, activate the Seat).

| File pattern | Project | Covers |
| --- | --- | --- |
| `quick-quote*.spec.ts` | `quick-quote` | Faisal starts a job → brief confirmed → Noura claims, shortlists ≥3 → RFQ drafts (seeded leak → REWORK) → approve and send → vendor simulator replies by mail → `quote_triage` → Faisal's price question refused → comparison → award → PR/PO → Closed with handover |
| `rfp*.spec.ts` | `rfp` | Noura starts an RFP → intake, brief → shortlist → master + vendor RFP → Samir sends back once, then approves → invitations sent → acks and questions → technical question to Rami, commercial to Noura, one answer for all → proposals → technical sheet with quoted evidence, no prices for evaluators → commercial and 70/30 → recommend → award + letters → PR → Closed |
| `negative*.spec.ts` | `negative` | Requester price refusal; evaluator never sees price; non-participant gets 403; reload and stream drop rebuild with no duplicate turns; injected instruction in a vendor email is treated as data |

## Rules for these specs

- **No demo endpoints.** Do not call `/api/demo/*` or rely on `AOS_DEMO=1`. Vendors reply through the vendor
  simulator (`AOS_VENDOR_SIM=1`), which only sends mail; the agent must triage it. A journey that passes only with
  demo heals is not evidence.
- **Assert on what people see**, plus the job snapshot for state (`GET /api/instances/{id}`): stage, open decisions,
  artifact versions. Never assert on model wording; assert on fields, cards and states.
- **Scripted model in CI**: every task in the journey needs a fake script (`backend/src/aos/worker/scripts/`). A missing
  script is a failing journey, not a skip.
- **Time**: quote and proposal windows use the short `demo_after` timers (`AOS_DEMO_CLOCK=1`, on in CI and UAT);
  wait on the job state with `expect.poll`, never a fixed sleep. Real-model runs (`E2E_LIVE=1`) get 40 minutes per
  journey.
- **Demo parity**: the RFP journey writes its job id to `journey-results/rfp-instance.txt`; CI then runs
  `scripts/verify-demo-rfp.sh` on that job, the same check the bootstrapped client demo passes (13 artifact types,
  rubric rows, 70/30 agreement, chat markers). Keep that script's needles in step with what the live agent writes.
- **Replaces the demo specs**: `e2e/demo/01-…` and `02-…` expect decisions and personas that no longer exist and call
  demo endpoints; retire them once these journeys pass.
- **One journey per file**, `test.describe.configure({ mode: "serial" })`, one `test.step` per lifecycle step, named
  after the step in `aos_quick_quote_flow` so the report reads like the UAT script.

Until the first spec lands, CI runs this project with `--pass-with-no-tests`; remove that flag in
`.github/workflows/ci.yml` once both journeys exist (planned for slice day 8).
