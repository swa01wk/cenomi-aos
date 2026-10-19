# What the POC provides, and what comes next

As of 17 Oct 2026. Milestone M0 is built; the specs for M1–M5 are in `docs/specs/`.

In short: the POC can run **several agents and several domains side by side**. Each domain is a **domain pack**
written as YAML, published through the Console with validation, simulation and approvals. It is **built to scale
out but not yet measured**. It runs one organization on a modular monolith, as the guidebook advises for a first
journey.

## Operating model: configuration as code, governance in the Console

A domain team writes a pack in Git: Seats (agents), Skills, workflows, policies, connectors and document types. AOS
validates and simulates it, Risk and the owner approve it, and only then can it run. People then work in the
Workspace, and owners govern in the Console: activate, pause, kill, trace, audit. There is no form-based agent
builder or visual workflow editor. Either could be added later as an editor that writes the same pack format.

## What you can do

| You want to… | Now (M0, built) | End of the POC (M5) | How |
| --- | --- | --- | --- |
| Create an organization | No: one organization, seeded | No: still one | Departments, teams and people come from `seed/org.yaml`; the Console's Organization page views them. Multi-tenancy and single sign-on come after the POC. |
| Create agents (Seats) | Define in YAML, validate, sync, view in the Console | Yes: publish, configure, test, activate, pause, kill | A Seat with its Skills, tools, authority profile and limits, in a pack. Activation needs the owner, never the person who configured it. |
| Define workflows | Define in YAML and validate | Yes: run, simulate, view the graph and each instance | A `WorkflowDefinition`: stages, guards, timers, a parallel branch with a join, participants, and who decides. Read-only graph in the Console. |
| Run several domains | Several packs can be synced and validated | Yes: two packs live at once is the M5 stretch goal | Each domain is its own pack. Platform code never names a domain (`test_pack_neutral.py`). |
| Dispatch work to the right agent and people | No | Yes, within a domain | A job goes to the Seat its workflow names. Team queues decide who picks it up; policies decide who approves. |
| Hand work between domains (agent to agent) | No | No | Delegation (`request_work`) is deferred beyond the POC. |
| Start work from outside events | No | Partly | Jobs start from New job in the Workspace. Inbound mail feeds jobs that already exist; an external event (say, a CRM lead) starting a new job is deferred. |
| Govern | Audit chain with verify; pack versions | Policies, bound approvals, exactly-once effects, reconciliation, kill switch, traces, dashboards, "why this outcome" | See `docs/plan/north-star.md` for the eight pass/fail checks. |

**What M0 contains today:** the pack format and `aos validate`, database schemas and roles, the org seed, the audit
hash chain, the kernel API (persona sign-in, organization, pack validate, sync and versions, audit verify), the
credential broker, mock ERP and mail connectors, the worker protocol with fencing, and the React shell (sign-in,
Organization, Domain packs, Audit, Workspace frame). There are 82 tests, including the contract, reference-DDL and
pack-neutral checks.

## Is it scalable?

**Built to scale out**
- **New domains are data, not code.** Kernel, API, gateway, worker and web code are pack-neutral, and a test
  enforces it.
- **Kernel API is stateless.** Several copies can run behind a load balancer.
- **Workers scale horizontally.** Claims use `FOR UPDATE SKIP LOCKED`; leases and fencing tokens stop two workers
  committing the same attempt.
- **Schedulers can run in parallel.** Timers are claimed the same way, and the M5 suite checks each fires once.
- **Tenancy-ready keys.** Nearly every kernel table carries `org_id`, so multi-tenancy is an extension, not a rewrite.
- **Versioned behaviour.** Each job pins its pack version, so new versions ship without breaking running work.

**Not built for scale yet (deliberately)**
- **One database.** A single PostgreSQL holds state, events, the outbox and audit. The event stream is
  `LISTEN/NOTIFY`, with no broker.
- **Small deployment.** One organization, one kernel service, one worker process, Docker Compose; no Kubernetes or
  Temporal.
- **Personas, not identity.** People sign in by picking a seeded persona; there's no single sign-on.

**Not measured.** The north star checks correctness: exactly-once effects, bound approvals, visibility, fencing. It
doesn't check throughput. The M5 stretch load test (below) is the first measurement. The guidebook asks for
thresholds set from measured results, not assumed ones.

## Next plan

### Inside the POC (9 weeks)

| Milestone | Weeks | Delivers |
| --- | --- | --- |
| M0 Foundations | 1 | Done: see above |
| M1 Seat and chat | 2–3 | Publish → test → activate a Seat; start a job; the agent chats and saves drafts; worker runtime on LangGraph |
| M2 Workflow layer | 4–5 | Workflows run on decisions; queues and claims; parallel branch and join; verifiers and REWORK; `aos simulate` |
| M3 Governed actions | 6–7 | Policy engine, bound approvals, exactly-once effects with reconciliation, inbound mail; the example run closes live |
| M4 Govern and observe | 8 | Kill switch, traces, dashboards, audit "why this outcome", real-model evals |
| M5 Harden and demo | 9 | Failure-path suite, replay, the 17-stop demo twice in a row |
| M5 stretch | 9 | A second pack (Sales lead qualification) with no platform change, and a first load test |

Stories, tests and exit gates for each milestone are in `docs/specs/milestones/`.

**M5 stretch load test (M5-ST-02):** many concurrent jobs across both packs, with 1, 2 and 4 workers and two kernel
copies. It records jobs per minute, attempt latency, database load and event-stream lag, and checks that every
committed effect happened exactly once and the audit chain verifies. The results go into an ADR as the first scale
baseline.

### Digital worker levels

`digital-worker-levels.md` maps the Level 3–5 characteristics of a digital worker to AOS. Inside the POC, M2–M4 make
a dispatched job feel agentic (ADR 015):
- the chat follows the job's state, for every participant;
- the agent answers "where are we?" from kernel records;
- it reports progress with decision cards in the chat;
- it answers "why?" from the explain records.

A conversation suite gates each of these milestones. Memory, enterprise context, plans, watchers and delegation
come after the POC. The POC ends at Level 3 complete and Level 4 in good part.

### After the POC

These follow the AOS proposition's Phase 3: domain expansion and enterprise hardening.

1. **Production foundations:** multi-tenancy with row-level security on `org_id`; single sign-on (OIDC) replacing
   personas; organizations created and managed in the Console; secrets management and real connector credentials.
2. **Cross-domain work:** inbound event triggers that start jobs (CRM lead, ATS application); agent-to-agent
   delegation with depth and cost limits; the Sales and HR reference packs in full.
3. **Scale:** partitioning of the events, outbox and audit tables by organization and time; worker autoscaling on
   queue depth; a message broker if `LISTEN/NOTIFY` stops being enough; Temporal or Kubernetes only if measurements
   call for them; throughput targets set in an ADR from the load-test baseline.
4. **Authoring:** a pack editor in the Console, and later a visual workflow builder, both writing the same YAML so
   review, validation and approval stay the same.
5. **Enterprise controls:** multi-level approval policies, SIEM and DLP export, SLOs, resilience drills, and
   production connectors (ERP, Graph mail, CRM, ATS) behind the same gateway.
