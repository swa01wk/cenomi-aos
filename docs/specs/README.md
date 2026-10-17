# Specs

Everything needed to build milestones M1–M5. The specs trace from the screens down to the agent. The design shows a
screen, the trace map names what the screen needs, and the contracts define those needs exactly. The backend,
frontend and agent specs say how each part behaves. The milestone files order the work.

```
design/  ──►  trace-map.md  ──►  contracts/ (openapi, schemas, events)
                                   │
              ┌────────────────────┼────────────────────┐
         frontend/            backend/ (+ ddl/)       agent/ (harness, skills/)
              └────────────────────┼────────────────────┘
                              milestones/M1…M5
```

## Reading order

1. [`../plan/north-star.md`](../plan/north-star.md): the eight checks the POC must pass.
2. [`trace-map.md`](trace-map.md): each of the 32 design boards, with its route, components, API operations,
   events, kernel records and agent parts. It also has the walkthrough stop table.
3. [`contracts/`](contracts/README.md): the OpenAPI spec (each operation is tagged with `x-milestone` and
   `x-screens`), the JSON Schemas and the event catalogue.
4. Part specs:
   - [`backend/README.md`](backend/README.md): module layout, request rules, Seat lifecycle, the eight admission
     gates, Task and attempt state machines, the workflow interpreter, policy engine, approvals, action executions
     and the SSE hub. Reference DDL for each milestone is in [`backend/ddl/`](backend/ddl).
   - [`agent/harness.md`](agent/harness.md): AgentRuntime, graphs, checkpoints, prompts, the model registry,
     fake model scripts, failure classes and tracing. Each Skill has its own spec in [`agent/skills/`](agent/skills).
   - [`frontend/README.md`](frontend/README.md): stack, routes, components, how Problems map to UI, the stream
     reducer, accessibility and tests.
5. The milestone you're implementing: [`milestones/`](milestones).

## Milestones

| Milestone | File | Proves |
|---|---|---|
| M0 Foundations | done (see root README) | pack format, `aos validate`, schemas, audit chain, connectors, worker protocol |
| M1 Seat and chat | [M1-seat-and-chat.md](milestones/M1-seat-and-chat.md) | publish → activate a Seat through the gates; one Task attempt runs a Skill; assist chat streams |
| M2 Workflow layer | [M2-workflow-layer.md](milestones/M2-workflow-layer.md) | the Quick Quote workflow moves only on kernel decisions; participants and visibility |
| M3 Governed actions | [M3-governed-actions.md](milestones/M3-governed-actions.md) | policy, bound approvals, idempotent effects, UNKNOWN → reconciled |
| M4 Govern and observe | [M4-govern-and-observe.md](milestones/M4-govern-and-observe.md) | kill switch, instance view, observability, audit search |
| M5 Harden and demo | [M5-harden-and-demo.md](milestones/M5-harden-and-demo.md) | test backlog C01–C14, replay, demo controls, the scripted walkthrough; stretch: a second pack (Sales lead qualification) on the same platform, and a first load test |

Each milestone file lists stories with IDs (`M1-BE-01`, `M1-FE-03`, `M1-AG-02` …). Each story names its operations,
tables and tests. The file ends with an exit gate checklist and a definition of done.

## Using these with Cursor

- `.cursor/rules/` applies the architecture rules automatically. The project rule is always on. The kernel, agent,
  frontend and test rules attach by path.
- Work one story at a time and point Cursor at the story plus the files it names. For example: *"Implement
  M1-BE-03 from docs/specs/milestones/M1-seat-and-chat.md. Use the operations in contracts/openapi.yaml and the
  tables in backend/ddl/0003_m1_seats_work.sql. Write the listed tests."*
- When a story needs something the contract doesn't have, change the contract first (spec, schema, example and
  DDL) in the same change. `make test` runs `test_contracts.py`, which catches drift between the code and
  `openapi.yaml`.

## Known prerequisites for M1 agent work

- LangGraph and its checkpointer need a normal package registry (`pip install -e 'backend[dev,runtime]'`).
- A real model run needs `ANTHROPIC_API_KEY`. Every test uses `FakeModel` and doesn't need it.
