# M2 · Workflow layer (weeks 4–5)

**Goal:** decisions in the Workspace drive QQ-0001 from intake to RFQ drafting, and `aos simulate` reaches `closed`
with the fake model. Once dispatched, the job feels agentic (ADR 015):
- the chat follows the job's state;
- the agent reports progress and puts decisions in front of the right person;
- it answers "where are we?" from kernel records;
- it never moves the job itself.

**Exit gate**
- [ ] On the real model: Faisal confirms brief v2 → Noura claims from the queue → confirms 3 suppliers → RFQ drafts
      are produced, the seeded leak is caught (REWORK) and attempt 2 passes `leak_check`.
- [ ] `aos simulate packs/procurement_demo --workflow quick_quote` reaches `closed` with the fake model, scripted people
      and stubbed effects, creating each Task exactly once.
- [ ] Guidebook C01 (duplicate command), C03 (concurrent completion), C09 (stale input), C12 (pinned version) pass.
- [ ] The conversation suite passes in `make gate` on the real model (ADR 015 verification): seven messages in one job,
      "where are we?" after confirmation, the buyer's progress turn with the shortlist card, a topic change and resume,
      an out-of-scope request declined. Must-checks pass in every run; quality checks in at least 80% of runs.

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

### M2-BE-07 Conversation follows the job (ADR 015)
- **Per-message attempts:** `attempts_used` counts per person turn. A new turn starts a fresh attempt budget; retries
  of the same turn use the rest of it. Fake scripts index attempts per job, so keep that index separate.
- **Assist Skill per state:**
  - The Seat's `assist_skill` is the default. A workflow state's `assist` overrides it, and intake keeps
    `request_intake`.
  - `postTurn` admits the current state's assist Skill, for any bound participant, with that participant's visibility.
  - Contracts change in the same story: `Seat.assist_skill`, `WorkflowState.assist`.
- **Where the job is:** `job_snapshot` adds:
  - the workflow's goal (its description);
  - each stage's status;
  - the open decisions with who each waits on;
  - the work in progress (Task template, state, attempt count).

  Every field passes through the reader's visibility.
- **Progress turns:**
  - **When:** on `task.completed.*`, REWORK, EXCEPTION, and a decision opened or resolved.
  - **What:** a Seat turn to the participants the event concerns. The text is the Task's result `summary`,
    projected per reader. A `pending_ref` block is added when the reader must act.
  - **Delivery:** sent as `agent.message.completed`.
- **Tests:**
  - a fourth and a seventh message are admitted;
  - the chat in shortlisting runs `sourcing_assist`, not `request_intake`;
  - the buyer receives the progress turn with the shortlist decision and the requester doesn't;
  - a progress turn never carries a field above the reader's visibility;
  - `job_snapshot` lists the open decision and who it waits on.

### M2-BE-05 Timers, scheduler and demo clock
- Readiness loop, timers with `SKIP LOCKED`, demo clock (`getDemoState`, `advanceClock`) behind `AOS_DEMO=1`.
- **Tests:** a timer fires once with two scheduler loops running; advancing the demo clock fires due timers.
- **Carried from M2-BE-07 (review):** when a workflow Task runs out of attempts because its leases expired, the
  scheduler path (`expire_one_attempt`) sets EXCEPTION and writes `TaskFailed`, but posts no progress turn,
  because it has no `org`. Give the scheduler the kernel's `org` and post the Task's EXCEPTION progress turn
  there too. **Test:** a workflow Task whose leases keep expiring ends in EXCEPTION with one progress turn to its
  `on_behalf_of` person.
- **Carried from M2-BE-02 (review):** if a parallel region's Task ends in EXCEPTION, the region never becomes done,
  so its join never opens (no shortlist card) and nothing lets anyone retry. Decide the way forward here, with the
  readiness loop: for example, a decision for the Task's `on_behalf_of` person to retry the region (new Task, as a
  re-run does), or to continue without it where the workflow allows. **Test:** a region Task in EXCEPTION
  leaves the job with a visible way forward for that person, never stuck silently.

### M2-BE-06 Simulate and Console reads
- `simulatePackVersion` and the `aos simulate` CLI (shared code); `listWorkflows`, `getWorkflowGraph`,
  `listInstances`, `getInstanceTimeline`, user stream `streamUserEvents`.

## Agent

### M2-AG-01 Task graph
- Generic Task graph from the harness spec; `request_intake` as the intake Task with resume-on-input; Task contracts per
  Skill spec (budgets, ceilings, tools).
- **Carried from M2-BE-01 (review):**
  - `aos validate` requires `on_behalf_of` on every task template (states' `tasks`, `on_event`, parallel `start`), so
    a missing one fails at publish, not when a job first reaches that state.
  - `build_task_contract` takes the classification ceiling from the Skill spec, never above the clearance of the
    `on_behalf_of` role. M2-BE-01 uses a placeholder (the Seat's highest grant), harmless only while no Task runs.
  - **Tests:** a template without `on_behalf_of` fails validation; the `supplier_lookup` contract's ceiling is
    `shareable` and `request_intake`'s is `internal`.
- **Carried from M2-BE-06 (review):** `aos simulate` completes Tasks with a stub executor (placeholder artifacts by
  field type, verifiers skipped, only on `-SIM-` jobs) because the Task graphs don't exist yet. Once they do, run
  the simulation's Tasks and intake through the real graphs with `FakeRuntime` and the pack's `happy` scripts, so
  the exit gate's "with the fake model" is literally true; keep the stub only as a fallback for Skills without a
  script. **Test:** the dry run reaches `closed` through FakeRuntime with verifiers running.
- **Carried from M2-BE-06 (review):** `build_task_contract` grants every tool the Skill may request, so the
  `rfq_draft` Task (work type `document_draft`) gets `send_message` because `rfq_authoring` lists it. Grant tools of
  class `committed_effect` only when the template's work type is in `EFFECT_COMMIT_WORK_TYPES` (kinds.py), the same
  rule the Console's `needs_approval` uses. **Test:** the `rfq_draft` contract has no `send_message`; the
  `rfq_send` contract does.
- **Carried from M2-AG-03:** when the context envelope includes `previous_verification`, the task prompt should
  surface those findings to the model (rendering belongs in this story's graph/prompt assembly).
### M2-AG-02 supplier_lookup and rfq_draft
- Skill specs `supplier_lookup.md`, `rfq_authoring.md` (draft part); fake scripts `happy` and `leak` (driven by the
  `seed_budget_leak` switch).
### M2-AG-04 Assist Skills that keep people informed
- **`sourcing_assist`:**
  - the Seat's default assist Skill, with spec `agent/skills/sourcing_assist.md`;
  - read-only tools: `read_artifact`, `browse_categories`, `get_supplier_history`;
  - answers "where are we?" and "what's next?" from `job_snapshot`;
  - points to the open decision card and who it waits on;
  - declines out-of-scope requests in plain words, saying who can help;
  - never says a step happened unless the records show it.
- **Result summaries are written for people:**
  - every Task's `summary` says what was done, what it found and what happens next, in one or two sentences;
  - no field names or JSON;
  - it respects the contract's classification ceiling, since it becomes a progress turn.
- **Fake scripts:** `sourcing_assist.status` and progress summaries in the `happy` scripts.

### M2-AG-03 Verifiers
- `brief_schema`, `sources_cited`, `leak_check` as rule code in `aos/verifiers/` (pack extensions; run by `kernel/verify.py`), each with unit tests from the Skill
  specs, and the REWORK loop with findings in the next envelope.

## Frontend

### M2-FE-01 Lists and live updates
- My jobs with waiting-on-me (WS-MyJobs), Team queue with claim and `ConflictNotice` (WS-Queue), user stream.
- **Carried from M2-BE-03 (review):** replace `requester` / `buyer` on `InstanceSummary` with a generic
  `people` list (`[{role, name}]`) in `openapi.yaml`, regenerate the web types, and use it in My jobs and the queue.
### M2-FE-02 Job page decisions and views
- `DecisionCard` (confirm brief, confirm shortlist), supplier ranking `ArtifactSheet` with selection, brief edit in the
  document view, REWORK notice from `verification.completed`.
- Progress turns in the conversation, with `pending_ref` blocks rendered as the `DecisionCard` in place. The
  conversation stays usable in every state, for every participant.
### M2-FE-03 Console
- Workflow page (Console-Workflows), Instances (Console-Instances), instance timeline (Console-Instance without trace),
  simulate panel on the Packs page, Demo controls clock section.
- **Playwright:** `stop-04` to `stop-07` (drafts) with the fake model.

## Definition of done
- Every M2 operation served and tested; `aos simulate` in CI; the gate demo runs on the real model.
