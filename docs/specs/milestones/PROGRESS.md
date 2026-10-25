# Progress

Tick a story when its PR merges with `make check` green. Stories are listed in the suggested build order inside each
milestone. A story's details, tests and contract references are in its milestone file.

## M0 Foundations — done

- [x] Pack format, `aos validate`, schemas and roles, org seed, audit chain, kernel API, broker, mock connectors,
      worker protocol, React shell (82 tests)

## M1 Seat and chat — [M1-seat-and-chat.md](M1-seat-and-chat.md)

- [x] M1-BE-01 Foundations for work state (migration from `ddl/0003`, ids, outbox)
- [x] M1-FE-01 Move to Vite and the router
- [x] M1-FE-02 Shared components
- [x] M1-BE-02 Publish requests
- [x] M1-BE-03 Seat lifecycle
- [x] M1-FE-03 Console: publish and Seats
- [x] M1-BE-04 Jobs and conversation
- [x] M1-BE-05 Worker protocol
- [x] M1-BE-06 Context assembler and visibility
- [x] M1-BE-07 Gateway reads
- [x] M1-AG-01 Runtime and worker process
- [x] M1-AG-04 Checkpointer
- [x] M1-AG-02 Assist graph and model
- [x] M1-AG-03 request_intake in chat
- [x] M1-FE-04 Workspace: start and chat
- [x] M1 exit gate (all boxes in the milestone file)

## M2 Workflow layer — [M2-workflow-layer.md](M2-workflow-layer.md)

- [x] M2-BE-01 Workflow interpreter
- [x] M2-BE-04 Decisions
- [x] M2-BE-07 Conversation follows the job (ADR 015)
- [x] M2-BE-03 Participants, queue and claim
- [x] M2-BE-02 Parallel region and join
- [x] M2-BE-05 Timers, scheduler and demo clock
- [x] M2-AG-01 Task graph
- [x] M2-AG-03 Verifiers
- [ ] M2-AG-02 supplier_lookup and rfq_draft
- [ ] M2-AG-04 Assist Skills that keep people informed
- [x] M2-BE-06 Simulate and Console reads
- [ ] M2-FE-01 Lists and live updates
- [ ] M2-FE-02 Job page decisions and views
- [ ] M2-FE-03 Console
- [ ] M2 exit gate

## M3 Governed actions — [M3-governed-actions.md](M3-governed-actions.md)

- [ ] M3-BE-01 Policy engine
- [ ] M3-BE-02 Approvals
- [ ] M3-BE-03 Actions, gateway effects and reconciliation
- [ ] M3-AG-01 Interrupt and resume
- [ ] M3-BE-04 Inbound mail and quotes
- [ ] M3-BE-05 Verifiers and budgets
- [ ] M3-BE-06 Progress for governed actions (ADR 015)
- [ ] M3-AG-02 rfq_send, quote_triage, quote_comparison, po_create
- [ ] M3-FE-01 Approvals in the Workspace
- [ ] M3-FE-02 Console governance
- [ ] M3 exit gate

## M4 Govern and observe — [M4-govern-and-observe.md](M4-govern-and-observe.md)

- [ ] M4-BE-01 Emergency control
- [ ] M4-BE-02 Outcome and explain
- [ ] M4-BE-03 Telemetry and dashboards
- [ ] M4-AG-01 Spans and behavioral evals
- [ ] M4-BE-04 Evals for real
- [ ] M4-FE-01 Govern screens
- [ ] M4 exit gate

## M5 Harden and demo — [M5-harden-and-demo.md](M5-harden-and-demo.md)

- [ ] M5-BE-01 Failure-path suite
- [ ] M5-BE-02 Replay
- [ ] M5-AG-01 Agent tuning and eval baseline ADR
- [ ] M5-FE-01 17-stop demo in Playwright, presenter script
- [ ] M5 exit gate
- [ ] M5-ST-01 Stretch: second domain pack (Sales lead qualification)
- [ ] M5-ST-02 Stretch: first load test
