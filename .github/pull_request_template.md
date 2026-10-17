## Story

<!-- One story per PR, e.g. M1-BE-03 Seat lifecycle — docs/specs/milestones/M1-seat-and-chat.md -->

## What changed

-

## Contract changes

<!-- New or changed operations, schema fields, events or tables. "None" if none. Every change here is also in
     docs/specs/contracts/ (openapi.yaml, schemas, examples) or the migrations, in this PR. -->

None

## Checks

- [ ] The story's tests from the milestone file are written and pass
- [ ] `make check` passes (tests + `aos validate`), with Postgres running (`AOS_TEST_REQUIRE_PG=1`)
- [ ] Screens match `design/png` and `design/boards` (attach a screenshot for UI stories)
- [ ] No pack, workflow or domain names in platform code (`test_pack_neutral.py`)
- [ ] `docs/specs/milestones/PROGRESS.md` updated
