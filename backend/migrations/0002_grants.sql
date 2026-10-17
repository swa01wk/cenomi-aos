-- Privileges after the baseline. Applied as the database owner.
grant usage on schema org, registry, work, gov, evidence, lg_checkpoints to aos_kernel;
grant select, insert, update, delete on all tables in schema org, registry, work, gov to aos_kernel;
grant select, insert on all tables in schema evidence to aos_kernel;          -- audit: append only
grant update on evidence.audit_heads to aos_kernel;
alter default privileges in schema org, registry, work, gov grant select, insert, update, delete on tables to aos_kernel;

-- The worker reaches business state only through the kernel API.
grant usage, create on schema lg_checkpoints to aos_worker;
revoke all on all tables in schema org, registry, work, gov, evidence from aos_worker;
