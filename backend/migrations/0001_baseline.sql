-- AOS POC baseline schema (M0). Six schemas, one per ownership domain (ADR 001, ADR 008).
-- Later milestones add tables in work, gov and evidence; nothing here names a supplier, an RFQ or a price.

create extension if not exists pgcrypto;

create schema if not exists org;
create schema if not exists registry;
create schema if not exists work;
create schema if not exists gov;
create schema if not exists evidence;
create schema if not exists lg_checkpoints;   -- LangGraph AsyncPostgresSaver tables (M1); the only schema the worker writes

-- ------------------------------------------------------------------ org
create table org.organizations (
  id text primary key,
  name text not null,
  data_residency text not null,
  created_at timestamptz not null default now()
);

create table org.departments (
  org_id text not null references org.organizations(id),
  id text not null,
  name text not null,
  head_person_id text,
  primary key (org_id, id)
);

create table org.teams (
  org_id text not null,
  department_id text not null,
  id text not null,
  name text not null,
  owner_person_id text not null,
  primary key (org_id, department_id, id),
  foreign key (org_id, department_id) references org.departments(org_id, id)
);

create table org.people (
  org_id text not null references org.organizations(id),
  id text not null,
  name text not null,
  department_id text not null,
  team_id text not null,
  console_access boolean not null default false,
  primary key (org_id, id),
  foreign key (org_id, department_id, team_id) references org.teams(org_id, department_id, id)
);

alter table org.teams add constraint teams_owner_fk
  foreign key (org_id, owner_person_id) references org.people(org_id, id) deferrable initially deferred;
alter table org.departments add constraint departments_head_fk
  foreign key (org_id, head_person_id) references org.people(org_id, id) deferrable initially deferred;

create table org.role_mappings (
  org_id text not null,
  person_id text not null,
  role text not null,
  granted_by text not null default 'seed',
  granted_at timestamptz not null default now(),
  primary key (org_id, person_id, role),
  foreign key (org_id, person_id) references org.people(org_id, id)
);

-- ------------------------------------------------------------------ registry
create table registry.packs (
  org_id text not null references org.organizations(id),
  name text not null,
  owner text not null,
  primary key (org_id, name)
);

create table registry.pack_versions (
  id uuid primary key default gen_random_uuid(),
  org_id text not null,
  pack_name text not null,
  version int not null check (version >= 1),
  digest text not null,
  source text not null,                       -- e.g. git main@a41c09e
  status text not null check (status in ('draft', 'validated', 'invalid', 'publish_requested', 'published', 'retired')),
  validation jsonb not null,
  created_by text not null,
  created_at timestamptz not null default now(),
  published_at timestamptz,
  unique (org_id, pack_name, version, digest),
  foreign key (org_id, pack_name) references registry.packs(org_id, name)
);

-- Each kind object of a pack version. Published rows are immutable (trigger below).
create table registry.definitions (
  pack_version_id uuid not null references registry.pack_versions(id),
  kind text not null,
  name text not null,
  version int not null,
  spec jsonb not null,
  digest text not null,
  file text not null,
  primary key (pack_version_id, kind, name)
);

create table registry.publish_requests (
  id uuid primary key default gen_random_uuid(),
  pack_version_id uuid not null references registry.pack_versions(id),
  requested_by text not null,
  requested_at timestamptz not null default now(),
  status text not null check (status in ('open', 'approved', 'rejected')),
  required_approvers jsonb not null,           -- [{"for": "policies", "role": "risk"}, ...]
  approvals jsonb not null default '[]'
);

create function registry.forbid_published_change() returns trigger language plpgsql as $$
begin
  if exists (select 1 from registry.pack_versions v
             where v.id = coalesce(old.pack_version_id, new.pack_version_id) and v.status = 'published') then
    raise exception 'published definitions are immutable; publish a new version instead';
  end if;
  return coalesce(new, old);
end $$;

create trigger definitions_immutable before update or delete on registry.definitions
  for each row execute function registry.forbid_published_change();

-- ------------------------------------------------------------------ evidence: audit hash chain
-- One chain per organization. The kernel computes record_hash = sha256(prev_hash || canonical_json(record))
-- and appends under a lock on the chain head, so concurrent writers serialize (ADR 008).
create table evidence.audit_heads (
  org_id text primary key references org.organizations(id),
  last_seq bigint not null default 0,
  last_hash text not null
);

create table evidence.audit_events (
  org_id text not null references org.organizations(id),
  seq bigint not null,
  occurred_at timestamptz not null,
  actor text not null,                         -- person id, seat id or 'kernel'
  action text not null,                        -- e.g. pack.validated, seat.activate.denied
  subject text not null,                       -- what it acted on
  correlation_id text,
  data jsonb not null default '{}',
  prev_hash text not null,
  record_hash text not null,
  primary key (org_id, seq)
);
create index audit_events_corr on evidence.audit_events (org_id, correlation_id);

create function evidence.forbid_audit_change() returns trigger language plpgsql as $$
begin
  raise exception 'the audit log is append-only';
end $$;

create trigger audit_append_only before update or delete on evidence.audit_events
  for each row execute function evidence.forbid_audit_change();
