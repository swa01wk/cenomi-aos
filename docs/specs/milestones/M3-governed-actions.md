# M3 · Governed actions (weeks 6–7)

**Goal:** every external effect is approved, executed once and verified, and QQ-0001 reaches `closed` live.

**Exit gate**
- [ ] QQ-0001 runs from New job to `closed` on the real model with every send and the PO approved by the right people.
- [ ] With the ERP `timeout_after_commit` switch on, exactly one PO exists and the action shows UNKNOWN → RECONCILED.
- [ ] Faisal asking for prices gets a refusal; Risk replays the decision and gets NEVER again.
- [ ] Guidebook C02, C04, C05 (approval bound to an old payload), C06 (injected supplier text), C08, C11 pass.
- [ ] `AOS_EVAL_STRICT=1`: the `refusals` and `dry_run` suites pass in full before activation.
- [ ] The conversation suite grows and still passes on the real model:
      - progress turns for approvals requested and decided, RFQs sent, each quote arriving ("2 of 3 quotes in") and the
        PO created;
      - "where are we?" while awaiting quotes names the deadline and who has replied;
      - no turn shows a price to Faisal.

**Walkthrough stops made real:** 7 (approval), 8, 9, 10, 11, 12, 13, 14.

---

## Backend

### M3-BE-01 Policy engine
- Apply `ddl/0005_m3_governed_actions.sql`. `kernel/policy.py` with the six-step evaluation order, attribute
  providers (participant role, instance attributes, artifact verification), decision log, replay.
- Replaces M1's allow-list check in `callTool`; assist turns that read restricted artifacts for a requester return a
  `refusal` block from the NEVER decision.
- Operations: `listPolicyDecisions`, `getPolicyDecision`, `replayPolicyDecision`.
- **Tests:** each rule in `quick_quote_gates` and `sourcing_supervised`; replay equals the original; default deny.

### M3-BE-02 Approvals
- `kernel/approvals.py` per the backend spec: chains with `when`, payload hash binding, `not_requester`,
  `distinct_approvers`, expiry, voiding on a new artifact version.
- Operations: `getApproval`, `approveStep`, `rejectStep`, `listApprovals`, `remindApprover`, `getInbox`,
  `markNoticeRead`.
- **Tests:** C05 — edit after approval voids it and the effect never runs on the old payload; the requester can't approve;
  one person can't approve two steps; an expired approval can't be approved.
- **Carried from M2-BE-03 (review):** `resolve_participant` binds a `by_rule` role (e.g. `team_owner(…)`) to whoever
  the rule names, even if that person already holds another role on the job, for example a team owner who raised
  the job as requester. Claims enforce one person, one role; rule binding doesn't. Decide the rule here: refuse
  the binding, or escalate to the next person up. Then make sure segregation (`not_requester`,
  `distinct_approvers`) holds when the approver came from a rule. **Test:** a job raised by the rule's team owner
  never lets them approve their own job's step.

### M3-BE-03 Actions, gateway effects and reconciliation
- `requestAction`, `checkpointAttempt`; action executions with idempotency keys; gateway committed calls; reconciler
  loop; `listConnectors`, `listActions`, `getAction`.
- **Tests:** C04 — worker dies after the ERP write: the reconciler finds the PO before any retry; a send timeout is
  reconciled with `find_message`; the same key twice returns the first receipt. C14 (adapted from deploy digests to
  payloads): the gateway executes only the payload whose hash passed the verifier and the approval; a payload with a
  different hash is blocked until it is verified and approved again.

### M3-BE-04 Inbound mail and quotes
- `receiveInbound` (HMAC with `connectors/inbound.py`, dedupe by message id), mock_mail posting to it, one
  `quote_triage` Task per reply, `quote_count`/`all_quotes_received` rules; demo `simulateVendorReply`, `setFaults`.

### M3-BE-06 Progress for governed actions (ADR 015)
- Progress turns for `approval.requested` (to the approver, with the `ApprovalCard`), approval decided, each send
  completed, each quote received with the running count, the PO created, and the handover. Same mechanism as
  M2-BE-07; visibility per reader, so quote values never reach the requester.
- **Tests:** the approver gets the card in the conversation; Faisal's quote-count turn carries no price; a voided
  approval posts a turn saying why.

### M3-BE-05 Verifiers and budgets
- `recipient_check`, `score_recompute`, `payload_match`; full budget enforcement on actions (`budget.actions`) and
  C11 — a budget exhausted mid-loop stops safely with work kept.

## Agent

### M3-AG-01 Interrupt and resume
- `request_action` node, `interrupt()`, `/checkpoint`, resume with `Command(resume=…)` on a new attempt, the
  no-model fast path after a voided approval.
### M3-AG-02 rfq_send, quote_triage, quote_comparison, po_create
- Per the Skill specs; `price_calculator` built-in tool; fake scripts `happy` and `injection`.
- **Tests:** C06 — the injection script makes no out-of-contract call; C08 — a request for a tool not in the contract is
  denied and doesn't raise any budget.
- **Carried from M2-BE-04 (review):** the `comparison` artifact type keys its rows by `supplier` (a name), because it
  has no id field, so *Select the supplier* matches selections by name. Add a `supplier_id` field to `comparison`,
  set `row_key: supplier_id`, and have `quote_comparison` fill it from the quotes. **Test:** two suppliers with
  similar names; selecting one by `supplier_id` records exactly that supplier.

## Frontend

### M3-FE-01 Approvals in the Workspace
- `ApprovalCard` with chain and hash, `MessageComposerView` with per-supplier tabs and edit, `RecordPreview`, Inbox
  (WS-Inbox) and the bell, `RefusalNotice` in conversation (stop 9), `TrackerView`, handover (stop 14).
### M3-FE-02 Console governance
- Approvals (Console-Approvals), Policies with evaluation trace and replay (Console-Policy), Connectors
  (Console-Connectors), action detail (Console-Gateway), Demo controls vendor replies and fault switches.
- **Playwright:** `stop-07` to `stop-14` with the fake model.

## Definition of done
- Every M3 operation served and tested; the full QQ-0001 runs live; the fault and injection tests are in CI.
