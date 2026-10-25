-- M2-AG-01: superseded workflow Tasks (revise intake, task.retry replacement).

alter table work.tasks add column superseded_by text references work.tasks(id);
create index tasks_latest on work.tasks (instance_id, template, created_at desc, id desc)
  where superseded_by is null and kind = 'task';

grant select, insert, update on work.tasks to aos_kernel;
