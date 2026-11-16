-- Job-level files included on every RFQ send (buyer upload, POC demo).
create table if not exists work.instance_shared_attachments (
  id text primary key,
  org_id text not null,
  instance_id text not null references work.instances (id) on delete cascade,
  filename text not null,
  content_type text not null default 'application/octet-stream',
  size_bytes integer not null,
  content bytea not null,
  uploaded_by text not null,
  uploaded_at timestamptz not null default now()
);

create index if not exists instance_shared_attachments_instance
  on work.instance_shared_attachments (instance_id, uploaded_at);

grant select, insert, update, delete on work.instance_shared_attachments to aos_kernel;
