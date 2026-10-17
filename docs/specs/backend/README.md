# Backend spec: the kernel

FastAPI + psycopg 3 + PostgreSQL, one kernel process plus a scheduler loop, plus the worker process (`agent/`).
The kernel owns lifecycle, permission and progression; nothing else commits state (ADR 001).

- API contract: `../contracts/openapi.yaml`. Event contract: `../contracts/events.md`.
- Tables: M1+ in `backend/migrations/`; reference DDL `ddl/0004`–`0006` (constraint-tested on top of migrations).

## Module layout

```
backend/src/aos/
  api/            routes per tag (auth, registry, seats, workspace, instances, artifacts, decisions, approvals,
                  worker, operate, policy, gateway, audit, emergency, inbound, demo); deps.py; problems.py
  kernel/
    settings.py, org.py, auth.py, audit.py, audit_store.py, registry_store.py      (M0, exist)
    clock.py        kernel time incl. demo offset (M2)
    ids.py          readable ids: job numbers from the workflow's `id_prefix` (QQ-0001 in the example),
                    AP-0009, ae_311, pd_…
    outbox.py       stream heads, outbox rows, NOTIFY; execution_events writer
    seats.py        Seat lifecycle FSM, configuration checks, eval runs (M1)
    admission.py    the eight admission gates + budget reservation (M1)
    contracts.py    TaskContract builder (M1)
    context.py      ContextAssembler and visibility filter (M1)
    tasks.py        Task and attempt state machines, leases, fencing, submit pipeline (M1)
    artifacts.py    versions, hashing, visibility projection (M1)
    conversation.py turns, assist admission (M1)
    workflow.py     FSM interpreter for WorkflowDefinition: guards, effects, regions, joins (M2)
    scheduler.py    readiness, lease expiry, timers, reconciler loop (M2, M3)
    participants.py binding at creation / by claim / by rule (M2)
    policy.py       evaluation order, decision log, replay (M3)
    approvals.py    chains, binding, segregation, expiry, voiding (M3)
    verify.py       runs the Verifiers a Skill names; loads each `implementation:` (M2–M3)
    emergency.py    kill switches, pause (M4)
  gateway/
    broker.py       (M0, exists) 60-second scoped JWTs
    gateway.py      tool calls and action executions through MCP clients (M1 reads, M3 effects)
    reconcile.py    unknown outcomes → find_* by reference (M3)
  # pack extensions: code a pack points to by `implementation:`; may be domain-specific
  connectors/       mock ERP and mail MCP servers (M0, exist)
  verifiers/        rule verifiers: brief_schema, sources_cited, leak_check, recipient_check, payload_match,
                    score_recompute (most are generic; score_recompute is procurement-only)
  tools/            deterministic builtin tools: price_calculator, leak_check_diff
  worker/           see ../agent/harness.md
  sse.py            SSE hub: LISTEN aos_outbox, per-connection cursor, visibility re-check
```

Everything outside `connectors/`, `verifiers/` and `tools/` is **pack-neutral**. It never names a pack, workflow,
Skill, document type or domain word; those arrive as pack data. `tests/test_pack_neutral.py` enforces this.

## Request handling rules

1. **One transaction per command.** State change, Decision Record, execution event, outbox rows and (when listed in
   `events.md`) the audit record commit together. External calls never happen inside it.
2. **Optimistic versions.** Every person-facing write carries `expected_version`; update with
   `WHERE id = $1 AND version = $2` and raise 409 `stale_version` with `current_version` when no row matched.
3. **Idempotency.** Creating calls accept `Idempotency-Key`; store `(org, actor, key) → response` (instances store it on
   the row). A repeat returns the stored response.
4. **Problems.** Raise `KernelProblem(code, status, title, detail, **extra)`; one exception handler renders
   `application/problem+json` and stamps `trace_id`.
5. **Visibility.** Artifact reads go through `artifacts.project(version, viewer_roles)`, which drops fields per the
   artifact type's `visibility` and `classification`; `hidden_fields` lists the dropped names. The same function feeds
   the ContextAssembler, so the agent and the person see the same projection.

## Seat lifecycle (M1)

```
DRAFT --configure (6 checks pass)--> CONFIGURED --evals pass--> TESTING --approve (risk)--> APPROVED
APPROVED --activate (owner, not configurer)--> ACTIVE <--pause/resume (owner)--> PAUSED
ACTIVE|PAUSED --kill switch--> KILLED --lift (second person + review)--> PAUSED
any --retire--> RETIRED
```

Configuration checks (all must pass): pack version published · every Skill's work types allowed by the role ·
every resource in the authority profile exists · every committed-effect tool has a policy rule and `reconcile_with` ·
model alias resolves · placement team exists and owner is a person in it.

## Admission (M1): the eight gates

Checked in order for every new attempt (assist turn, Task attempt, resume). The first failure refuses with its code
and is recorded as a policy decision; nothing is reserved.

Until M3 (`gov.policy_decisions`, M3-BE-01), admission refusals are recorded as **`gov.decision_records`**
(`event=admission.denied`, `value` = refusal code) plus audit `admission.denied`, and returned as
`application/problem+json` with `decision_id`. No instance, task, attempt, turn or budget row is written on refusal.

| # | Gate | Refusal code |
| --- | --- | --- |
| 1 | No active kill switch on the instance, its workflow or its Seat | `kill_switch_active` |
| 2 | Seat version is ACTIVE (not PAUSED, KILLED, RETIRED) | `seat_not_active` |
| 3 | Instance pinned to a published pack version | `conflict` |
| 4 | Caller may act: for `startInstance`, org roles intersect a start participant's `org_roles`; on an existing job, caller is a bound participant (or the Task is kernel-scheduled) | `not_permitted` |
| 5 | Task has no live attempt and attempts remain | `conflict` |
| 6 | Inputs current: `dependency_versions` match the instance | `stale_version` |
| 7 | Budget: attempt reservation fits the Seat's remaining daily limit | `budget_exhausted` |
| 8 | Concurrency: at most 4 live attempts per Seat in the POC | `unavailable` (retry later) |

Admission writes the attempt row (`ADMITTED`, new fencing token = `tasks.fencing_token + 1`) and the reservation in
`gov.budget_ledger` in one transaction.

## Tasks and attempts (M1)

```
Task:    CREATED → READY → RUNNING → VERIFYING → COMPLETED
         RUNNING → WAITING_INPUT | WAITING_APPROVAL → READY (when answered/approved) → RUNNING (new attempt)
         VERIFYING → READY (REWORK; new attempt with findings) | EXCEPTION (FAIL, or retries spent)
         any → CANCELLED (kill switch, instance closed)
Attempt: ADMITTED → CLAIMED (lease) → ENDED{submitted | waiting_approval | needs_input | fenced | failed | expired | cancelled}
```

- **Claim** (`claimAttempt`): `SELECT … FROM work.attempts WHERE state='ADMITTED' … FOR UPDATE SKIP LOCKED LIMIT 1`;
  set `CLAIMED`, `worker_id`, `lease_expires_at = now() + 90 s`.
- **Every worker call** checks `X-AOS-Fencing-Token = tasks.fencing_token` and attempt `CLAIMED`; else 409 `fenced`
  and an `AttemptFenced` event.
- **Heartbeat** extends the lease; returns `cancel_requested` when a kill switch or cancel is pending.
- **Lease expiry** (scheduler, every 5 s): expired `CLAIMED` attempts → `ENDED/expired`, bump the Task's fencing token,
  settle the budget at the reservation, and if attempts remain admit a new one (the Task stays RUNNING).
- **Submit pipeline**: (1) validate `AgentResult` schema and each output against its artifact type → 422 / REWORK;
  (2) freshness: `input_versions` equal current `dependency_versions` else verdict STALE and a new attempt;
  (3) run the Task's verifier on the output versions → PASS (Task COMPLETED, raise `task.completed.<template>`),
  REWORK (new attempt; findings go into the next envelope), FAIL (EXCEPTION). Settle the budget with actual usage.

## Workflow interpreter (M2)

- The instance's `WorkflowDefinition` comes from its pinned pack version, never the latest.
- Entering a state creates its Tasks (one per template; `on_event` templates are created per event).
- An event (`decision.*`, `task.completed.*`, `timer.*`, `event.*`) finds transitions `from` the current state whose
  `on` matches; `by` must equal the deciding participant's role; the guard is evaluated with the M0 expression
  evaluator over `attr.*`; the first passing transition fires. No match → the event is recorded and ignored.
- Effects run in the same transaction: `start_timer`, `lock` (artifact status `locked`), `handover` (notification +
  turn for the requester), `outcome_record`, `cancel_timers`.
- **Parallel region**: on its start event create the region and its Task; at `join_at`, a transition out is allowed
  only when every required region is `done` and its join guard holds (`same(brief_version)` compares the region's
  `started_with` to the current attributes). This is the all-required join (ADR 002).
- **Readiness**: a Task is READY when its state is current and its inputs exist. Dispatch identity is
  `(task_id, attempts_used)`, so two concurrent completions admit one attempt (guidebook C03).
- **Timers**: the scheduler claims due timers with `FOR UPDATE SKIP LOCKED`, flips them to `fired` and raises the event
  in the same transaction; each fires once. `demo_after` applies when `AOS_DEMO=1`.
- **Attributes** are written only by the kernel, from records, never by the agent:

  | Attribute | Set when |
  | --- | --- |
  | `brief_version` | the requester confirms a brief version (`decision.brief_confirmed`) |
  | `shortlist_count` | the buyer confirms a shortlist (length of `selection`) |
  | `invited_count` | `rfq_send` completes (number of send receipts) |
  | `quote_count` | each `quote_triage` Task completes |
  | `po_amount` | a `po_payload` version is saved |

- **Domain events the kernel raises** (declared in the workflow's `events`): `event.intent_identified` when the first
  brief version with a `category` is saved; `event.all_quotes_received` when `quote_count == invited_count`.
- **Decisions the kernel opens** (pending items): confirm the brief (requester, when `request_intake` completes),
  confirm the shortlist (buyer, when bound and the discovery region is done), select the supplier (buyer, when
  `quote_comparison` completes).

## Policy engine (M3)

Inputs: action (`resource.action`), subject (Seat or person, with participant role), instance attributes, artifact
verification results. Evaluation order, recorded step by step in `gov.policy_decisions.evaluation`:

1. **NEVER** rules matching subject and action → NEVER.
2. **Specific** gate rules for this workflow and action whose conditions hold → their effect.
3. **Restrictive** authority-profile grants for the Seat → their effect.
4. **Conditions**: rules whose conditions fail don't apply.
5. **Default deny** when nothing applied.
6. **Tighten**: the result is the strictest of the effects that applied (NEVER > DENY > REQUIRE_APPROVAL > ALLOW).

Every decision stores the attribute snapshot and its hash; replay re-evaluates the same snapshot against the same
policy version and must return the same result.

## Approvals (M3)

- Created only by `request_action` returning REQUIRE_APPROVAL. Steps come from the rule's `chain`; a step whose
  `when` is false is `skipped`. Approver role resolves to a person at step open.
- `payload_hash = sha256(canonical({tool, args, artifact_refs with content hashes, policy_version}))`.
- Approve requires: caller is the step's approver; caller didn't request it (`not_requester`); caller decided no
  other step (`distinct_approvers`, also a unique index); `payload_hash` matches; not expired.
- A new version of any bound artifact voids open approvals bound to it (`approval.resolved` voided) and returns the
  Task to READY; the agent re-requests on its next attempt.
- When the last step approves, the Task becomes READY with `resume = {checkpoint_id, signal: {approval_id}}`.

## Action executions and reconciliation (M3)

```
INTENDED (row + idempotency key committed) → EXECUTING (broker token minted, MCP call)
EXECUTING → SUCCEEDED (receipt) | FAILED (connector refused; not retried) | UNKNOWN (timeout, connection lost)
UNKNOWN → reconcile with reconcile_with tool by reference → RECONCILED (found) | retry with the same key (not found) | exception
```

- Execution happens on the resumed attempt's `request_action`, after policy is re-checked against current state.
- `create_po` reference is `AOS-<instance>-PO1`; `send_message` keys are `<instance>:rfq_send:<supplier_id>`.
- The reconciler runs on the scheduler loop for rows in EXECUTING or UNKNOWN older than 30 s; it never asks the agent.
- After SUCCEEDED or RECONCILED, the Task's verifier (`recipient_check`, `payload_match`) reads the remote record.

## SSE hub

`GET …/events` opens a stream: authenticate, resolve the viewer's roles on the instance, read outbox rows after the
cursor (or send `snapshot.required`), then `LISTEN aos_outbox` and push new rows whose audience includes the viewer.
Heartbeat comment every 15 s. Deltas (`agent.message.delta`) are not stored in the outbox; the hub relays them from
an in-memory channel keyed by turn and drops them if the viewer is not the turn's addressee.

## Testing expectations

Each milestone spec lists its acceptance tests. Kernel tests run against a scratch Postgres (`tests/_pg.py`), use the
fake model and the in-process MCP mocks, and never call a real model. Failure-path tests use the connectors' fault
switches and a `FrozenClock`.
