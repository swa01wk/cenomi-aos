Model: Composer 2.5 (Agent mode) | Branch: feat/SPEC-19-rfp-journey-parity

Context: read AGENTS.md, .cursor/rules/, plans/UAT-1/milestone.md (the rule for the slice and the requirement
IDs), plans/UAT-1/specs/SPEC-19-rfp-journey-parity/spec.md, and the files it names. Contracts: docs/specs/contracts/openapi.yaml, schemas and events.md.
For agent work also read the skill folder under packs/procurement_demo/skills/ and backend/src/aos/worker/scripts/.

Task: implement SPEC-19 (RFP journey, integration suite, UI fixtures and demo parity) exactly as specified.

Before editing, reply with a short plan: files, operations, tables, events and the tests (T-19-n) you will
write. Wait for my OK.

Boundaries: change only what the spec lists (web/e2e/journeys/, scripts/verify-demo-rfp.sh, web/src/workspace/job/, .github/workflows/ci.yml) plus tests. Do not change a public contract without
updating docs/specs/contracts/ in the same change. Keep platform code pack-neutral (test_pack_neutral.py).
The kernel decides; the agent proposes. No heal or demo path may run when AOS_DEMO=0.

Tests: write the spec's tests first, make them pass, run `make check` (Postgres up, nothing skipped). For agent
specs also add fake scripts so CI is deterministic, and run `make eval` once the eval runner exists.

Rules: AGENTS.md and .cursor/rules apply. Flag any new dependency. No secrets or real client data in code,
prompts or fixtures.

Report: changes made, tests added, any deviation from the spec and why. Then update this spec's row in
plans/STATUS.md (status, PR link) and add a line to the daily log there. Commit title:
`SPEC-19: RFP journey, integration suite, UI fixtures and demo parity`.
