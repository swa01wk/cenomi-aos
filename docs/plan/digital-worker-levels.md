# Digital worker levels 3–5 in AOS

As of 19 Oct 2026, after M1. A proposal for review, not yet in the milestone specs.

The AOS digital worker model describes three levels of capability: Level 3 *Intelligent workflow execution*, Level 4
*Context-aware, outcome-driven assistance*, Level 5 *Proactive, autonomous workflow optimization*. This document maps
every characteristic to AOS. For each it says which layer provides it, what is built or planned, what is missing, and
how it stays governed. It ends with the building blocks to add and when.

## The rule that doesn't change

Every level runs on the same split:

- **The agent proposes.** Understanding, conversation, reasoning, planning and drafting happen in the worker, inside a
  Seat's Skills, on a model.
- **The kernel decides.** Every state change, permission, external effect, approval, budget and record is the
  kernel's (ADR 001), whatever the level.
- **Autonomy grows by policy, not by code.** A Seat does more on its own when its owner changes its
  `autonomy_mode` and its policies let more actions run without a person, through a published, approved pack
  version. It never grows because the agent decides it should.

So "adding a level" means giving the agent better ways to understand and help, and giving the kernel the matching
controls. It never means letting the agent act outside them.

**Status labels** used below:
- **Built (M1):** done and tested.
- **Planned (Mn):** in a milestone spec.
- **Gap:** not planned; the proposal says where it should go.

## Level 3 · Intelligent workflow execution

*Execute business tasks reliably while reducing manual interaction.* This is what the POC is built to prove. It is
complete at M3 once the two gaps below are filled.

| Characteristic | In AOS | Status | Governed by |
| --- | --- | --- | --- |
| Natural-language intent understanding and task routing | Understanding works within a step's Skill (intake extracts the need). Routing a message to the right Skill for what the person asks is missing. | Built (M1) for one Skill; **Gap** for routing → conversation skill (A), M2 | Routing can only choose among the Seat's granted Skills; the kernel admits each attempt |
| Structured extraction from unstructured input | `request_intake` turns a free-text need into a typed brief; field descriptions from the pack guide it | Built (M1): quantity, date, site, sign-off and budget correct in 10/10 gate runs | Artifact type schema on every save; `brief_schema` verifier (M2) |
| Multi-field extraction, less repetitive questioning | Fills every field it can from one message; asks only for what's missing, at most three at a time; never invents a value | Built (M1); **Gap**: no measure of questions asked per job → add to the gate (G) | Gate must-check: nothing invented in the first draft |
| Persistent task, conversation and workflow state | Turns, artifact versions, tasks, attempts and checkpoints persist; a reload rebuilds the page. Workflow state arrives in M2. | Built (M1) / Planned (M2); **Gap**: running summary is empty, and a job allows only 3 replies → (B), M2 | Kernel owns state (ADR 001); the LangGraph checkpoint is only attempt memory |
| Deterministic business validation and permissions | Admission gates, tool grants, visibility projection and budgets (M1); verifiers (M2); policy engine (M3) | Built (M1) / Planned (M2, M3) | Kernel; Decision Records for every refusal |
| Tool/API integration for authorized actions | Reads through the gateway with short-lived broker tokens (M1); effects with exactly-once and reconciliation (M3) | Built (M1) / Planned (M3) | Gateway, grants, policy, idempotency keys |
| Human-in-the-loop confirmation and approvals | Decisions such as confirming the brief (M2); approvals bound to the payload hash (M3) | Planned (M2, M3) | Kernel-opened decisions; approval binding (ADR 006) |
| Error handling, retries, auditability, recovery | Leases, fencing, failure classes, retries, a failure notice in chat, hash-chained audit (M0–M1); failure-path suite (M5) | Built (M1) / Planned (M5) | ADR 004, 008 |
| Configurable workflows, reusable capabilities | Packs: Seats, Skills, workflows, policies, connectors, document types, published with approval; second pack with no platform change (M5 stretch) | Built (M1) / Planned (M2, M5) | Publish requests, pack-neutral platform code |

## Level 4 · Context-aware, outcome-driven assistance

*Minimize human effort and maximize individual and collaborative productivity.* About half of this is in the POC,
through evidence-backed recommendations and cross-system work. The rest needs the conversation skill and new context
building blocks.

| Characteristic | In AOS | Status | Governed by |
| --- | --- | --- | --- |
| Goal- and outcome-oriented understanding | Skills see their step's objective, not the job's goal. The conversation skill should carry the job's goal, stage and next decision. | **Gap** → (A), M2 | Goal comes from the published workflow, not the model |
| Dynamic context assembly from enterprise systems | The kernel assembles each step's context (job snapshot, messages, artifacts, tool results). Pulling facts from enterprise systems into context, like Mall C's last order for "same spec as Mall C", isn't there. | Built (M1) for job context; **Gap** for enterprise context → (C), M3–after POC | Resolvers read through the gateway with the Seat's grants; visibility projection on everything |
| Intelligent retrieval, inference and reuse | No retrieval over past jobs or documents; no memory beyond one job (ADR 012: no shared agent memory in the POC) | **Gap** → (C), after POC | Kernel-owned memory with visibility; agents never write shared memory directly |
| Adaptive conversations, minimal clarification | Asks only for what's missing; no adaptation to the person's history | Built (M1) partly; better with (B) and (C) | Gate quality checks |
| Context-aware planning, bounded decomposition | Within one reply the agent chains tools under a step and tool budget. Jobs run only the published workflow (ADR 010). | Built (M1) within a reply; **Gap**: a visible plan → (D), M2–M3 | Budgets per attempt; ADR 010: no graph changes without a person |
| Selection of authorized tools and sources | The model picks among the Skill's granted tools; anything else is refused before any effect | Built (M1) | Tool grants, gateway, Decision Records |
| Cross-system synthesis and execution | ERP + mail + quote comparison in one job | Planned (M3) | Policy, approvals, exactly-once |
| Intent-shift detection, conversational continuity | Not handled: off-topic requests reach a Skill with no tools for them | **Gap** → (A) + (B), M2 | Conversation never changes state; only decisions and tasks do |
| Assistance for multiple workflow participants | Each person sees only what their role allows (M1); buyer and approver join the job (M2). Each participant needs their own conversation with the agent. | Built (M1) / Planned (M2); **Gap** for per-participant chat → (A), M2 | Visibility per role on context and on what the agent says |
| Evidence-backed recommendations, decision support | Supplier lookup must cite sources (M2); comparison scores are recomputed by a verifier (M3); "why this outcome" from records (M4) | Planned (M2–M4) | Verifiers, Outcome Records, audit chain |
| Less repetitive investigation and admin | Follows from the rows above; needs measuring | **Gap** → (G) | — |
| Outcome-based evaluation, productivity measurement | Outcome records and dashboards (M4). No productivity measures yet: time to PO, human touches per job, questions per job. | Planned (M4); **Gap** for productivity → (G), M4 | Measured from kernel records, not model self-report |

## Level 5 · Proactive, autonomous workflow optimization

*Optimize overall business processes by anticipating needs, coordinating work, and reducing friction.* Mostly after
the POC. Two parts are already planned: preparing later stages early (M2's parallel supplier lookup) and
policy-governed autonomy (M3–M4).

| Characteristic | In AOS | Status | Governed by |
| --- | --- | --- | --- |
| Event-driven initiation and monitoring | Timers (M2) and inbound mail into existing jobs (M3). New jobs started from outside events come after the POC. | Planned (M2, M3); **Gap** for new jobs from events → (E), after POC | Event triggers declared in the published workflow |
| Proactive spotting of pending actions and bottlenecks | Pending items and queues show what waits on whom (M2); nothing watches for stuck work | **Gap** → (E), M4 first slice ("stuck job" nudge) | Watchers create pending items or nudges, never effects |
| Next-best-action prediction and recommendations | — | **Gap** → (A), suggestions per state, after M2 | Suggestions only; a person or a policy decides |
| Goal-driven planning, adaptive execution | Only the published graph runs (ADR 010) | **Gap** → (D), governed amendments, after POC | Amendments proposed by the agent, approved by a person, audited |
| Cross-functional digital worker collaboration | Delegation between Seats (`request_work`) is deferred | **Gap** → (F), after POC | Depth and cost limits; each Seat keeps its own grants |
| Intelligent delegation and coordination | As above; within a job, queues and claims route work to people (M2) | Planned (M2) for people; **Gap** for agents → (F) | Kernel routes; Seats can't grant themselves work |
| Preparing information for future stages | The parallel branch starts supplier lookup during intake as soon as the intent is clear, joined at shortlisting on the same brief version | Planned (M2) | `join_guard: same(brief_version)`; nothing runs that the workflow doesn't declare |
| Risk identification, exception detection, escalation | Verifiers send work to REWORK or EXCEPTION (M2); policies return DENY or NEVER (M3); kill switch (M4) | Planned (M2–M4) | Policy engine, verifiers, emergency control |
| Proactive follow-ups and stakeholder engagement | The quote deadline timer (M3). Agent-initiated follow-ups (chasing a supplier, reminding an approver) come later. | Planned (M3) partly; **Gap** → (E), after POC | Every outbound message is an effect: policy, approval when required, exactly once |
| End-to-end process optimization | Needs outcome data across many jobs | **Gap**, after POC | Changes ship as new pack versions through approval |
| Continuous evaluation, feedback, controlled improvement | Evals gate Seat activation (M4); the real-model gate (M1). No feedback capture from people yet. | Planned (M4); **Gap** for feedback → (G) | Improvements are new pack versions, evaluated and approved; never self-modifying in production |
| Policy-governed autonomy with human oversight | Seats declare `autonomy_mode` (supervised, assisted, autonomous); policies decide which actions need a person (M3); kill switch (M4) | Planned (M3, M4) | This row is the governance layer itself |

## What to add

Seven building blocks cover every gap above. Each keeps the rule: the agent proposes, the kernel decides.

| | Building block | What it gives the user | Kernel side | When |
| --- | --- | --- | --- | --- |
| A | **Conversation skill** on every user-facing Seat ([ADR 015](../adr/015-conversation-skill.md)) | Talk naturally: change topic, come back, ask "where are we?", get help at any stage, as any participant | Each message is one attempt of the conversation skill; step Skills are the actions it can request; talk never changes state | M2 (needed once jobs move between states) |
| B | **Conversation memory** | The agent keeps up over a long chat and across sessions | Running summary per job (kernel-written, lossy, versioned); each message gets its own attempt budget; per-person memory later, under visibility | M2 (summary, budget); after POC (per person) |
| C | **Enterprise context resolvers** | The agent already knows the relevant facts ("same spec as Mall C" → the last Mall C order) | Pack-declared resolvers that read through the gateway with the Seat's grants, projected by visibility, cited as sources | M3 for one resolver; after POC in general |
| D | **Visible, bounded plans** | The agent says what it will do and in what order, then does it | A plan is an artifact; only published task templates run; governed amendments (ADR 010 revisited) after the POC | M2–M3 (plan artifact); after POC (amendments) |
| E | **Watchers and triggers** | The agent notices stuck work, reminds people, follows up, starts work from events | Kernel timers run watcher Skills that create pending items and nudges; outbound follow-ups are effects under policy; event triggers start jobs | M4 (stuck-job nudge); after POC (rest) |
| F | **Delegation between Seats** | Digital workers hand work to each other across functions | `request_work` with depth and cost limits; each Seat keeps its own grants; full audit | After POC |
| G | **Measuring the experience** | Proof that the agent saves effort, not just that it's correct | Gate suites per level (conversation, continuity, clarification count); productivity measures from kernel records (time to PO, human touches, questions per job); feedback on replies | M2 (conversation suite); M4 (productivity, feedback) |

### Proposed changes to the plan

- **M2**:
  - add (A) the conversation skill and (B) the running summary and per-message attempt budget;
  - add (G) a conversation suite to the gate: topic change and resume, "where are we?" at each stage, a change of mind after confirmation, an out-of-scope request answered politely.
- **M3**:
  - add (C) one enterprise context resolver, the requester's past orders, so "same spec as Mall C" resolves to a real specification;
  - add (D) the plan artifact for the RFQ stage.
- **M4**:
  - add (E) the stuck-job nudge;
  - add (G) productivity measures and reply feedback.
- **After the POC**: per-person memory, retrieval, governed graph amendments, follow-ups, event-started jobs, delegation, process optimization.

With these, the POC ends at **Level 3 complete and Level 4 in large part**, every characteristic governed by the
kernel. Level 5 is designed for, and two of its characteristics are working.
