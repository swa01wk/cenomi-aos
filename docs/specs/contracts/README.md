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

## Checks

`backend/tests/test_contracts.py`, run by `make test`, checks that:

- every schema is valid Draft 2020-12, every example validates and known-bad variants are rejected;
- every `$ref` in `openapi.yaml` resolves, every operationId is unique and every operation has a milestone;
- the M0 operations in the spec match the routes the FastAPI app actually serves.

As you implement M1 and later milestones, extend the last check so it covers that milestone's operations.
