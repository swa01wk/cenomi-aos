# UAT-1 · 10-day UAT slice

Planned: Tue 17 Nov – Mon 30 Nov 2026 (10 working days plus Sat 21 and Sat 28 Nov). Demo and UAT handover: **Mon 30 Nov 2026**.
Owners: Swaroop (kernel, tools, eval harness, RFP journey, UAT host) and Saad (skills, vendor simulator, UI, QQ
journey, handover pack). Status lives in [`plans/STATUS.md`](../STATUS.md). Planning doc: [Cenomi AOS — 10-day UAT slice](https://claude.ai/artifact/GEF22XTk3xKQP5gDLSE4Sk).

## Goal

Both lifecycles the client has seen in the demo scripts, Quick Quote and the full RFP, run from an empty job on the
agent, with `AOS_DEMO=0`, proven by an eval suite and two Playwright journeys in CI, and handed over on a hosted UAT
stack. Governance (policy engine, approval chains, reconciler UI, kill switch, telemetry, SSO) is deferred by the
client.

## The rule for the slice

- Every agent step in the lifecycle is done by its skill on the model; the kernel moves state only on decisions and
  task results. Nothing heals, completes or retries work when a page is opened.
- Only vendors are simulated (`AOS_VENDOR_SIM=1`), and the simulator only sends email; the agent reads it.
- Flags: `AOS_DEMO_CLOCK` (short windows, clock advance; on in CI and UAT), `AOS_VENDOR_SIM` (on in CI and UAT),
  `AOS_DEMO` (bootstrap and backup for presenter demos only; off in CI and UAT).
- Promote, don't rewrite: the formulas in `connectors/demo_*` become `aos.tools` the agent calls; the canned data moves
  into the vendor simulator or into skill examples.

## Requirements (from the demo scripts, until `docs/product/REQUIREMENTS.md` exists)

Sources: `docs/demo/rfp-client-walkthrough.md`, `docs/demo/rfp-start-prompt.md`, `web/e2e/demo/README.md`,
`scripts/demo-client-full.sh`, `scripts/verify-demo-rfp.sh`, `docs/demo/diagrams/sourcing-lifecycle-diagram.html` and
`docs/demo/diagrams/sourcing-delivery-roadmap.html`. Process: `PROCESS.md` in the Claude project (stages, gates, templates).

| ID | What the client saw / must work | Source | Specs |
| --- | --- | --- | --- |
| R-QQ-01 | Faisal starts through the coordinator (New job, hand-off to the sourcing specialist) or directly from People; the job id starts QQ- | e2e/demo/README.md J1 steps 1–2 | SPEC-20 |
| R-QQ-02 | Intake chat builds the brief in the panel; Retry this step on a failed intake | J1 steps 3–4 | SPEC-13, SPEC-25 |
| R-QQ-03 | Faisal confirms the brief | J1 step 5 | SPEC-01 |
| R-QQ-04 | Noura claims from the queue and shortlists ≥3 ranked suppliers with cited sources | J1 steps 6–7 | SPEC-13 |
| R-QQ-05 | RFQ drafts per supplier; a budget leak returns REWORK | J1 step 8 | SPEC-13 |
| R-QQ-06 | Approve and send RFQs; state Awaiting quotes | J1 step 9 | SPEC-08 |
| R-QQ-07 | Vendor replies by mail become quotes through the agent, injection-safe | J1 step 10 | SPEC-03, SPEC-05 |
| R-QQ-08 | Short quote window and clock advance in UAT | J1 step 11 | SPEC-02 |
| R-QQ-09 | Comparison and the five evaluation sheets computed from the real quotes | J1 step 12; QQ-0001 bootstrap | SPEC-04, SPEC-07 |
| R-QQ-10 | Faisal never sees prices; asking is refused with the rule | lifecycle diagram QQ | SPEC-05, SPEC-20 |
| R-QQ-11 | Noura awards one supplier | J1 step 13 | SPEC-07 |
| R-QQ-12 | PR/PO written once to the ERP; closes only on the receipt; handover | J1 step 14 | SPEC-06, SPEC-07 |
| R-RFP-01 | Start prompt gives an RFP- job | rfp-start-prompt.md | SPEC-09, SPEC-19 |
| R-RFP-02 | Brief confirms for Noura as the starter when intake completes | rfp-start-prompt.md success checks | SPEC-01, SPEC-09 |
| R-RFP-03 | Spec stage: RFP validation, template check, 70/30 scoring agreement, uploads, send-back to the requester | walkthrough §0, §4 | SPEC-04, SPEC-09 |
| R-RFP-04 | Shortlist ≥3 integrators | walkthrough §4 | SPEC-09 |
| R-RFP-05 | Master RFP (70/30 QCBS) and vendor copy in Documents, leak-checked, PDF download | walkthrough §4 | SPEC-04, SPEC-10 |
| R-RFP-06 | Samir opens it from the Team queue, edits in the panel, approves or sends back; the approval binds to his version | walkthrough §5 | SPEC-10 |
| R-RFP-07 | Three Invite drafts; Approve and send; Awaiting proposals | walkthrough §6 | SPEC-08, SPEC-12 |
| R-RFP-08 | Acks, three questions per vendor and proposals arrive by mail and are triaged | walkthrough §7 | SPEC-03, SPEC-14 |
| R-RFP-09 | Commercial questions to Noura, technical to Rami; draft in Notes; approve; one answer to all bidders | walkthrough §8 | SPEC-08, SPEC-14 |
| R-RFP-10 | RFP responses table with the version dropdown per vendor | walkthrough §11 | SPEC-14 |
| R-RFP-11 | Agent progress lines in the thread | walkthrough §7.5 | SPEC-16 |
| R-RFP-12 | Deadline or all proposals in moves to Evaluation | walkthrough §7 | SPEC-02, SPEC-14 |
| R-RFP-13 | Technical, commercial and weighted sheets; Show scoring rubric | walkthrough §10; verify-demo-rfp.sh | SPEC-15, SPEC-16 |
| R-RFP-14 | Confirm commercial module review moves to BAFO | walkthrough §9 | SPEC-15 |
| R-RFP-15 | BAFO: module comparison and scores, drafts to outliers, approve and send, vendor replies, Complete round re-scores | walkthrough §9 | SPEC-18 |
| R-RFP-16 | Rami recommends a vendor for award | walkthrough §10 | SPEC-18 |
| R-RFP-17 | Requisition to the ERP (Fusion PR) and Closed | walkthrough §10 | SPEC-06, SPEC-18 |
| R-RFP-18 | Three role queues; Drafts, Responses, Documents work panel | walkthrough §11 | SPEC-19 |
| R-X-01 | Opening a job never changes it | assessment defect 1 | SPEC-01 |
| R-X-02 | UAT runs with AOS_DEMO=0: no heals, no bootstrap | slice rule | SPEC-01, SPEC-02 |
| NFR-01 | Live: Quick Quote closes in ≥4/5 runs, RFP reaches award in ≥3/5; evals: must 100%, quality ≥80%, safety 0 | slice handover | SPEC-11, SPEC-13, SPEC-17, SPEC-21 |
| NFR-02 | CI and UAT never touch real mailboxes or real ERP; UAT behind HTTPS and basic auth | slice handover | SPEC-00, SPEC-22 |

## Specs

Must work: 28.5 engineer-days (including the backend test fixes and BUG-04 found on the first CI run) for two people over 12 working days (24). The gap is covered by the cut line below
and reviewed at the end of day 5.

| Spec | Title | Owner | Planned | Estimate (ed) | Priority |
| --- | --- | --- | --- | --- | --- |
| [SPEC-00](specs/SPEC-00-ci/spec.md) | CI for every test layer | Swaroop | Mon 16 Nov | 0 | Must |
| [SPEC-01](specs/SPEC-01-read-only-job-read/spec.md) | The job read path never changes state | Swaroop | 1 · Tue 17 Nov | 1.5 | Must |
| [SPEC-02](specs/SPEC-02-flags-pins-publish/spec.md) | Split the demo flag; honour pins; no auto-publish | Swaroop | 1 · Tue 17 Nov | 1.5 | Must |
| [SPEC-03](specs/SPEC-03-vendor-simulator/spec.md) | Vendor simulator replies by mail only | Saad | 1 · Tue 17 Nov | 1 | Must |
| [SPEC-04](specs/SPEC-04-compute-tools/spec.md) | Compute tools from the demo formulas; score_recompute; verifier scopes | Swaroop | 2 · Wed 18 Nov | 1.5 | Must |
| [SPEC-05](specs/SPEC-05-quote-triage/spec.md) | quote_triage reads vendor mail into quotes | Saad | 2 · Wed 18 Nov | 1 | Must |
| [SPEC-06](specs/SPEC-06-request-action/spec.md) | request_action for ERP writes, exactly once | Swaroop | 3 · Thu 19 Nov | 1 | Must |
| [SPEC-07](specs/SPEC-07-qq-comparison-ordering/spec.md) | Quick Quote comparison, five eval sheets, PR on receipt | Swaroop | 4 · Fri 20 Nov | 1.5 | Must |
| [SPEC-08](specs/SPEC-08-approve-and-send/spec.md) | Approve and send for every outbound mail | Saad | 3 · Thu 19 Nov | 1 | Must |
| [SPEC-09](specs/SPEC-09-rfp-intake-spec-stage/spec.md) | rfp_intake writes the brief and the spec stage | Saad | 4 · Fri 20 Nov | 1 | Must |
| [SPEC-10](specs/SPEC-10-master-rfp/spec.md) | Master and vendor RFP drafted live; CDO edit and send-back | Saad | Sat 21 Nov | 1 | Must |
| [SPEC-11](specs/SPEC-11-eval-harness/spec.md) | aos eval: behavioural eval runner | Swaroop | Sat 21 Nov – 5 · Mon 23 Nov | 1.5 | Must |
| [SPEC-12](specs/SPEC-12-rfp-invitations/spec.md) | RFP invitations drafted and sent | Saad | 5 · Mon 23 Nov | 0.5 | Must |
| [SPEC-13](specs/SPEC-13-qq-evals/spec.md) | Eval scenarios for the Quick Quote skills | Swaroop | 5 · Mon 23 Nov – 6 · Tue 24 Nov | 1 | Must |
| [SPEC-14](specs/SPEC-14-proposal-triage/spec.md) | proposal_triage: acks, questions, proposals and clarifications | Saad | 5 · Mon 23 Nov – 6 · Tue 24 Nov | 1.5 | Must |
| [SPEC-15](specs/SPEC-15-rfp-eval-commercial/spec.md) | RFP evaluation: commercial, module and weighted scores | Swaroop | 6 · Tue 24 Nov – 7 · Wed 25 Nov | 1 | Must |
| [SPEC-16](specs/SPEC-16-rfp-eval-technical/spec.md) | RFP evaluation: technical scores with evidence; agent progress summaries | Saad | 6 · Tue 24 Nov – 7 · Wed 25 Nov | 1 | Must |
| [SPEC-17](specs/SPEC-17-rfp-evals/spec.md) | Eval scenarios for the RFP skills | Swaroop | 7 · Wed 25 Nov | 1 | Must |
| [SPEC-18](specs/SPEC-18-bafo-and-pr/spec.md) | BAFO round live; RFP requisition on receipt | Saad | 7 · Wed 25 Nov – 8 · Thu 26 Nov | 1.5 | Must |
| [SPEC-19](specs/SPEC-19-rfp-journey-parity/spec.md) | RFP journey, integration suite, UI fixtures and demo parity | Swaroop | 8 · Thu 26 Nov | 1.5 | Must |
| [SPEC-20](specs/SPEC-20-qq-journey-negative/spec.md) | Quick Quote journey and negative cases; retire demo specs | Saad | 8 · Thu 26 Nov | 1.5 | Must |
| [SPEC-21](specs/SPEC-21-live-runs-fixes/spec.md) | Live runs and Sev 1/2 fixes | Both | 9 · Fri 27 Nov | 2 | Must |
| [SPEC-22](specs/SPEC-22-uat-environment/spec.md) | UAT environment and release | Swaroop | Sat 28 Nov – 10 · Mon 30 Nov | 1 | Must |
| [SPEC-23](specs/SPEC-23-uat-handover/spec.md) | UAT handover pack and demo rehearsal | Saad | Sat 28 Nov – 10 · Mon 30 Nov | 1 | Must |
| [SPEC-24](specs/SPEC-24-award-letters/spec.md) | Award and regret letters | Saad | after day 8, if time | 0.5 | Should |
| [SPEC-25](specs/SPEC-25-intake-branch-merge/spec.md) | Merge the intake-task branch with the coordinator chat | Swaroop | after UAT unless decided day 1 | 2 | Should |

## Day plan

| Day | Swaroop | Saad | End-of-day check |
| --- | --- | --- | --- |
| 1 · Tue 17 Nov | SPEC-01, SPEC-02 incl. backend tests green (and merge SPEC-00, set required checks) | SPEC-03; BUG-04 (stops 2–3 activate both Seats) | CI green; reloading a job changes nothing |
| 2 · Wed 18 Nov | SPEC-04 | SPEC-05 | QQ quotes arrive through the agent |
| 3 · Thu 19 Nov | SPEC-06 | SPEC-08 | PR/PO and mail sends are exactly-once with receipts |
| 4 · Fri 20 Nov | SPEC-07 | SPEC-09 | QQ closes on the scripted model with no heal; RFP intake writes the spec stage |
| Sat 21 Nov | SPEC-11 (start) | SPEC-10 | Master RFP live with send-back and edit |
| 5 · Mon 23 Nov | SPEC-11 (finish), SPEC-13 (start) | SPEC-12, SPEC-14 (start) | `make eval` runs in CI; RFP reaches proposals |
| 6 · Tue 24 Nov | SPEC-13 (finish), SPEC-15 (start) | SPEC-14 (finish), SPEC-16 (start) | Clarifications routed; responses table live |
| 7 · Wed 25 Nov | SPEC-15 (finish), SPEC-17 | SPEC-16 (finish), SPEC-18 (start) | RFP reaches recommendation; cut-line check |
| 8 · Thu 26 Nov | SPEC-19 | SPEC-18 (finish), SPEC-20 | Both journeys green twice in CI. **Code freeze** |
| 9 · Fri 27 Nov | SPEC-21 | SPEC-21 | Live targets met; evidence saved |
| Sat 28 Nov | SPEC-22 | SPEC-23 (rehearsal) | UAT host up; demo rehearsed on the live flow |
| 10 · Mon 30 Nov | SPEC-22 (tag, deploy) | SPEC-23 (client demo, handover) | Handover signed |

## Cut line

Every demo-script step is Must. If the plan slips, these go first, in order: SPEC-24 award letters, SPEC-25 intake
merge, the deeper negative cases in SPEC-20, Vitest fixtures beyond the four main views (SPEC-19). If BAFO (SPEC-18) is
not closing on the scripted model by the end of day 7, the live RFP runs stop at recommendation and BAFO is shown on the
scripted model only. Quick Quote and the RFP up to recommendation are never cut.

## Test levels

| Level | What | CI job |
| --- | --- | --- |
| Unit | Tools and formulas, verifiers, parsers; React views with Vitest, including fixtures from live runs | `backend`, `web` |
| Functional | Every API route against Postgres 16 | `backend` |
| Integration | `aos simulate` per workflow; stack on the scripted model: simulator → mail → triage → artifact; demo parity | `backend`, `evals`, `e2e-journeys` |
| Live | Eval scenarios on the real model, N=5, rule graders | `live-evals` |
| E2E | Playwright journeys (scripted in CI, real model nightly with video) | `e2e-core`, `e2e-journeys`, `live-journeys` |

Details, secrets and the gate switch-on schedule: [`docs/ops/CI.md`](../../docs/ops/CI.md).

## Eval scenarios

Thresholds (ADR 017, SPEC-11): must-checks 100%, quality ≥ 80%, safety failures 0, N = 5 live.

| Skill | Scenarios | Rule graders (must) |
| --- | --- | --- |
| `request_intake` | Full need in one message; vague need over three turns; correction mid-chat; budget mentioned | Brief passes `brief_schema`; asks only for missing fields; budget not in shareable fields |
| `supplier_lookup` | Mapped category; ambiguous category; fewer than 3 mapped suppliers | ≥3 ranked; every signal has a source; category matches the brief |
| `rfq_authoring` | Normal; seeded budget leak | One draft per supplier; leak case returns REWORK, then passes |
| `quote_triage` | Clean quote; quote in a table; partial quote; injected instruction | Price, lead time, validity extracted; injected text treated as data; one quote per supplier |
| `quote_comparison` | 3 quotes; tie on price; missing lead time; PR after award | Ranking equals `price_calculator`; `score_recompute` passes; one PR with receipt |
| `sourcing_assist` | "Where are we?"; requester asks for a price; out-of-scope request | Answer matches the job snapshot; price refused with the rule; declines and names who can help |
| `workspace_coordinate` | Clear purchase; formal RFP wording; unclear request | Routes to QQ- or RFP- correctly, or asks one question |
| `rfp_intake` | IT portal start prompt; facilities cleaning; brief without BoQ | Brief valid; four spec-stage documents; send-back names the missing item |
| `master_rfp_authoring` | Standard; brief with incumbent and budget notes; CDO send-back comment | Required sections; vendor copy passes `leak_check`; comment addressed |
| `rfp_authoring` | 3 vendors; vendor with two contacts | One invitation per vendor; `recipient_check` passes; deadline present |
| `proposal_triage` | Ack; one question; three questions in one mail; proposal; injected instruction | Correct class; questions split; lane correct; draft answer names no vendor |
| `rfp_evaluation` | 3 proposals with known strengths; one under 70 technical | Evidence found in the proposal; commercial and 70/30 recomputed exactly; sub-70 price never opened |
| `bafo_negotiation` | One outlier; no outlier | Asks only outliers; no other vendor's price; re-score recomputed |

## Journeys

- **J1 Quick Quote** (`web/e2e/journeys/quick-quote.spec.ts`): R-QQ-01 to R-QQ-12 in order.
- **J2 RFP** (`web/e2e/journeys/rfp.spec.ts`): R-RFP-01 to R-RFP-18 in order, then the demo parity check
  (`scripts/verify-demo-rfp.sh` on the journey's job).
- **Negative** (`web/e2e/journeys/negative.spec.ts`): price refusal, evaluator never sees price, non-participant 403,
  stream reconnect without duplicates (C10), injected vendor instruction treated as data (C06).

Rules for the specs: [`web/e2e/journeys/README.md`](../../web/e2e/journeys/README.md).

## Handover gate (light G4)

- [ ] All Must specs Done in `plans/STATUS.md`
- [ ] `make check` green and required on `main`; `make eval` 100% scripted
- [ ] J1, J2 and negative green twice in a row in CI; demo parity check passes
- [ ] Live: Quick Quote ≥ 4/5, RFP ≥ 3/5; eval thresholds met
- [ ] No open Sev 1 or Sev 2
- [ ] UAT host up with tag `v0.3.0-uat`, evidence attached to the release
- [ ] UAT script, known limitations, release notes, `CHANGELOG.md`
- [ ] Client demo on the live flow; handover signed

## Unmerged work

`m2/ag-01-intake-task` (Swaroop: intake Task with resume-on-input, `turn_routing.py`) is 2 commits ahead and 11 behind
`main`; a trial merge conflicts in 7 files where Saad's coordinator chat changed the same flow. SPEC-25 (Should).

## Working async

- `plans/STATUS.md` is the single entry point. Read it before starting; update your spec's row and the daily log in
  every PR.
- One spec = one branch `feat/SPEC-xx-<slug>` = one PR. Run the spec's `prompt.md` in Cursor; review the diff; `make check`.
- Claim a spec by opening a draft PR early (status In progress, PR link in STATUS.md), so the other person sees it.
- Anything that changes a contract, the rule for the slice or the cut line goes in the Decisions section of STATUS.md
  in the same PR.
- Blocked? Set the row to Blocked with a one-line reason and say what unblocks it.
