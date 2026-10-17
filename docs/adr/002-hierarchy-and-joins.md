# ADR 002 — Hierarchy and joins

- **Status:** Proposed (awaiting sign-off at the M0 gate)
- **Owner:** Kernel lead

## Context
The reference architecture allows workflows to create Tasks dynamically and join them with several
policies (any, quorum, all). The Quick Quote scenario needs neither dynamic fan-out nor partial joins.

## Decision
- A workflow is a set of states. Each state declares a fixed list of Task templates
  (`template`, `skill`, `work_type`, `verifier`) in `workflows/*.yaml`.
- Entering a state creates exactly those Tasks. The state's exit transitions fire only when
  **all required** Tasks are terminal ("all required" join).
- Transitions are triggered by named events: `decision.*` (needs `by`), `task.completed.<template>`,
  `timer.<emits>` and `event.<declared>`. `aos validate` rejects unknown events (`E_EVENT`),
  unreachable states (`E_UNREACHABLE`), dead ends (`E_DEAD_END`) and workflows without a final state.

## Alternatives considered
Dynamic Task creation from agent output; any/quorum joins. Deferred to MVP — they need ADR 010
(graph mutation) first.

## Assumptions
Every state in the POC pack has one to three Tasks; none needs to run a variable number.

## Verification
`aos validate packs/procurement_demo` passes; `test_validate` covers each workflow error code.
In M2 the Quick Quote instance reaches `awarded` only after both comparison Tasks complete.
