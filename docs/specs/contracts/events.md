# Events

The kernel keeps two kinds of event. Both are written in the **same database transaction** as the state change they
describe (transactional outbox, guidebook §3). A relay publishes them afterwards; consumers handle at-least-once
delivery and dedupe on `(run_id, aggregate_seq)` or the stream cursor.

| | ExecutionEvent | UiEvent |
| --- | --- | --- |
| Schema | `schemas/execution-event.schema.json` | `schemas/ui-event.schema.json` |
| Purpose | Evidence: what happened, under which contract and model | Projection: what one viewer may see change |
| Stored | `evidence.execution_events`, kept | `evidence.outbox`, kept 7 days for resume |
| Audience | Console (timeline, trace, audit explain) | Workspace and Console screens over SSE |
| Redaction | Payloads by reference; `redacted_summary` only | Filtered per viewer by participant role and artifact visibility |

The audit hash chain (`evidence.audit_events`, ADR 008) is a third record. It holds a smaller set of authority
events (session started, pack synced, Seat state changes, decisions, approvals, kill switches) and links them by hash.

## ExecutionEvent types

Names follow reference architecture v1.2 §29. The worker may **propose** only the four marked W. The kernel stamps
`event_id`, `aggregate_seq`, `correlation_id` and `actor`, and rejects proposed events from a fenced attempt.

| Type | Emitted when | By | Key attributes |
| --- | --- | --- | --- |
| RunCreated | An instance is started | kernel | `workflow_id`, `graph_revision` |
| TaskDispatched | An attempt is admitted and claimed | kernel | `attempt_id`, `n`, `fencing_token` |
| AgentStarted W | The graph starts running | worker | `adapter`, `graph` |
| ModelInvoked W | One model call ends | worker | `provider`, `model`, `tokens_in`, `tokens_out`, `cost_usd`, `prompt_version` |
| ToolRequested W | The graph asks for a tool | worker | `tool`, `args_sha256` |
| ToolAuthorized | Policy allows a tool call | kernel | `tool`, `decision_id` |
| ToolDenied | Policy refuses a tool call | kernel | `tool`, `decision_id`, `rule` |
| ToolCompleted | The gateway finishes a tool call (success, failure or discarded) | kernel | `tool`, `receipt_ref`, `duration_ms`, `outcome` (`success`, `failed`, `discarded`) |
| ArtifactProduced | A draft or person version is saved | kernel | `artifact_refs` |
| ApprovalRequested | request_action returns REQUIRE_APPROVAL | kernel | `approval_id`, `payload_hash` |
| CheckpointSaved W | The graph interrupts for approval or input | worker | `checkpoint_id`, `waiting_for` |
| TaskResultProposed | `submit` is received | kernel | `status`, `output_artifact_refs` |
| TaskAccepted | All three checks pass | kernel | `verifier`, `verdict=PASS` |
| TaskRejected | Schema, freshness or verifier fails | kernel | `stage`, `verdict` (REWORK, FAIL, STALE) |
| TaskFailed | The Task ends in exception or failure | kernel | `failure_category` |
| TaskCancelled | A kill switch or a person cancels | kernel | `reason` |
| AttemptFenced | A late call from a stale attempt is refused | kernel | `fencing_token`, `current_token` |
| BudgetExceeded | An attempt crosses a limit | kernel | `limit`, `used` |
| StateTransitioned | A workflow transition fires | kernel | `from_state`, `to_state`, `event`, `guard`, `decision_id`, `instance_version` |
| WorkflowEventIgnored | An event did not match any transition | kernel | `state`, `event`, `reason` (`no_match`, `wrong_role`, `guard_failed`, `not_running`) |

## UiEvent types

`id` is the SSE cursor. On connect the client sends `Last-Event-ID`; if the kernel no longer has that cursor, or
the viewer's visibility changed, the first message is `snapshot.required` and the client refetches
`GET /instances/{id}` (guidebook C10).

| Type | Stream | Seen by | Drives (component) |
| --- | --- | --- | --- |
| `snapshot.required` | both | everyone | Reload snapshot; `ConnectionBanner` |
| `instance.created` | user | participants | My jobs list |
| `instance.state_changed` | both | participants, Console | `StageStepper`, lists |
| `participant.bound` | instance | participants | Job header people |
| `task.state_changed` | instance | buyer, Console | `TaskStatus` |
| `attempt.started` / `attempt.ended` | instance | every participant role on the job (from `work.participants`) | `TaskStatus`, "Agent working" |
| `turn.created` | instance | the conversation's participants | `PersonMessage` |
| `agent.message.delta` | instance | the participant the turn answers | `StreamingText` |
| `agent.message.completed` | instance | conversation participants | `AgentMessage` (typed blocks) |
| `agent.tool.activity` | instance | buyer; requester sees reads only | `ToolActivity` |
| `artifact.version_created` | instance | roles whose visibility includes the artifact | `ArtifactChip`, panel views |
| `pending.created` / `pending.resolved` | both | the person or role it is for | `DecisionCard`, `ApprovalCard`, Inbox |
| `approval.requested` / `approval.step_decided` / `approval.resolved` | both | approvers, buyer, Console | `ApprovalCard`, Console approvals |
| `action.state_changed` | instance | buyer, Console | Gateway action detail |
| `timer.fired` | instance | participants | Timeline entry |
| `verification.completed` | instance | buyer, Console | Verified badge, REWORK notice |
| `seat.state_changed` | user | `seat_audience`: seat owner, placement team, and anyone whose org roles may start a workflow on that Seat | Digital worker card |
| `kill_switch.changed` | both | everyone affected | `SeatNotice` |
| `notification.created` | user | the addressee | Inbox, bell count |

### Visibility rules for the projection

1. A viewer receives instance events only for instances where they hold a participant role, or with a Console role.
2. `artifact.version_created` carries refs only (`artifact_id`, `version`, `artifact_type`, plus chip metadata such as
   `status` and `by`); it never includes artifact content. Any block quoting artifact content passes through the
   artifact type's `visibility` for the viewer's role; fields not visible are dropped, not masked.
3. `agent.message.delta` goes only to the participant whose turn is being answered. Others get the completed turn.
   Its `turn_id` is that answered turn (the reply's own turn exists only once `agent.message.completed` arrives), so
   the client shows the live text under the answered message and drops it when the completed reply arrives.
   Deltas are not stored in the outbox; the hub relays them in-process. The JSON may carry an ephemeral `id`, but SSE
   sends only `event:` and `data:` (no SSE `id:` line) so `Last-Event-ID` remains an outbox cursor.
4. Refusals are delivered as a `refusal` block carrying the decision ID and rule, never the refused data.
5. When an assist reply ends for good without one (a failure that won't be retried, a budget stop, a lease that
   expired with no attempts left), the kernel adds a Seat turn with a `notice` block (tone `bad`) saying the reply
   couldn't be finished and the kind of reason, and sends it as `agent.message.completed`. Details stay in the
   execution events.

## Outbox mechanics (backend)

Per **ADR 013**, the Postgres outbox table is the stream source; `LISTEN/NOTIFY` wakes the SSE hub. There is no
Redis. `pg_notify` is called **inside** the same transaction as the outbox insert; Postgres delivers notifications
when that transaction commits and discards them on rollback.

```
BEGIN
  UPDATE work.instances SET state = 'shortlisting', version = version + 1 WHERE id = 'QQ-0001' AND version = :expected
  INSERT INTO gov.decision_records (...)
  INSERT INTO evidence.execution_events (...)                         -- evidence
  INSERT INTO evidence.outbox (stream, seq, event_type, data, audience)  -- one row per stream the change reaches
  SELECT pg_notify('aos_outbox', '<stream>')                          -- once per stream touched; commit delivers
  SELECT audit append (head row locked)                               -- authority events only
COMMIT
```

- `evidence.outbox.seq` is per **outbox stream** (`instance:QQ-0001`, `user:noura`), allocated atomically on
  `evidence.stream_heads` with `INSERT … ON CONFLICT DO UPDATE … RETURNING last_seq`. The SSE cursor is
  `<stream>:<seq>` (UiEvent `id`). Only streams whose names start with `instance:` or `user:` receive outbox
  rows and `pg_notify` payloads.
- Outbox rows store `event_type` (UiEvent `type`), `data` (UiEvent payload), and `created_at` (UiEvent `at`).
- **`evidence.stream_heads` also holds execution counters:** `aggregate_seq` is monotonic per `run_id`,
  allocated on a row keyed `run:<run_id>` (same upsert pattern), independent of instance row locks. The `run:`
  prefix is **reserved for kernel sequencing**; those rows are never read as outbox streams, never notified on
  `aos_outbox`, and never appear in SSE cursors.
- Execution events are **instance-scoped** (`run_id` = instance id). Seat lifecycle evidence uses
  `registry.seat_events`, not `execution_events`. When several outbox streams are touched in one command, append
  rows in **sorted stream name order** (`append_outbox_many`) so shared `user:` heads lock consistently.
- Persisted execution-event column is `org_id`; the JSON schema field is `tenant_id`.
- The SSE hub reads `seq > cursor` from `evidence.outbox` only (outbox stream names) and re-checks visibility at
  send time, because a viewer's role can change.
