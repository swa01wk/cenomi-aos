-- M4 reference DDL: kill switches, credential revocation, outcome records.

create table gov.kill_switches (
  id text primary key,                              -- ks_…
  org_id text not null,
  scope text not null check (scope in ('seat','workflow','instance')),
  target text not null,                             -- seat name, workflow name or instance id
  reason text not null,
  active boolean not null default true,
  activated_by text not null,
  activated_at timestamptz not null default now(),
  lifted_by text, lifted_at timestamptz, review_note text,
  check (lifted_by is null or lifted_by <> activated_by),       -- lifting needs a second person
  check (active or (lifted_by is not null and review_note is not null))
);
create index kill_switches_active on gov.kill_switches (org_id, scope, target) where active;

create table gov.credential_revocations (
  id bigserial primary key,
  org_id text not null,
  scope text not null, target text not null,
  not_before timestamptz not null default now(),    -- the gateway refuses broker tokens issued before this
  kill_switch_id text references gov.kill_switches(id)
);

create table evidence.outcome_records (
  instance_id text primary key references work.instances(id),
  org_id text not null,
  outcome jsonb not null,                           -- supplier, po_reference, totals as the buyer may see them
  pack_version text not null,
  decision_ids text[] not null,
  closed_at timestamptz not null
);

grant select, insert, update on gov.kill_switches to aos_kernel;
grant select, insert on gov.credential_revocations, evidence.outcome_records to aos_kernel;
grant usage on all sequences in schema gov to aos_kernel;
