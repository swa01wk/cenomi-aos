-- M2-BE-02: once-only domain events raised by the kernel.

alter table work.instances
  add column if not exists raised_events jsonb not null default '[]';
