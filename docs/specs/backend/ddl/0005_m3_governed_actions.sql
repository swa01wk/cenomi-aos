-- M3 reference DDL: policy decisions, approvals, action executions, inbound messages.

create table gov.policy_decisions (
  id text primary key,                              -- pd_…
  org_id text not null,
  instance_id text,
  task_id text, attempt_id text,
  action text not null,                             -- mailbox.send, erp_po.create, quotes.read
  subject_kind text not null check (subject_kind in ('seat','person')),
  subject_id text not null,
  participant_role text,
  result text not null check (result in ('ALLOW','REQUIRE_APPROVAL','DENY','NEVER')),
  rule text not null,                               -- matching rule id, or 'default_deny'
  policy_version text not null,                     -- quick_quote_gates@1 + sourcing_supervised@1
  evaluation jsonb not null,                        -- ordered steps with matched/detail
  attributes_snapshot jsonb not null,               -- every attribute the conditions read
  snapshot_hash text not null,
  at timestamptz not null default now()
);
create index policy_decisions_instance on gov.policy_decisions (instance_id, at);

create sequence gov.approval_number;
create table gov.approvals (
  id text primary key,                              -- AP-0009
  org_id text not null,
  instance_id text not null references work.instances(id),
  task_id text not null references work.tasks(id),
  requested_by_attempt text references work.attempts(id),
  requested_by text not null,                       -- seat or person id
  action text not null,                             -- mailbox.send
  tool text not null,                               -- send_message
  summary text not null,
  payload jsonb not null,                           -- exactly what will run
  payload_hash text not null,                       -- sha256(canonical {tool, args, artifact_refs, policy_version})
  artifact_refs jsonb not null,
  policy_decision_id text not null references gov.policy_decisions(id),
  status text not null default 'open' check (status in ('open','approved','rejected','voided','expired')),
  expires_at timestamptz not null,
  created_at timestamptz not null default now(),
  resolved_at timestamptz,
  version int not null default 1
);
create index approvals_open on gov.approvals (instance_id) where status = 'open';

create table gov.approval_steps (
  approval_id text not null references gov.approvals(id),
  n int not null,
  approver_role text not null,                      -- participant:buyer, participant:procurement_approver
  approver_person_id text,                          -- resolved when the step opens
  kind text not null default 'release' check (kind in ('content','release')),
  status text not null default 'waiting' check (status in ('waiting','approved','rejected','skipped')),
  decided_by text, decided_at timestamptz, note text,
  primary key (approval_id, n)
);
-- distinct_approvers: one person decides at most one step of an approval.
create unique index approval_steps_distinct on gov.approval_steps (approval_id, decided_by) where decided_by is not null;

create table work.action_executions (
  id text primary key,                              -- ae_311
  org_id text not null,
  instance_id text not null references work.instances(id),
  task_id text not null references work.tasks(id),
  attempt_id text references work.attempts(id),
  approval_id text references gov.approvals(id),
  connector text not null, tool text not null,
  idempotency_key text not null unique,             -- same key on every retry and on reconciliation
  args jsonb not null, args_hash text not null,
  state text not null default 'INTENDED'
    check (state in ('INTENDED','EXECUTING','SUCCEEDED','FAILED','UNKNOWN','RECONCILED')),
  remote_id text,                                   -- PO-778201, message id
  receipt jsonb,
  history jsonb not null default '[]',              -- [{state, at, detail}]
  verification jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index actions_unknown on work.action_executions (updated_at) where state in ('EXECUTING','UNKNOWN');

create table work.inbound_messages (
  source text not null,                             -- mock_mail
  message_id text not null,
  conversation_id text not null,
  instance_id text,
  payload jsonb not null,
  received_at timestamptz not null default now(),
  processed_at timestamptz,
  primary key (source, message_id)                  -- duplicate notifications are dropped here
);

grant select, insert, update, delete on gov.policy_decisions, gov.approvals, gov.approval_steps,
  work.action_executions, work.inbound_messages to aos_kernel;
grant usage on all sequences in schema gov to aos_kernel;
