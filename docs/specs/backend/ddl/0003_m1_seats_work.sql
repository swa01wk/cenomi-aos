-- M1 reference DDL: Seats, jobs, Tasks and attempts, artifacts, conversation, events, budgets.
-- Applies on top of backend/migrations/0000–0002. Copy to backend/migrations/0003_*.sql when implementing M1.
-- Conventions: text ids with a readable prefix; every mutable row has `version` for optimistic checks;
-- timestamps are timestamptz; JSON is jsonb. Nothing here names a supplier, an RFQ or a price.

-- ------------------------------------------------------------------ registry: Seats
create table registry.seats (
  org_id text not null references org.organizations(id),
  name text not null,                               -- seat_sourcing_poc
  version int not null,                             -- Seat definition version
  pack_version_id uuid not null references registry.pack_versions(id),
  display_name text not null,
  placement text not null,                          -- procurement/sourcing
  owner_person_id text not null,
  state text not null default 'DRAFT'
    check (state in ('DRAFT','CONFIGURED','TESTING','APPROVED','ACTIVE','PAUSED','KILLED','RETIRED')),
  configured_by text,
  activated_by text,
  record_version int not null default 1,            -- expected_version for lifecycle calls
  updated_at timestamptz not null default now(),
  primary key (org_id, name, version),
  check (activated_by is null or activated_by <> configured_by)      -- segregation of duties, also checked in code
);
-- At most one non-retired version of a Seat is ACTIVE or PAUSED at a time.
create unique index seats_one_live on registry.seats (org_id, name) where state in ('ACTIVE','PAUSED');

create table registry.seat_events (
  id bigserial primary key,
  org_id text not null, seat text not null, seat_version int not null,
  from_state text, to_state text not null,
  actor text not null, decision_id text, note text,
  at timestamptz not null default now()
);

create table registry.seat_checks (
  org_id text not null, seat text not null, seat_version int not null,
  name text not null,                               -- one of the six configuration checks
  passed boolean not null, detail text not null default '',
  checked_at timestamptz not null default now(),
  primary key (org_id, seat, seat_version, name)
);

create table registry.eval_runs (
  id text primary key,                              -- ev_…
  org_id text not null, seat text not null, seat_version int not null,
  suite text not null, model text not null check (model in ('fake','real')),
  status text not null check (status in ('running','passed','failed')),
  passed int not null default 0, total int not null default 0, detail jsonb not null default '{}',
  started_at timestamptz not null default now(), finished_at timestamptz
);

-- ------------------------------------------------------------------ gov: decisions and budgets
create table gov.decision_records (
  id text primary key,                              -- dr_… (DR-0007 shown in the UI)
  org_id text not null,
  subject_kind text not null check (subject_kind in ('seat','instance','publish_request','kill_switch')),
  subject_id text not null,
  event text not null,                              -- seat.activate, decision.brief_confirmed, …
  value text,
  actor text not null, actor_role text,
  artifact_ref jsonb,                               -- {"artifact_id":…, "version":…, "content_hash":…}
  inputs_hash text,
  correlation_id text,
  at timestamptz not null default now()
);
create index decision_records_subject on gov.decision_records (org_id, subject_kind, subject_id);

create table gov.budget_ledger (
  org_id text not null, seat text not null, day date not null,
  limit_usd numeric(10,2) not null,
  reserved_usd numeric(10,4) not null default 0,
  settled_usd numeric(10,4) not null default 0,
  primary key (org_id, seat, day),
  check (reserved_usd + settled_usd <= limit_usd)   -- admission fails before this can be violated
);

-- ------------------------------------------------------------------ work: instances (jobs)
create sequence work.instance_number;
create table work.instances (
  id text primary key,                              -- QQ-0001 (prefix from the workflow)
  org_id text not null references org.organizations(id),
  workflow text not null,                           -- quick_quote
  pack_version_id uuid not null references registry.pack_versions(id),   -- pinned (ADR 009)
  seat text not null, seat_version int not null,
  title text not null,
  state text not null,                              -- current workflow state
  status text not null default 'running' check (status in ('running','closed','cancelled')),
  attributes jsonb not null default '{}',           -- brief_version, shortlist_count, …
  correlation_id text not null unique,
  version int not null default 1,
  created_by text not null,
  idempotency_key text,
  created_at timestamptz not null default now(),
  state_entered_at timestamptz not null default now(),
  closed_at timestamptz,
  unique (org_id, created_by, idempotency_key)
);

create table work.participants (
  instance_id text not null references work.instances(id),
  role text not null,                               -- requester, buyer, procurement_approver
  person_id text not null,
  bound_by text not null check (bound_by in ('creation','claim','rule')),
  bound_at timestamptz not null default now(),
  primary key (instance_id, role)                   -- one person per role: a second claim fails here
);

-- ------------------------------------------------------------------ work: Tasks and attempts (ADR 004)
create table work.tasks (
  id text primary key,                              -- task_…
  instance_id text not null references work.instances(id),
  kind text not null check (kind in ('assist','task')),
  template text not null,                           -- request_intake, rfq_draft, …, or 'assist'
  skill text not null,
  work_type text not null,
  verifier text,
  region text,                                      -- parallel region name, e.g. discovery
  state text not null default 'CREATED'
    check (state in ('CREATED','READY','RUNNING','WAITING_INPUT','WAITING_APPROVAL','VERIFYING','COMPLETED','EXCEPTION','FAILED','CANCELLED')),
  contract jsonb not null,                          -- TaskContract, frozen at creation
  contract_hash text not null,
  fencing_token bigint not null default 0,          -- bumped on every new attempt and on cancel
  attempts_used int not null default 0,
  max_attempts int not null default 3,
  checkpoint_id text,                               -- set while waiting; used by the next attempt
  waiting_for jsonb,                                -- {"kind":"approval","id":"AP-0009"}
  version int not null default 1,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index tasks_ready on work.tasks (state) where state = 'READY';

create table work.attempts (
  id text primary key,                              -- att_…
  task_id text not null references work.tasks(id),
  n int not null,
  fencing_token bigint not null,
  state text not null check (state in ('ADMITTED','CLAIMED','ENDED')),
  outcome text check (outcome in ('submitted','waiting_approval','needs_input','fenced','failed','expired','cancelled')),
  worker_id text,
  lease_expires_at timestamptz,
  turn_id text,                                     -- assist attempts: the turn being answered
  resume jsonb,                                     -- {"checkpoint_id":…, "signal":{…}}
  reserved_usd numeric(10,4) not null default 0,
  usage jsonb not null default '{}',                -- tokens_in, tokens_out, cost_usd, steps, actions
  failure_class text,
  trace_id text,
  admitted_at timestamptz not null default now(),
  claimed_at timestamptz, ended_at timestamptz,
  unique (task_id, n)
);
-- Exactly one live attempt per Task.
create unique index attempts_one_live on work.attempts (task_id) where state in ('ADMITTED','CLAIMED');
create index attempts_claimable on work.attempts (admitted_at) where state = 'ADMITTED';
create index attempts_leases on work.attempts (lease_expires_at) where state = 'CLAIMED';

-- ------------------------------------------------------------------ work: conversation
create table work.turns (
  id text primary key,                              -- turn_…
  instance_id text not null references work.instances(id),
  seq int not null,
  author_kind text not null check (author_kind in ('person','seat','system')),
  author_id text not null,
  audience_roles text[],                            -- null = every participant; else only these roles see it
  blocks jsonb not null,                            -- typed blocks (ui-event.schema.json#/$defs/Block)
  attempt_id text,
  client_turn_id text,
  at timestamptz not null default now(),
  unique (instance_id, seq),
  unique (instance_id, author_id, client_turn_id)
);

-- ------------------------------------------------------------------ work: artifacts (content-addressed versions)
create table work.artifacts (
  id text primary key,                              -- art_…
  instance_id text not null references work.instances(id),
  artifact_type text not null,                      -- brief, supplier_list, rfq_email, quote, comparison, po_payload
  key text not null default '',                     -- per-item artifacts: supplier_id
  name text not null,
  status text not null default 'draft' check (status in ('draft','final','locked')),
  latest_version int not null default 0,
  unique (instance_id, artifact_type, key)
);

create table work.artifact_versions (
  artifact_id text not null references work.artifacts(id),
  version int not null,
  content jsonb not null,                           -- full content; filtering happens on read
  content_hash text not null,
  produced_by_kind text not null check (produced_by_kind in ('attempt','person')),
  produced_by text not null,
  inputs jsonb not null default '[]',               -- [{"artifact_id","version","content_hash"}]
  sources jsonb not null default '[]',
  verification jsonb,                               -- {"verifier","verdict","findings"}
  created_at timestamptz not null default now(),
  primary key (artifact_id, version)
);

create table work.pending_items (
  id text primary key,                              -- pend_…
  instance_id text not null references work.instances(id),
  kind text not null check (kind in ('decision','approval','question')),
  event text,                                       -- decision.brief_confirmed
  title text not null, detail text,
  for_role text not null, for_person_id text,
  options jsonb not null default '[]',
  artifact_ref jsonb,
  approval_id text,
  status text not null default 'open' check (status in ('open','resolved','voided','expired')),
  due_at timestamptz,
  created_at timestamptz not null default now(),
  resolved_at timestamptz, resolved_by text
);
create index pending_open on work.pending_items (instance_id) where status = 'open';

-- ------------------------------------------------------------------ evidence: execution events and outbox
create table evidence.execution_events (
  event_id uuid primary key,
  org_id text not null,
  run_id text not null,                             -- instance id
  aggregate_seq int not null,
  event_type text not null,
  task_id text, attempt_id text,
  actor_kind text not null, actor_id text not null,
  correlation_id text not null, causation_id uuid,
  contract_version int, graph_revision text,
  artifact_refs text[] not null default '{}',
  payload_ref text,
  redacted_summary text not null,
  attributes jsonb not null default '{}',
  occurred_at timestamptz not null default now(),
  unique (run_id, aggregate_seq)
);

create table evidence.stream_heads (
  stream text primary key,                          -- instance:QQ-0001, user:noura
  last_seq bigint not null default 0
);

create table evidence.outbox (
  stream text not null,
  seq bigint not null,
  event_type text not null,                         -- UiEvent type
  instance_id text,
  audience jsonb not null,                          -- {"roles":[…]} or {"person_id":…}; re-checked at send
  data jsonb not null,
  created_at timestamptz not null default now(),
  primary key (stream, seq)
);

-- Grants: the kernel owns all of this; the worker reaches none of it.
grant select, insert, update, delete on all tables in schema registry, gov, work to aos_kernel;
grant select, insert on evidence.execution_events, evidence.outbox to aos_kernel;
grant select, insert, update on evidence.stream_heads to aos_kernel;
grant usage on all sequences in schema work, evidence to aos_kernel;
