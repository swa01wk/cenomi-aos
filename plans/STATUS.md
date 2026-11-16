# STATUS: Cenomi AOS        Updated: 2026-11-16

Current milestone: **UAT-1 · 10-day UAT slice** ([plan](UAT-1/milestone.md)) | Next gate: **UAT handover (light G4)
on Mon 30 Nov 2026** | Planning doc: [Cenomi AOS — 10-day UAT slice](https://claude.ai/artifact/GEF22XTk3xKQP5gDLSE4Sk)

## How to use this file

- Start every session here. Find your next spec (owner + planned day), open its `prompt.md` in Cursor.
- In the PR for a spec, update its row (status, PR link) and add a dated line to the daily log. Keep edits to your
  own rows to avoid conflicts.
- Spec statuses: Draft → Ready → In progress → In review → Done, or Blocked (with a reason).

## Milestones

| Milestone | Scope | Status | Exit date |
| --- | --- | --- | --- |
| M0 Foundations | Pack format, kernel, audit, connectors, worker protocol | Done | Oct 2026 |
| M1 Seat and chat | Publish, Seat lifecycle, jobs and chat | Done | 19 Oct 2026 |
| M2 Workflow layer | Interpreter, decisions, queues, parallel join, timers, task graph, verifiers | Backend done; exit gate superseded by UAT-1 | — |
| **UAT-1 10-day slice** | Both lifecycles live with AOS_DEMO=0, evals, journeys, UAT host | **In progress** | 30 Nov 2026 |
| M3–M5 (governance, observe, harden) | Policy, approvals, kill switch, telemetry | Deferred by the client | — |

## UAT-1 specs

| Spec | Title | Requirements | Owner | Planned | Branch | PR | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| [SPEC-00](UAT-1/specs/SPEC-00-ci/spec.md) | CI for every test layer | NFR-01, NFR-02 | Swaroop | Mon 16 Nov | `chore/uat-1-plan-and-ci` | [#47](https://github.com/swa01wk/cenomi-aos/pull/47) | In review |
| [SPEC-01](UAT-1/specs/SPEC-01-read-only-job-read/spec.md) | The job read path never changes state | R-X-01, R-X-02, R-RFP-02, R-QQ-12 | Swaroop | 1 · Tue 17 Nov | `feat/SPEC-01-read-only-job-read` | — | Ready |
| [SPEC-02](UAT-1/specs/SPEC-02-flags-pins-publish/spec.md) | Split the demo flag; honour pins; no auto-publish | R-X-02, R-QQ-08, R-RFP-12 | Swaroop | 1 · Tue 17 Nov | `feat/SPEC-02-flags-pins-publish` | — | Ready |
| [SPEC-03](UAT-1/specs/SPEC-03-vendor-simulator/spec.md) | Vendor simulator replies by mail only | R-QQ-07, R-RFP-08, R-RFP-15 | Saad | 1 · Tue 17 Nov | `feat/SPEC-03-vendor-simulator` | — | Ready |
| [SPEC-04](UAT-1/specs/SPEC-04-compute-tools/spec.md) | Compute tools from the demo formulas; score_recompute; verifier scopes | R-QQ-09, R-RFP-03, R-RFP-13, R-RFP-15, R-RFP-05 | Swaroop | 2 · Wed 18 Nov | `feat/SPEC-04-compute-tools` | — | Ready |
| [SPEC-05](UAT-1/specs/SPEC-05-quote-triage/spec.md) | quote_triage reads vendor mail into quotes | R-QQ-07, R-QQ-10 | Saad | 2 · Wed 18 Nov | `feat/SPEC-05-quote-triage` | — | Ready |
| [SPEC-06](UAT-1/specs/SPEC-06-request-action/spec.md) | request_action for ERP writes, exactly once | R-QQ-12, R-RFP-17 | Swaroop | 3 · Thu 19 Nov | `feat/SPEC-06-request-action` | — | Ready |
| [SPEC-07](UAT-1/specs/SPEC-07-qq-comparison-ordering/spec.md) | Quick Quote comparison, five eval sheets, PR on receipt | R-QQ-09, R-QQ-11, R-QQ-12 | Swaroop | 4 · Fri 20 Nov | `feat/SPEC-07-qq-comparison-ordering` | — | Ready |
| [SPEC-08](UAT-1/specs/SPEC-08-approve-and-send/spec.md) | Approve and send for every outbound mail | R-QQ-06, R-RFP-07, R-RFP-09, R-RFP-15 | Saad | 3 · Thu 19 Nov | `feat/SPEC-08-approve-and-send` | — | Ready |
| [SPEC-09](UAT-1/specs/SPEC-09-rfp-intake-spec-stage/spec.md) | rfp_intake writes the brief and the spec stage | R-RFP-01, R-RFP-02, R-RFP-03 | Saad | 4 · Fri 20 Nov | `feat/SPEC-09-rfp-intake-spec-stage` | — | Ready |
| [SPEC-10](UAT-1/specs/SPEC-10-master-rfp/spec.md) | Master and vendor RFP drafted live; CDO edit and send-back | R-RFP-05, R-RFP-06 | Saad | Sat 21 Nov | `feat/SPEC-10-master-rfp` | — | Ready |
| [SPEC-11](UAT-1/specs/SPEC-11-eval-harness/spec.md) | aos eval: behavioural eval runner | NFR-01 | Swaroop | Sat 21 Nov – 5 · Mon 23 Nov | `feat/SPEC-11-eval-harness` | — | Ready |
| [SPEC-12](UAT-1/specs/SPEC-12-rfp-invitations/spec.md) | RFP invitations drafted and sent | R-RFP-07 | Saad | 5 · Mon 23 Nov | `feat/SPEC-12-rfp-invitations` | — | Ready |
| [SPEC-13](UAT-1/specs/SPEC-13-qq-evals/spec.md) | Eval scenarios for the Quick Quote skills | NFR-01, R-QQ-02, R-QQ-04, R-QQ-05, R-QQ-07, R-QQ-09, R-QQ-10 | Swaroop | 5 · Mon 23 Nov – 6 · Tue 24 Nov | `feat/SPEC-13-qq-evals` | — | Ready |
| [SPEC-14](UAT-1/specs/SPEC-14-proposal-triage/spec.md) | proposal_triage: acks, questions, proposals and clarifications | R-RFP-08, R-RFP-09, R-RFP-10, R-RFP-12 | Saad | 5 · Mon 23 Nov – 6 · Tue 24 Nov | `feat/SPEC-14-proposal-triage` | — | Ready |
| [SPEC-15](UAT-1/specs/SPEC-15-rfp-eval-commercial/spec.md) | RFP evaluation: commercial, module and weighted scores | R-RFP-13, R-RFP-14 | Swaroop | 6 · Tue 24 Nov – 7 · Wed 25 Nov | `feat/SPEC-15-rfp-eval-commercial` | — | Ready |
| [SPEC-16](UAT-1/specs/SPEC-16-rfp-eval-technical/spec.md) | RFP evaluation: technical scores with evidence; agent progress summaries | R-RFP-11, R-RFP-13 | Saad | 6 · Tue 24 Nov – 7 · Wed 25 Nov | `feat/SPEC-16-rfp-eval-technical` | — | Ready |
| [SPEC-17](UAT-1/specs/SPEC-17-rfp-evals/spec.md) | Eval scenarios for the RFP skills | NFR-01, R-RFP-03, R-RFP-05, R-RFP-08, R-RFP-09, R-RFP-13, R-RFP-15 | Swaroop | 7 · Wed 25 Nov | `feat/SPEC-17-rfp-evals` | — | Ready |
| [SPEC-18](UAT-1/specs/SPEC-18-bafo-and-pr/spec.md) | BAFO round live; RFP requisition on receipt | R-RFP-15, R-RFP-16, R-RFP-17 | Saad | 7 · Wed 25 Nov – 8 · Thu 26 Nov | `feat/SPEC-18-bafo-and-pr` | — | Ready |
| [SPEC-19](UAT-1/specs/SPEC-19-rfp-journey-parity/spec.md) | RFP journey, integration suite, UI fixtures and demo parity | R-RFP-01, R-RFP-18, NFR-01 | Swaroop | 8 · Thu 26 Nov | `feat/SPEC-19-rfp-journey-parity` | — | Ready |
| [SPEC-20](UAT-1/specs/SPEC-20-qq-journey-negative/spec.md) | Quick Quote journey and negative cases; retire demo specs | R-QQ-01, R-QQ-10, NFR-01 | Saad | 8 · Thu 26 Nov | `feat/SPEC-20-qq-journey-negative` | — | Ready |
| [SPEC-21](UAT-1/specs/SPEC-21-live-runs-fixes/spec.md) | Live runs and Sev 1/2 fixes | NFR-01 | Both | 9 · Fri 27 Nov | `feat/SPEC-21-live-runs-fixes` | — | Ready |
| [SPEC-22](UAT-1/specs/SPEC-22-uat-environment/spec.md) | UAT environment and release | NFR-02, R-X-02 | Swaroop | Sat 28 Nov – 10 · Mon 30 Nov | `feat/SPEC-22-uat-environment` | — | Ready |
| [SPEC-23](UAT-1/specs/SPEC-23-uat-handover/spec.md) | UAT handover pack and demo rehearsal | R-QQ-01, R-RFP-01 | Saad | Sat 28 Nov – 10 · Mon 30 Nov | `feat/SPEC-23-uat-handover` | — | Ready |
| [SPEC-24](UAT-1/specs/SPEC-24-award-letters/spec.md) | Award and regret letters | R-RFP-17 | Saad | after day 8, if time | `feat/SPEC-24-award-letters` | — | Draft (Should) |
| [SPEC-25](UAT-1/specs/SPEC-25-intake-branch-merge/spec.md) | Merge the intake-task branch with the coordinator chat | R-QQ-02 | Swaroop | after UAT unless decided day 1 | `feat/SPEC-25-intake-branch-merge` | — | Draft (Should) |

## Handover gate (light G4)

| Item | Status | Evidence |
| --- | --- | --- |
| All Must specs Done | Not started | this table |
| `make check` green and required on `main` | Not started | CI |
| `make eval` 100% scripted | Not started | `evals` job |
| J1, J2, negative green twice in CI; demo parity | Not started | `e2e-journeys` jobs |
| Live: QQ ≥ 4/5, RFP ≥ 3/5; eval thresholds | Not started | `live.yml` |
| No open Sev 1/2 | — | Bugs below |
| UAT host up, `v0.3.0-uat`, evidence on the release | Not started | `uat-release.yml` |
| UAT script, known limitations, release notes | Drafted | `plans/UAT-1/` |
| Client demo on the live flow; handover signed | Not started | — |

## Bugs (Sev 1 production down / data loss / security · Sev 2 Must broken, no workaround · Sev 3 workaround · Sev 4 cosmetic)

| ID | Sev | Requirement | Found | Spec / PR | Status |
| --- | --- | --- | --- | --- | --- |
| BUG-01 | 2 | R-X-01, R-QQ-12 | 16 Nov (assessment) | SPEC-01 | Open: job page heals can close a job without an ERP write |
| BUG-02 | 2 | NFR-02 | 16 Nov | SPEC-00 | Fixed in SPEC-00: CI e2e job could not start (Compose required `.env`) |
| BUG-03 | 2 | R-X-02 | 16 Nov | SPEC-02 (heal tests with SPEC-01) | Open: backend CI on `main` code runs 428 tests, 25 failures and 34 errors (pack-neutral 554 hits; publish-flow `setUpClass` errors from auto-publish; 4 pack warnings) |
| BUG-04 | 2 | R-QQ-01 | 16 Nov (first CI run, PR #47) | Saad, day 1 (with SPEC-03) | Open: Playwright stop 4 fails — the workspace landing needs the workspace-coordinator Seat active, but stops 2–3 only configure and activate the first Seat. Configure, approve and activate both Seats in stops 2–3 |
| BUG-05 | 3 | — | 16 Nov (first CI run) | Fixed in PR #47 | `web/src/api/schema.d.ts` was not regenerated after demo routes were added to `openapi.yaml`; `workComposerHint.test.ts` expected the old hint copy. `web` job now green |

## Open questions and risks

- **Capacity:** Must work is 28.5 engineer-days against 24 (two people, 10 days plus two Saturdays), after adding the
  backend test fixes and BUG-04 found on the first CI run. Review at the end of day 5; use the cut line in the plan.
- **Agent effects were never wired:** `request_action` is in the contract but not implemented, and compute tools are
  refused; SPEC-04 and SPEC-06 add them. Until then PR/PO creation only "works" through heals.
- **Live variance on long RFP runs:** target 3/5; fix prompts, not tests.
- **UAT host:** pick the VM on day 1 so SPEC-22 is not blocked.
- **Repository secrets** for `live.yml` and the deploy (list in `docs/ops/CI.md`): needed by day 4 for the first live run.

## Decisions

| Date | Decision | By |
| --- | --- | --- |
| 2026-11-16 | Demo and UAT handover on Mon 30 Nov 2026 | Swaroop |
| 2026-11-16 | Governance (policy, approval chains, kill switch, telemetry, SSO) deferred by the client | Client |
| 2026-11-16 | Simulated vendors are acceptable in UAT | Swaroop |
| 2026-11-16 | No separate tester: every test layer runs in GitHub Actions | Swaroop |
| 2026-11-16 | Work Sat 21 and Sat 28 Nov | Swaroop, Saad |
| 2026-11-16 | Every demo-script step is Must; BAFO is Must; award letters and intake merge are Should | Swaroop |

## Daily log (newest first)

- 2026-11-16 · Claude: first CI run on #47 — stack, publish, Seat activation, evals and journey jobs run; backend red
  (BUG-03), e2e-core stop 4 red (BUG-04), web job fixed and green (BUG-05); security green (dependency review advisory until Dependency graph
  is enabled in repo settings).
- 2026-11-16 · Swaroop/Claude: slice planned; SPEC-00 CI and the plan in PR #47; specs SPEC-01 to SPEC-25 written.
  Next: merge #47, set required checks, start SPEC-01/02 (Swaroop) and SPEC-03 (Saad).
