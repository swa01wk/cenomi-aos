-- Database roles (run once per cluster by an administrator; Compose runs it at init).
-- aos_kernel owns business state. aos_worker may only write LangGraph checkpoints (ADR 001, ADR 004).
do $$
begin
  if not exists (select from pg_roles where rolname = 'aos_kernel') then
    create role aos_kernel login password 'aos_kernel_dev';
  end if;
  if not exists (select from pg_roles where rolname = 'aos_worker') then
    create role aos_worker login password 'aos_worker_dev';
  end if;
end $$;
