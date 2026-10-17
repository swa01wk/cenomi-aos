# M5 · Harden and demo (week 9)

**Goal:** the north star holds under failure, twice in a row.

**Exit gate**
- [ ] Every north-star check passes (`docs/plan/north-star.md`).
- [ ] The 17-stop demo runs in CI as one Playwright run, twice in a row from a fresh `make up`, fake model.
- [ ] The same demo runs once live on the real model.
- [ ] Backup → restore → reconcile drill leaves no duplicate effects and a verifying audit chain.

---

## Failure-path suite (M5-BE-01, backend, CI)
| Fault | Expected |
| --- | --- |
| Kill the worker mid-attempt | lease expires, attempt fenced, a new attempt finishes, no duplicate effect |
| Deliver the same inbound notification 3 times | one quote_triage Task |
| Lose the connector's reply after commit (ERP and mail) | UNKNOWN → reconciled, one effect each |
| Rotate the broker secret mid-run | in-flight token refused, next call gets a new token, work continues |
| Restart the kernel during an SSE session | clients reconnect, resume from cursor or reload the snapshot |
| Two schedulers running | each timer fires once; each ready Task gets one attempt |
| Edit an artifact during inference | stale result rejected, new attempt on fresh inputs |
| C13 (adapted from repair agents to packs): the worker tries to change a verifier, a policy or its own Skill | no worker endpoint can write a definition; published versions are immutable; a pack version that changes a verifier needs Risk approval before publish |

## Replay (M5-BE-02)
- `replayAttempt` with `exact` (recorded model and tool responses; must reproduce the artifact hash) and `re_evaluate`
  (live model, recorded tools). The gateway refuses committed tools in replay mode.

## Agent tuning (M5-AG-01)
- Tune prompts and tool descriptions against the M4 eval results; record the final baseline (pass rates, cost and
  tokens per Task) in an ADR. Thresholds are set there, not invented earlier.

## Demo (M5-FE-01)
- Playwright `e2e/demo.spec.ts` walks all 17 stops with the demo controls; screenshots attached to the CI run.
- A presenter script (`docs/plan/demo-script.md`) that follows the canvas start page.

---

## Stretch: a second domain pack (M5-ST-01)

**Goal:** show that AOS isn't built around procurement. A second, smaller scenario runs on the same kernel, Console
and Workspace with **no change to platform code**. This follows the validation rule in the AOS proposition: if a new
domain needs the Seat, Task, attempt, action, approval, verification, handover or audit model redesigned, the
platform is coupled too tightly.

**Scenario:** Sales lead qualification, from the Sales reference use case in the AOS Sales/HR proposition, cut down
to fit the POC.

| Step | What happens | Platform part it reuses |
| --- | --- | --- |
| 1 | An SDR starts **Qualify lead** from New job for lead LEAD-892 | `startInstance`, admission gates |
| 2 | The Sales Agent researches the account in the mock CRM and drafts a qualification note (`view: document`) with cited sources | assist and task graphs, context envelope, `sources_cited` |
| 3 | The SDR confirms the qualification | `DecisionCard`, decision record |
| 4 | The agent proposes a CRM update (`view: record_preview`): status, recommended product, follow-up date. The sales manager approves it. | policy REQUIRE_APPROVAL, bound approval, gateway, idempotent effect |
| 5 | The agent drafts outreach (`view: message_composer`). The SDR approves the send. | approval card, mock mail |
| 6 | Handover to the Account Executive; job closed | handover, outcome record, audit chain |

**What's allowed to change**

- A new pack `packs/sales_demo/`: Seat, two Skills (`lead_research`, `outreach_drafting`, each `skill.yaml` +
  `instructions.md`), a four-state workflow, artifact types using catalogue views, one policy, one eval suite.
- Org seed: two people (an SDR, a sales manager) and an Account Executive, in a Sales team.
- A mock CRM connector (`aos/connectors/mock_crm.py`) in the same style as the mock ERP, with an idempotent
  `update_lead` and a `find_lead_update` for reconciliation.
- Fake-model scripts for the two Skills.
- Domain tools or verifiers the pack points to, if any, under `aos/tools` and `aos/verifiers`.

**What must not change:** anything under `backend/src/aos/{kernel,api,gateway,worker,registry}` or `web/src`, and
`openapi.yaml`, the JSON Schemas or the migrations. `test_pack_neutral.py` keeps platform code free of pack names.
A `git diff --stat` over those paths is part of the exit evidence.

**Exit evidence**
- [ ] `aos validate sales_demo` passes, and both packs are synced and active at the same time.
- [ ] `e2e/second-pack.spec.ts` runs steps 1–6 with the fake model, on the same build that runs the 17-stop demo.
- [ ] The Console shows both Seats, both workflows and both jobs' timelines. The audit chain verifies across both.
- [ ] The diff over the platform paths above is empty for this story.
- [ ] Anything that *did* need a platform change is written up as an ADR. That's a finding, not a failure, but it
      has to be named.

## Stretch: first load test (M5-ST-02)

**Goal:** turn "built to scale out" into a measured claim. Correctness under load comes first, then throughput.

- `scripts/load/run.py` starts N jobs across both packs (100, 500, then 1,000) with the fake model and the demo
  clock. The vendor simulator replies and the scripted people approve.
- Runs: 1, 2 and 4 workers; one and two kernel API copies behind a proxy; two schedulers.
- Measured: jobs per minute, attempt claim-to-submit latency (p50, p95), Postgres CPU and connections, outbox lag
  from commit to SSE delivery, and lease expiries.
- Checked on every run: each committed effect happened exactly once (mock ERP and mail logs against action
  executions); no attempt committed after being fenced; the audit chain verifies.

**Exit evidence**
- [ ] The three run sizes complete with zero duplicate effects and a verifying audit chain.
- [ ] An ADR records the baseline and the first bottleneck found, with the measured numbers. Throughput targets
      for after the POC are set from it, not before.
