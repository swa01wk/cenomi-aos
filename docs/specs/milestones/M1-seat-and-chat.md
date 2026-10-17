# M1 · Seat and chat (weeks 2–3)

**Goal:** Faisal chats with an active Sourcing Agent, and his brief is saved as draft versions.

**Exit gate**
- [ ] The procurement_demo pack is published through a publish request approved by Risk and the Head of Procurement.
- [ ] The platform admin configures and tests the Seat; their activation is refused (`segregation_of_duties`) and audited.
- [ ] The Head of Procurement activates it; the Sourcing Agent appears in Faisal's Workspace.
- [ ] Faisal starts a Quick Quote and chats on the real model; replies stream; brief v1 and v2 are saved as drafts.
- [ ] A reloaded job page rebuilds the conversation from snapshot + cursor (C10). A stalled worker is fenced.
- [ ] `make test` green, including the new API and worker tests; contract tests green.

**Walkthrough stops made real:** 1 (publish), 2, 3, 4, 5 (chat and drafts; the confirm decision comes in M2).

**Out of scope:** workflow transitions, decisions, claims, timers (M2); policy engine, approvals, effects (M3).

**Prerequisites:** package registries reachable (PyPI, npm) or a machine with Docker; `OPENAI_API_KEY` and
`OPENAI_MODEL` (development uses `gpt-5.4-mini`) for the real-model part of the gate.

---

## Backend

### M1-BE-01 Foundations for work state
- Apply M1 work-state DDL as `backend/migrations/0003_m1.sql` (moved from the former reference file `ddl/0003`).
- Add `kernel/ids.py`, `kernel/outbox.py` (stream heads, outbox rows, `NOTIFY aos_outbox` after commit),
  execution-event writer, `api/problems.py` (`KernelProblem` → `application/problem+json`, `trace_id`).
- **Done when:** a test writes a state change, an execution event and two outbox rows in one transaction and a
  rolled-back transaction leaves none of them.

### M1-BE-02 Publish requests
- Operations: `requestPublish`, `listPublishRequests`, `approvePublishPart`, `rejectPublish`.
- Parts: `policies` (role `risk`) when the version has Policy objects; `seats_and_workflows` (the pack owner).
- All parts approved → `pack_versions.status = published`, `published_at`; definitions immutable (M0 trigger).
- Audit: `pack.publish_requested`, `pack.publish_part_approved`, `pack.published`.
- **Tests:** requester cannot approve any part (403); a rejected part closes the request; publishing twice is a no-op.

### M1-BE-03 Seat lifecycle
- Publishing creates `registry.seats` rows (DRAFT) for each Seat definition.
- Operations: `listSeats`, `getSeat`, `configureSeat` (six checks, see backend spec), `runSeatEvals`, `approveSeat`
  (risk), `activateSeat` (owner, never the configurer; Decision Record; `seat.state_changed`).
- Eval runner, M1 scope: runs suites through the worker with the fake model. Expectations the kernel can't check yet
  (`policy_result` before M3, a full `dry_run` before M2) are reported `deferred`; they block activation only when
  `AOS_EVAL_STRICT=1` (default from M3).
- **Tests:** activation by the configurer → 403 with a Decision Record and audit `seat.activate.denied`; owner activation
  → ACTIVE; `expected_version` mismatch → 409.

### M1-BE-04 Jobs and conversation
- Operations: `listDigitalWorkers`, `listMyInstances`, `startInstance`, `getInstance`, `listTurns`, `postTurn`,
  `streamInstanceEvents`, `getArtifact`, `getArtifactVersion`.
- `startInstance`: admission gates 1–8 (backend spec), pin the pack version, bind the requester, create the assist Task
  whose Skill is the initial state's first template (`request_intake`), store the first turn and admit an attempt.
- Snapshot projection: stages from the workflow's states with `done/current/next`; turns filtered by `audience_roles`;
  artifacts through the visibility projection. `ArtifactSummary.view` is built from the pack's `ArtifactType`: view
  type, columns, export, and fields with labels (the pack's `label`, or the field name humanized). Fields the caller
  may not see are left out.
- SSE hub (`sse.py`): cursor resume, `snapshot.required` for unknown cursors, 15 s heartbeat comments, delta relay.
- **Tests:** a second `startInstance` with the same Idempotency-Key returns the first instance; a non-requester role
  gets 403; Seat PAUSED → 403 `seat_not_active`; stream resumes from a cursor without duplicates.

### M1-BE-05 Worker protocol
- Operations: `claimAttempt`, `heartbeatAttempt`, `getAttemptContract`, `assembleContext`, `postAttemptEvents`,
  `callTool`, `saveDraft`, `askQuestions`, `submitResult`, `failAttempt`; worker service token (aud `aos-worker`).
- Fencing on every call; lease 90 s; scheduler loop expires leases every 5 s; budget reserve at admission, settle on end.
- Submit pipeline steps 1–3 (schema, freshness, verifier — no verifier for assist Tasks).
- **Tests:** stale fencing token → 409 `fenced` + `AttemptFenced`; expired lease → new attempt with a higher token and
  the late worker's submit refused; budget reservation fails admission at the daily limit.

### M1-BE-06 Context assembler and visibility
- `kernel/context.py`: build `ContextEnvelope` (schema) from the contract, resolvers the Skill `reads`, artifacts
  projected for `on_behalf_of` and the classification ceiling, `redactions` listing every removed field.
- `artifacts.project()` shared by artifact reads and the assembler.
- **Tests:** envelope validates against the schema; a requester envelope never contains `restricted` fields and lists
  them in `redactions`; an RFQ-draft envelope (shareable ceiling) has no `budget_guidance`. C07 (adapted from
  cross-tenant to cross-job): an assist turn on QQ-0001 that asks about a job the person doesn't take part in gets
  nothing from that job; the resolver refuses it and the refusal is audited.

### M1-BE-07 Gateway reads
- `gateway/gateway.py`: for `callTool`, check the tool is in `contract.allowed_tools` and the authority profile grants
  ALLOW for its resource and action (full policy engine in M3); mint a broker token; call the MCP server; wrap
  external text as untrusted; emit `ToolAuthorized` / `ToolDenied` / `ToolCompleted`.
- **Tests:** a tool outside the contract → 403 before any connector call (guidebook C02); token expires after 60 s.

## Agent

### M1-AG-01 Runtime and worker process
- `AgentRuntime` protocol; `LangGraphRuntime`, `FakeRuntime`; HTTP `KernelClient` implementing `protocol.py`;
  `python -m aos.worker` entry point; lanes `assist`, `task`; failure classes aligned with the contract.
- **Tests:** the M0 worker-protocol tests still pass against the HTTP client and an in-process kernel.

### M1-AG-02 Assist graph and model
- Assist graph (harness spec), prompt template `assist_v1`, model registry (`enterprise_reasoning` → the provider
  and model in `.env`, OpenAI `gpt-5.4-mini` in development; harness spec, ADR 014), streaming deltas, `ModelInvoked` with tokens and cost, step and token budget checks.
- **Tests:** fake model reply streams as deltas then a completed turn of typed blocks; the step budget stops a loop.

### M1-AG-03 request_intake in chat
- Skill spec `agent/skills/request_intake.md`, assist mode: `browse_categories`, `save_draft` brief, `ask_question`.
  Fake script `happy`.
- **Tests:** brief v1 then v2 saved with `produced_by` the attempts and `inputs` recorded.

### M1-AG-04 Checkpointer
- `AsyncPostgresSaver` on schema `lg_checkpoints` as `aos_worker`; `thread_id` rule from the harness spec.

## Frontend

### M1-FE-01 Move to Vite and the router
- Install deps (`npm install`), keep `build-offline.mjs` as a fallback, add `react-router`, TanStack Query,
  `openapi-typescript` (`npm run gen:api`), `openapi-fetch`; `tokens.css` from the Components board.
- Port M0 pages (sign-in, Org, Packs, Version, Audit, Workspace frame) to real routes.

### M1-FE-02 Shared components
- Everything on the Components and States boards that M1 screens use (frontend spec table), with component tests.

### M1-FE-03 Console: publish and Seats
- Packs page: publish request panel (stop 1). Seats list (Console-Seats). Seat page: lifecycle, checks, eval runs,
  approve, activate with the segregation refusal (stops 2, 3).

### M1-FE-04 Workspace: start and chat
- Rail with digital workers and My jobs; New job (stop 4); job page with conversation, streaming, composer, document
  view of brief versions and artifact chips (stop 5 without the decision card).
- Work panel view registry keyed by `view.type`, with `DocumentView` and the `FieldListView` fallback (frontend spec,
  *Views from the pack*). Stage stepper from `snapshot.stages`. No string in `web/src` names the example pack.
  **Test:** `views.test.tsx` renders the views from fixtures with made-up field names.
- **Playwright:** `stop-01` … `stop-05` (partial) against `make up` with the fake model.

## Definition of done
- Every operation marked M1 in `openapi.yaml` is served and covered by a test; contract tests green.
- The gate demo runs from a fresh `make up`: publish → configure → refused → activate → Faisal chats → drafts saved.
