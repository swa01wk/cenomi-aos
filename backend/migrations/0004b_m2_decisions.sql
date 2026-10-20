-- M2-BE-04: decision idempotency, selection on Decision Records.

alter table gov.decision_records
  add column if not exists selection jsonb,
  add column if not exists idempotency_key text,
  add column if not exists request_hash text,
  add column if not exists response jsonb;

create unique index if not exists decision_records_idempotency
  on gov.decision_records (org_id, actor, idempotency_key)
  where idempotency_key is not null;
