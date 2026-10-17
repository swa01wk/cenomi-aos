# M4 · Govern and observe (week 8)

**Goal:** operators can stop, trace and explain everything.

**Exit gate**
- [ ] A kill on the Seat during QQ-0003's chat refuses the next turn with a plain notice, fences running attempts and
      makes the gateway refuse in-flight actions; QQ-0001's records are untouched; lifting needs a second person.
- [ ] One Task of QQ-0001 is traced span by span from admission to submit, model calls included.
- [ ] "Why Najd Supplies?" is answered by walking back from the Outcome Record; the audit chain verifies.
- [ ] Behavioral evals run on the real model for every Skill and their results gate Seat activation.

**Walkthrough stops made real:** 3 (pause, kill), 15 (trace), 16 (explain), 17.

---

## Backend
### M4-BE-01 Emergency control
- Apply `ddl/0006_m4_govern.sql`. Kill switches and pause/resume: admission gate 1, fencing of running attempts,
  `cancel_requested` on heartbeat, broker revocation (`credential_revocations.not_before`), gateway refusal.
- Operations: `listKillSwitches`, `activateKillSwitch`, `liftKillSwitch`, `pauseSeat`, `resumeSeat`.
- **Tests:** kill during an attempt → the next worker call is fenced and no effect runs; lift by the activator → 403.

### M4-BE-02 Outcome and explain
- Outcome Record on close; `explainOutcome` walks Decision Records, approvals, verifications, drafts and turns back
  to the first message, each with the pack version in force.

### M4-BE-03 Telemetry and dashboards
- OpenTelemetry in API, kernel, worker and gateway (OTLP to Jaeger in Compose); `getTaskTrace`; `getDashboard` for
  seat-health, stage-times and approvals with thresholds from the pack's `observability`.

### M4-BE-04 Evals for real
- `aos test` CLI and `runSeatEvals {model: real}`; behavioral suites per Skill (see each Skill spec) added to the pack
  as a new version; results stored in `registry.eval_runs`.

## Agent

### M4-AG-01 Spans and behavioral evals
- GenAI span attributes in the graphs; behavioral eval cases per Skill; prompt capture stays off.

## Frontend

### M4-FE-01 Govern screens
- Emergency page (Console-Emergency), Seat page pause and kill, `SeatNotice` on Workspace screens, Audit explain view
  (Console-Audit), instance trace waterfall (Console-Instance), Observability dashboards (Console-Observability).
- **Playwright:** `stop-15` to `stop-17`.
