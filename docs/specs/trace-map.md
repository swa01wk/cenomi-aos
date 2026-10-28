# Trace map: design → frontend → backend → agent

Every board on the design canvas (*AOS App Screens*, copies in `design/boards/`) traced to the route that renders it,
the components it is built from, the API operations and events it uses (`contracts/openapi.yaml`,
`contracts/events.md`), the kernel records behind it (`backend/README.md`, tables in `backend/ddl/`) and the agent parts involved
(`agent/`). Milestone = when the screen first works end to end.

Rules this map relies on:
- **The screens are platform screens; QQ-0001 is example data.** Workflow and stage names, document tabs and their
  layout, field labels and visibility come from the pack through the API (`WorkflowDefinition`, `ArtifactType.view`,
  projected fields). Pack-specific names below (`rfq_authoring`, `price_calculator`, "RFQ") belong to the example
  run, not to the screen. The screen names to use in code and tickets are in `design/README.md`.
- The **job page is one route** (`/workspace/jobs/:id`). Stops 5–14 are states of that page, not separate pages.
- Screens never compute permissions. A disabled button or a missing column comes from the snapshot the kernel sent.
- Every number on a Console screen links to the records behind it.

## Index

| Board | Route | Persona | Milestone |
| --- | --- | --- | --- |
| Sign-in | `/` | anyone | M0 |
| Console-Org | `/console/org` | Console roles | M0 |
| Console-Packs (stop 1) | `/console/packs`, `/console/versions/:id` | Platform admin, Risk, owner | M0 view, M1 publish, M2 simulate |
| Console-Seats | `/console/seats` | Console roles | M1 |
| Console-Activation (stop 2) | `/console/seats/:seat` | Platform admin | M1 |
| Console-Seat (stop 3) | `/console/seats/:seat` | Seat owner | M1; pause and kill M4 |
| WS-MyJobs | `/workspace` | any Workspace person | M1 list, M2 waiting-on-me and live updates |
| WS-New (stop 4) | `/workspace/new` | requester | M1 |
| Main (stop 5) | `/workspace/jobs/:id` | requester | M1 chat, M2 decision and parallel lookup |
| WS-Queue (Team queue) | `/workspace/queue` | member of the queue's team | M2 |
| WS-Shortlist (stop 6) | `/workspace/jobs/:id` | buyer | M2 |
| WS-RFQ-Approval (stop 7) | `/workspace/jobs/:id` | buyer | M2 drafts and REWORK, M3 approval |
| WS-Quotes (stop 8) | `/workspace/jobs/:id` | buyer | M3 |
| WS-Faisal-Refused (stop 9) | `/workspace/jobs/:id` | requester | M3 (M1 for the refusal block itself) |
| Console-Policy (stop 10) | `/console/policies`, `/console/policies/decisions/:id` | Risk | M3 |
| WS-Comparison (stop 11) | `/workspace/jobs/:id` | buyer | M3 |
| WS-PO-Approval (stop 12) | `/workspace/jobs/:id` | procurement approver | M3 |
| Console-Gateway (stop 13) | `/console/actions/:id` | Platform admin | M3 |
| WS-Closed (stop 14) | `/workspace/jobs/:id` | requester | M3 |
| WS-Inbox | `/workspace/inbox` | any Workspace person | M3 |
| Console-Workflows | `/console/workflows/:name` | process owner | M2 |
| Console-Instances | `/console/instances` | Console roles | M2 |
| Console-Instance (stop 15) | `/console/instances/:id` | process owner | M2 timeline, M4 trace |
| Console-Approvals | `/console/approvals` | Console roles | M3 |
| Console-Connectors | `/console/connectors` | Platform admin | M3 |
| Console-Observability | `/console/observability` | Seat owner | M4 |
| Console-Audit (stop 16) | `/console/audit` | Risk | M0 log, M4 explain |
| Console-Emergency (stop 17) | `/console/emergency` | Seat owner | M4 |
| Demo-Controls | `/demo` | demo operator | M2 clock, M3 replies and faults |
| States | all screens | — | M1 to M3 |
| Components | all screens | — | M1 |
| Scenario-Index | not built; the canvas start page | — | — |

---

## Shared

### Sign-in
- **Components:** `PersonaCard` grid in two groups (Workspace, Console); `ErrorBanner` if the kernel is down.
- **API:** `listPersonas`, `startSession` → token in `sessionStorage`; then `getMe` on reload.
- **Kernel:** `org.people`, `org.role_mappings`; audit `session.started`.
- **Routing after sign-in:** Workspace people → `/workspace`; Console people → the first Console page their role
  allows (`platform_admin` → packs, `risk` → policies, owners → seats).
- **Exists in M0** with hash routes; M1 moves it to the router and adds the role landing rule.

### States (catalogue) · Components (sheet)
Not routes. Build their components first in M1 (`web/src/components/`) and use them on every screen:
`Skeleton`, `EmptyState`, `ErrorBanner`, `RefusalNotice`, `ConflictNotice`, `FieldError`, `ConnectionBanner`,
`ToolActivity`, `StreamingText`, `TaskStatus`, `SeatNotice`, `ExceptionCard`, `SessionDialog`, `Button`, `StatusPill`,
`StageStepper`, `AgentMessage`, `PersonMessage`, `SourceChip`, `ArtifactChip`, `DecisionCard`, `ApprovalCard`,
`ArtifactSheet`, `TimelineItem`. Problem `code` → component mapping is in `frontend/README.md`.

---

## Console

### Console-Org
- **Components:** `PageHeader`, department `Panel` cards, `DataTable` (people), participant-rules panel.
- **API:** `getOrg`. Participant rules read from the published workflow (`getWorkflowGraph`, M2; static text in M0).
- **Kernel:** `org.*`. **Agent:** none.

### Console-Packs · stop 1
- **Components:** `StatTile` row (kind counts), validate `CheckList`, simulate `StageStepper` path, publish request
  `ChainSteps`, version `DataTable`, definition list + JSON view (M0 `VersionPage`).
- **API:** `listPacks`, `validatePack`, `syncPack`, `getPackVersion`, `getDefinition` (M0); `requestPublish`,
  `listPublishRequests`, `approvePublishPart`, `rejectPublish` (M1); `simulatePackVersion` (M2).
- **Events:** none on this page; it refetches after each action.
- **Kernel:** `registry.packs`, `registry.pack_versions`, `registry.definitions` (immutable once published),
  `registry.publish_requests`; audit `pack.validated`, `pack.publish_requested`, `pack.published`.
- **Agent:** none. `aos simulate` uses the fake model through the same worker protocol (M2).
- **Rule:** the requester of a publish can't approve any part of it; Risk approves policies, the owner approves Seats and
  workflows.

### Console-Seats
- **Components:** `DataTable` with `StatusPill` (lifecycle), availability text, `MeterBar` (spend vs daily limit),
  lifecycle legend, limits `StatTile`s.
- **API:** `listSeats`. **Kernel:** `registry.seats`, `work.attempts` (running count), `gov.budget_ledger`.

### Console-Activation · stop 2 / Console-Seat · stop 3
- **Components:** `LifecycleSteps`, `RefusalNotice` (segregation of duties), eval run cards, activation `Panel`,
  configuration `CheckList`, Skills list, 7-day stats; `KillSwitchPanel` entry (M4).
- **API:** `getSeat`, `configureSeat`, `runSeatEvals`, `approveSeat`, `activateSeat` (M1); `pauseSeat`,
  `resumeSeat`, `activateKillSwitch` (M4).
- **Events:** `seat.state_changed` (user stream) updates the Workspace digital-worker card.
- **Kernel:** `registry.seats`, `registry.seat_events`, `registry.seat_checks`, `registry.eval_runs`,
  `gov.decision_records` (activation); audit `seat.activate.denied`, `seat.activated`.
- **Agent:** eval suites run Skills through the worker with the fake model (M1) and the real model (M4).
  `refusals` asserts NEVER and that `unit_price`, `total` and `po_amount` appear only in envelope `redactions`.

### Console-Workflows
- **Components:** state cards in a grid, parallel-branch and timer panels, participants, attributes, stage targets.
- **API:** `listWorkflows`, `getWorkflowGraph`. **Kernel:** `registry.definitions` (WorkflowDefinition, Pack
  observability). **Agent:** shows which Skill and verifier each Task uses.

### Console-Instances
- **Components:** `StatTile` row (each a filter link), search form, `DataTable` with `StatusPill` and `MeterBar`
  (time vs stage target).
- **API:** `listInstances` (with `summary`). **Events:** none (manual refresh in the POC).
- **Kernel:** `work.instances`, `work.pending_items`, `work.tasks`, `work.timers` (to compute "waiting on").

### Console-Instance · stop 15
- **Components:** time-in-state bars, `TimelineItem` list, `TraceWaterfall` for one Task.
- **API:** `getInstanceTimeline` (M2), `getTaskTrace` (M4), `replayAttempt` (M5).
- **Kernel:** `work.instance_transitions`, `gov.decision_records`, `gov.policy_decisions`, `work.action_executions`,
  `work.timers`, `evidence.execution_events`; spans via OpenTelemetry (`work.attempts.trace_id`).
- **Agent:** spans carry `aos.correlation_id`, `aos.task.id`, `aos.attempt.id`, `gen_ai.request.model`.

### Console-Policy · stop 10
- **Components:** decisions `DataTable`, `PolicyEvalTrace` (evaluation order), attribute snapshot, replay button.
- **API:** `listPolicyDecisions`, `getPolicyDecision`, `replayPolicyDecision`.
- **Kernel:** `gov.policy_decisions` (with `attributes_snapshot` and `policy_version`).
- **Agent:** the refusal came from an assist turn's `read_artifact` tool call (`ToolDenied`).

### Console-Approvals
- **Components:** `Tabs`, open approval `Panel` with `ChainSteps`, recently decided `DataTable`.
- **API:** `listApprovals`, `remindApprover`, `listPublishRequests`. Approving happens only in the Workspace.
- **Kernel:** `gov.approvals`, `gov.approval_steps`, `registry.publish_requests`, `registry.seat_events`.

### Console-Connectors
- **Components:** connector `Panel`s with tool tables (committed effects highlighted), recent actions `DataTable`.
- **API:** `listConnectors`, `listActions`. **Kernel:** `registry.definitions` (ToolProvider), `work.action_executions`.

### Console-Gateway · stop 13
- **Components:** executions list, `ExecutionSteps` (INTENDED → EXECUTING → UNKNOWN → RECONCILED), receipt, verification.
- **API:** `getAction`, `listActions`.
- **Kernel:** `work.action_executions` (state history, idempotency key, args hash), broker token log in
  `evidence.execution_events` (`ToolAuthorized`).
- **Agent:** `create_po` came from `request_action` in attempt 2 of `po_create`; on UNKNOWN the kernel reconciles with
  `find_po` itself, not the agent.

### Console-Observability
- **Components:** `StatTile`s with thresholds, `BarChart` (attempts per day, stacked accepted/reworked), target bars,
  approver table.
- **API:** `getDashboard` × 3. **Kernel:** aggregates over `work.attempts`, `gov.policy_decisions`,
  `work.instance_transitions`, `gov.approvals`, `gov.budget_ledger`. Thresholds from the pack's `observability`.

### Console-Audit · stop 16
- **Components:** search, explain walk-back `TimelineItem`s, `HashChainBadge`, versions in force, audit `DataTable`.
- **API:** `listAudit`, `verifyAudit` (M0); `explainOutcome` (M4).
- **Kernel:** `evidence.audit_events`, `evidence.audit_heads`, `evidence.outcome_records`.

### Console-Emergency · stop 17
- **Components:** scope picker, `KillSwitchPanel` (danger), recent controls list.
- **API:** `activateKillSwitch`, `listKillSwitches`, `liftKillSwitch`, `pauseSeat`.
- **Events:** `kill_switch.changed` → `SeatNotice` on every affected Workspace screen.
- **Kernel:** `gov.kill_switches`; admission gate 1; attempts fenced; broker revocation list.
- **Agent:** a fenced worker gets 409 `fenced` on its next heartbeat and stops without effects.

---

## Workspace

### WS-MyJobs
- **Components:** `WorkspaceRail`, filter `Tabs`, `JobCard` list (stage pill, "waiting on you" line).
- **API:** `listMyInstances`, `listDigitalWorkers` (rail). **Events:** user stream (`streamUserEvents`):
  `instance.created`, `instance.state_changed`, `pending.created`, `pending.resolved`.
- **Kernel:** `work.instances`, `work.participants`, `work.pending_items`.

### WS-New · stop 4
- **Components:** `WorkflowPicker` (only startable workflows), need `Composer` with attachment, "How it works" panel.
- **API:** `listDigitalWorkers`, `startInstance` (Idempotency-Key = client UUID) → navigate to `/workspace/jobs/:id`.
- **Kernel:** admission (Seat ACTIVE, no kill switch, start role, budget); `work.instances` pinned to
  `quick_quote@1`; `work.participants` (requester at creation); `work.tasks` (assist); `work.turns`.
- **Agent:** first assist attempt for `request_intake`.

### Job page `/workspace/jobs/:id` (stops 5–14)
Layout from the boards: rail · conversation (header with `StageStepper`, turns, `Composer`) · work panel (`Tabs`, one
per artifact view). The page loads `getInstance`, opens `streamInstanceEvents` from the snapshot's cursor and renders
pending items inline in the conversation. The stepper shows `snapshot.stages`. The work panel gets one tab per
artifact, rendered by the view component for its `ArtifactType.view.type`. The table below lists the example run's
states of this one page.

| Stop | Board | What changes on the page | API added | Events | Kernel | Agent |
| --- | --- | --- | --- | --- | --- | --- |
| 5 | Main | Agent interviews; brief versions in a document panel; supplier ranking tab appears; `DecisionCard` confirm brief | `postTurn`, `getArtifactVersion`, `createArtifactVersion` (edit in panel, M2), `decidePending` (M2) | `agent.message.*`, `agent.tool.activity`, `artifact.version_created`, `pending.created` | `work.turns`, `work.artifact_versions` (brief v1, v2), `work.pending_items`, `work.regions` (discovery) | `request_intake` (assist + Task), `supplier_lookup` in the parallel branch |
| 6 | WS-Shortlist | Claimed by Noura; ranking `ArtifactSheet` with checkboxes; "why" answered from saved sources; confirm shortlist (≥3) | `claimInstance`, `decidePending` | `participant.bound`, `instance.state_changed` | `work.participants` (by claim), `gov.decision_records`, join guard `same(brief_version)` | assist turn answers from `sources`, no new tool calls |
| 7 | WS-RFQ-Approval | Leak REWORK notice; three RFQ tabs in `MessageComposerView`; Noura edits one (v3); `ApprovalCard` send ×3 | `createArtifactVersion`, `getApproval`, `approveStep`, `rejectStep` | `verification.completed` (REWORK), `approval.requested` | `gov.policy_decisions` (REQUIRE_APPROVAL), `gov.approvals` bound to 3 digests | `rfq_authoring`: `leak_check` REWORK → attempt 2; `request_action(send_message)` → `interrupt()` |
| 8 | WS-Quotes | Sends confirmed; quote `TrackerView`; vendor replies arrive | — | `action.state_changed`, `timer.fired` later, `artifact.version_created` (quote) | `work.action_executions` ×3, `work.timers` (quote_deadline), `work.inbound_messages` | resume on attempt 2; `recipient_check`; one `quote_triage` Task per reply |
| 9 | WS-Faisal-Refused | Faisal asks for prices → `RefusalNotice` block; tracker without price columns | `postTurn` | `agent.message.completed` with a `refusal` block | `gov.policy_decisions` (NEVER) | assist turn; envelope built without quote values |
| 11 | WS-Comparison | Deadline fires; comparison `ArtifactSheet` (verified); `DecisionCard` select supplier; comparison locks | `decidePending` | `timer.fired`, `verification.completed` (PASS), `pending.created` | `work.timers`, `gov.decision_records`, artifact status `locked` | `quote_comparison` with `price_calculator`; `score_recompute` |
| 12 | WS-PO-Approval | PO `RecordPreview`; two-step `ApprovalCard` with chain; Khalid approves step 2 | `getApproval`, `approveStep` | `approval.step_decided`, `approval.resolved` | `gov.approval_steps`, segregation check | `po_create` attempt 1 interrupted; attempt 2 resumes after approval |
| 13 | (Console-Gateway) | — | — | `action.state_changed` UNKNOWN → RECONCILED | `work.action_executions` | `payload_match` PASS |
| 14 | WS-Closed | Handover card; Outcome tab; acknowledge | `markNoticeRead` (the handover is a notice) | `instance.state_changed` → closed | `evidence.outcome_records`, timers cancelled | none |

### WS-Queue
- **Components:** `QueueCard` list with a comment, Approve and Reject, `ConflictNotice` for a lost claim.
- **API:** `listQueue` (each item includes `claim_role`), `claimInstance` with `decision` `approve` or `reject` and `note`. Approve binds the role and posts the comment. Reject requires a comment, closes the job, and posts the comment. 409 `already_claimed` shows the notice and removes the card.
- **Kernel:** `work.participants` with a unique (instance, role) constraint; queue membership from `org.people.team`.

### WS-Inbox
- **Components:** `InboxItem` (approval, decision) linking to the job at its card; notices list.
- **API:** `getInbox`, `markNoticeRead`. **Events:** user stream. **Kernel:** `work.pending_items`, `gov.approvals`,
  `work.notifications`.

---

## Demo

### Demo-Controls
- **Components:** clock `Panel` with timers table, fault switch list, vendor simulator (thread list + reply form).
- **API:** `getDemoState`, `advanceClock` (M2), `simulateVendorReply`, `setFaults` (M3). Only when `AOS_DEMO=1`.
- **Kernel:** demo clock offset in `work.demo_clock`; every action audited as actor `demo`.
- **Agent:** `seed_budget_leak` switches the fake model's first RFQ draft script; the real model never sees the budget
  (RFQ contracts use a shareable ceiling).
