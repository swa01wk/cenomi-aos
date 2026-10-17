# Contracts

The single source of truth for the shapes that cross a boundary. Code follows these files. When code needs to
differ, change the file in the same commit.

| File | What it defines | Used by |
|---|---|---|
| [`openapi.yaml`](openapi.yaml) | Every HTTP operation (OpenAPI 3.1). Each has `x-milestone` (when it's built) and `x-screens` (which boards use it). Security schemes: `session` (people), `worker` (worker bearer + fencing token), `inboundSignature` (mail replies). | kernel routes; web types via `npm run gen:api`; worker `KernelClient` |
| [`schemas/task-contract.schema.json`](schemas/task-contract.schema.json) | What one Task attempt may do: Skill, inputs, tools, budget, classification ceiling, deadline | kernel (issues), worker (obeys) |
| [`schemas/context-envelope.schema.json`](schemas/context-envelope.schema.json) | The fresh, projected context before each model step, with source versions and redactions | kernel (assembles), worker (reads) |
| [`schemas/agent-result.schema.json`](schemas/agent-result.schema.json) | What a worker submits: outputs, evidence, verifier results. No direct actions or graph changes. | worker (submits), kernel (validates) |
| [`schemas/execution-event.schema.json`](schemas/execution-event.schema.json) | The internal event log (18 types) | kernel, outbox |
| [`schemas/ui-event.schema.json`](schemas/ui-event.schema.json) | What the browser receives over SSE (23 types), already projected for the viewer | SSE hub, web stream reducer |
| [`schemas/problem.schema.json`](schemas/problem.schema.json) | RFC 9457 errors and the closed list of `code`s | kernel, web error UI |
| [`events.md`](events.md) | Event catalogue: who emits each event, who sees it, what the UI does, outbox and cursor mechanics | all |
| [`examples/`](examples) | One valid example per schema, built from the QQ-0001 RFQ drafting attempt | tests, docs |

## Kernel identifiers

Stable ids the kernel allocates (see `backend/src/aos/kernel/ids.py`). JSON Schema fields are plain `string`
unless noted; **`examples/` use short narrative ids** (e.g. `task_qq0001_assist`) for the QQ-0001 walkthrough — not
the runtime allocation shape.

| Kind | Format | Source |
| --- | --- | --- |
| Instance (job) | `<id_prefix>-<n>` | `id_prefix` from the pinned workflow's `WorkflowDefinition.spec.id_prefix` (pack schema: `WorkflowSpec.id_prefix`, default `JOB`, pattern `^[A-Z]{2,5}$` in `backend/src/aos/registry/kinds.py`). `<n>` is at least four digits, zero-padded, never truncated (`QQ-0001`, `JX-12345`). |
| Task | `task_` + 16 lowercase hex | `new_task_id()` |
| Attempt | `att_` + 16 lowercase hex | `new_attempt_id()` |
| Turn | `turn_` + 16 lowercase hex | `new_turn_id()` |
| Artifact | `art_` + 16 lowercase hex | `new_artifact_id()` |
| Pending item | `pend_` + 16 lowercase hex | `new_pending_id()` |
| Decision record | `dr_` + 16 lowercase hex | `new_decision_id()` |
| Eval run | `ev_` + 16 lowercase hex | `new_eval_run_id()` |
| Execution event | UUID | `event_id` in `execution-event.schema.json` |
| Publish request | UUID string | `registry.publish_requests.id` (`PR-12` in examples is narrative only) |

## Checks

`backend/tests/test_contracts.py`, run by `make test`, checks that:

- every schema is valid Draft 2020-12, every example validates and known-bad variants are rejected;
- every `$ref` in `openapi.yaml` resolves, every operationId is unique and every operation has a milestone;
- the M0 operations in the spec match the routes the FastAPI app actually serves.

As you implement M1 and later milestones, extend the last check so it covers that milestone's operations.
