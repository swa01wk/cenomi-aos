# M2 · Workflow layer (weeks 4–5)

**Goal:** decisions in the Workspace drive QQ-0001 from intake to RFQ drafting, and `aos simulate` reaches `closed`
with the fake model.

**Exit gate**
- [ ] On the real model: Faisal confirms brief v2 → Noura claims from the queue → confirms 3 suppliers → RFQ drafts
      are produced, the seeded leak is caught (REWORK) and attempt 2 passes `leak_check`.
- [ ] `aos simulate packs/procurement_demo --workflow quick_quote` reaches `closed` with the fake model, scripted people
      and stubbed effects, creating each Task exactly once.
- [ ] Guidebook C01 (duplicate command), C03 (concurrent completion), C09 (stale input), C12 (pinned version) pass.

**Walkthrough stops made real:** 4, 5 (with decision and parallel lookup), 6, 7 (drafts and REWORK; approval in M3).

---

## Backend

### M2-BE-01 Workflow interpreter
- Apply `ddl/0004_m2_workflow.sql`. `kernel/workflow.py` per the backend spec: Tasks on state entry, event matching,
  `by` role, guards with the M0 expression evaluator, effects, transition log, attributes and kernel-raised events.
- **Tests:** every transition in `quick_quote` fires from its event; a wrong `by` role is refused; a failing guard leaves
  the state unchanged and records the event; C12 — an instance pinned to v1 keeps running v1 after v2 is published.

### M2-BE-02 Parallel region and join
- `discovery` region from `event.intent_identified`; all-required join at `shortlisting` with `same(brief_version)`.
- **Tests:** C03 — two completions in parallel transactions dispatch one attempt; C09 — brief edited after the ranking
  re-runs `supplier_lookup` before the shortlist decision opens.

### M2-BE-03 Participants, queue and claim
- Binding at creation, by claim (`claimInstance`, `listQueue`), by rule (`team_owner(…)` resolved when needed).
- **Tests:** two claims at once → one 200 and one 409 `already_claimed`; only queue-team members see the queue.

### M2-BE-04 Decisions
- Kernel-opened decisions (backend spec), `decidePending` with Decision Records, `createArtifactVersion` for the
  requester's brief edits before confirmation.
- **Tests:** C01 — the same Idempotency-Key twice gives one Decision Record; a decision on a stale version → 409.

### M2-BE-05 Timers, scheduler and demo clock
- Readiness loop, timers with `SKIP LOCKED`, demo clock (`getDemoState`, `advanceClock`) behind `AOS_DEMO=1`.
- **Tests:** a timer fires once with two scheduler loops running; advancing the demo clock fires due timers.

### M2-BE-06 Simulate and Console reads
- `simulatePackVersion` and the `aos simulate` CLI (shared code); `listWorkflows`, `getWorkflowGraph`,
  `listInstances`, `getInstanceTimeline`, user stream `streamUserEvents`.

## Agent

### M2-AG-01 Task graph
- Generic Task graph from the harness spec; `request_intake` as the intake Task with resume-on-input; Task contracts per
  Skill spec (budgets, ceilings, tools).
### M2-AG-02 supplier_lookup and rfq_draft
- Skill specs `supplier_lookup.md`, `rfq_authoring.md` (draft part); fake scripts `happy` and `leak` (driven by the
  `seed_budget_leak` switch).
### M2-AG-03 Verifiers
- `brief_schema`, `sources_cited`, `leak_check` as rule code in `aos/verifiers/` (pack extensions; run by `kernel/verify.py`), each with unit tests from the Skill
  specs, and the REWORK loop with findings in the next envelope.

## Frontend

### M2-FE-01 Lists and live updates
- My jobs with waiting-on-me (WS-MyJobs), Team queue with claim and `ConflictNotice` (WS-Queue), user stream.
### M2-FE-02 Job page decisions and views
- `DecisionCard` (confirm brief, confirm shortlist), supplier ranking `ArtifactSheet` with selection, brief edit in the
  document view, REWORK notice from `verification.completed`.
### M2-FE-03 Console
- Workflow page (Console-Workflows), Instances (Console-Instances), instance timeline (Console-Instance without trace),
  simulate panel on the Packs page, Demo controls clock section.
- **Playwright:** `stop-04` to `stop-07` (drafts) with the fake model.

## Definition of done
- Every M2 operation served and tested; `aos simulate` in CI; the gate demo runs on the real model.
