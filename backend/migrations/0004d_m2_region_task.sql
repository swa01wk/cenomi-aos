-- M2-BE-02: a region names its current Task, so "is this the region's latest Task?" never depends on timestamps
-- (now() is the transaction start time, so Tasks created in one transaction tie).
-- on delete set null: Tasks are never deleted in normal operation; cleanup that removes Tasks before regions
-- (test teardown) just clears the pointer.
alter table work.regions add column current_task text references work.tasks(id) on delete set null;
