-- M2-BE-05: kernel task.retry pending items reference the failed workflow Task.
alter table work.pending_items
  add column task_id text references work.tasks(id) on delete set null;

create unique index pending_one_open_task_retry on work.pending_items (task_id)
  where status = 'open' and event = 'task.retry' and task_id is not null;
