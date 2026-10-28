-- M3: dedupe inbound connector notifications (one quote_triage Task per message id).
create table if not exists work.inbound_messages (
  source text not null,
  message_id text not null,
  conversation_id text not null,
  instance_id text,
  payload jsonb not null,
  received_at timestamptz not null default now(),
  processed_at timestamptz,
  primary key (source, message_id)
);

grant select, insert, update, delete on work.inbound_messages to aos_kernel;
