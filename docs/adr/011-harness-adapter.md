# ADR 011 — AgentRuntime adapter and checkpoint semantics

- **Status:** Proposed
- **Owner:** Runtime lead

## Context
Reference architecture v1.2 §28 asks for a provider-neutral harness with start, resume, interrupt, cancel, inspect and
subscribe, and adapter-private checkpoints.

## Decision
- The worker implements `AgentRuntime` with two adapters: `LangGraphRuntime` (real model) and `FakeRuntime` (scripted
  model). Both run the same graphs; only the chat model differs (`docs/specs/agent/harness.md`).
- Checkpoints are adapter-private, stored by `AsyncPostgresSaver` in `lg_checkpoints`. Only canonical contracts,
  events and artifacts cross the kernel boundary.
- Resume after approval or input continues the interrupted thread on a new attempt; retry and REWORK start a new
  thread (amends ADR 001).
- Cancel is the kernel bumping the fencing token; the worker notices on its next heartbeat or kernel call.

## Alternatives
Claude Agent SDK or a custom loop behind the same protocol — kept possible by the adapter boundary, not built.

## Verification
The fake adapter passes every Skill's `happy` script; the resume test executes the approved action exactly once.
