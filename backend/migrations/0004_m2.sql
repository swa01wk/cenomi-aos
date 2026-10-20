-- M2: workflow layer (transitions, parallel regions, timers, demo clock, notifications).

create table work.instance_transitions (
  id bigserial primary key,
  instance_id text not null references work.instances(id),
  from_state text not null,
  to_state text not null,
  event text not null,                              -- decision.shortlist_confirmed, task.completed.rfq_draft, timer.quotes_closed
  guard text,                                       -- the guard expression that held, if any
  decision_id text,
  instance_version int not null,                    -- version after the transition; unique per instance
  at timestamptz not null default now(),
  unique (instance_id, instance_version)
);

create table work.regions (
  instance_id text not null references work.instances(id),
  name text not null,                               -- discovery
  state text not null check (state in ('running','done','joined','abandoned')),
  started_on text not null,                         -- event.intent_identified
  join_at text not null,                            -- shortlisting
  join_guard text,                                  -- same(brief_version)
  started_with jsonb not null default '{}',         -- attribute values when the branch started
  started_at timestamptz not null default now(),
  joined_at timestamptz,
  primary key (instance_id, name)
);

create table work.timers (
  id text primary key,                              -- tmr_…
  instance_id text not null references work.instances(id),
  name text not null,                               -- quote_deadline
  emits text not null,                              -- quotes_closed
  fires_at timestamptz not null,                    -- on the kernel clock (demo offset applied)
  status text not null default 'scheduled' check (status in ('scheduled','fired','cancelled')),
  generation int not null default 1,
  fired_at timestamptz,
  unique (instance_id, name, generation)
);
create index timers_due on work.timers (fires_at) where status = 'scheduled';

create table work.demo_clock (
  org_id text primary key,
  offset_seconds bigint not null default 0,         -- kernel now() = wall clock + offset when AOS_DEMO=1
  updated_at timestamptz not null default now()
);

create table work.notifications (
  id text primary key,                              -- ntf_…
  org_id text not null,
  person_id text not null,
  instance_id text,
  text text not null,
  at timestamptz not null default now(),
  read_at timestamptz
);
create index notifications_unread on work.notifications (person_id) where read_at is null;

grant select, insert, update, delete on work.instance_transitions, work.regions, work.timers, work.demo_clock, work.notifications to aos_kernel;
grant usage on all sequences in schema work to aos_kernel;
