# Architecture decision records

Status of each: **Proposed** until signed off (M0 gate). Reference architecture v1.2 §38 asks for ADR-01 to ADR-10 with
its own numbering; this table maps them to ours so nothing is missing.

| Ours | Decision | Reference architecture v1.2 §38 |
| --- | --- | --- |
| [001](001-state-ownership.md) | State ownership: kernel FSM authoritative; LangGraph checkpoint is attempt memory | ADR-01 authoritative state and transaction boundaries |
| [002](002-hierarchy-and-joins.md) | Fixed Task templates per state; all-required joins | ADR-05 (scheduler part) |
| [003](003-contract-and-context-envelope.md) | Task Contract and context envelope schemas | ADR-03 task/event schemas and version compatibility |
| [004](004-concurrency-leases-fencing.md) | Leases, heartbeats, fencing tokens, one live attempt | ADR-05 scheduler, leases, fencing, reconciliation |
| [005](005-idempotency-and-reconciliation.md) | Idempotency keys and reconciliation per connector | ADR-05 (reconciliation part), ADR-04 (tool authorization part) |
| [006](006-approval-binding-and-chains.md) | Approval binding and chains | ADR-09 (approval binding part) |
| [007](007-budgets.md) | Budget reservations and limits | ADR-07 (budgets part) |
| [008](008-evidence-and-audit-chain.md) | Evidence, retention and audit chain | ADR-08 artifacts, identity, provenance; ADR-10 (retention part) |
| [009](009-replay-and-definition-migration.md) | Replay modes and definition pinning | ADR-03 (version compatibility part) |
| [010](010-graph-mutation.md) | No graph mutation in the POC | §19 question 5 |
| [011](011-harness-adapter.md) | AgentRuntime adapter and checkpoint semantics | ADR-02 harness adapter interface and checkpoint semantics |
| [012](012-context-freshness.md) | Context freshness, visibility and memory writes | ADR-06 context freshness, retrieval permissions, memory writes |
| [013](013-streamed-ui.md) | Streamed UI: snapshot, cursor, typed blocks | ADR-09 streamed UI and human approval binding |
| [014](014-model-provider.md) | Model provider behind the alias: OpenAI `gpt-5.4-mini` for development, Anthropic optional | ADR-07 (model router part) |
| [015](015-conversation-skill.md) | Conversation skill for user-facing Seats: one skill handles every message, step Skills are its actions, talk never changes state (proposed after M1) | — (digital worker levels 3–4) |
| — | Model fallback | ADR-07: no fallback in the POC (agent/harness.md, ADR 014) |
| — | Sandbox isolation | ADR-04: no code execution in the POC; tool authorization in 005 and the gateway spec |
| — | Operational security, SLO, DR | ADR-10: set in M5 from measurements (restore drill in M5) |
