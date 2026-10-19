# ADR 015 — Conversation skill for user-facing Seats

- **Status:** Proposed (19 Oct 2026, after M1)
- **Owner:** Runtime lead, with the product owner

## Context
In M1 a job's chat is tied to the Skill of the workflow's first state (`request_intake`) for the job's whole life.
Each message admits one attempt of that Skill, with its instructions, its tools and a budget per reply, against an
attempt limit that spans the whole job.

That proved the kernel controls every step. But it makes the agent narrow:
- It can't follow a person who changes topic and comes back.
- It can't answer "where are we?" or help at a later stage.
- It can't talk to anyone but the requester.

Once M2 moves jobs between states, the chat has no defined behaviour at all. The digital worker levels
(`docs/plan/digital-worker-levels.md`) ask for intent understanding and routing (Level 3), and for intent-shift
detection and continuity (Level 4).

## Decision
1. **Every user-facing Seat has a conversation skill.** The pack declares it on the Seat. It handles every message in
   the Workspace, in any state, for any participant. Its voice and role come from the pack.
2. **Step Skills become actions the conversation skill can request.**
   - When a message needs work (update the brief, look up suppliers), the conversation skill asks for that step Skill.
   - It can only ask for Skills that are the Seat's and that fit the job's current state.
   - The kernel admits the step attempt as today: grants, budget, visibility and policy, with a Decision Record when it refuses.
3. **Talk never changes state.**
   - Only decisions, completed tasks, events and timers move a job, as published in the workflow.
   - The conversation skill can explain the state, prepare a decision for a person, or park a request until the job reaches the state that handles it.
4. **The context carries the conversation.** Each attempt's envelope adds:
   - the job's goal, stage and next decision, from the published workflow;
   - the participant's role and what they may see;
   - a running summary kept by the kernel (lossy, versioned, as ADR 012 already allows);
   - the recent messages.
5. **Each message gets its own attempt budget,** instead of attempts counted per job.
6. **Visibility applies to what the agent says,** not only to what it saves: the reply is checked against the
   participant's projection before it is shown.

## Alternatives
- **Keep one Skill per state and switch the chat's Skill when the state changes.** Simpler, but the chat still breaks
  on a topic change, and people get a different agent at each stage.
- **One free agent with every tool.** Natural, but it gives up per-step grants and budgets. Rejected.
- **A separate router model in front of the Skills.** It adds a hop and a second prompt to govern; the conversation
  skill does the routing itself, inside one attempt.

## Consequences
- **Packs:** a `conversation` Skill per user-facing Seat, plus declared action Skills per state.
- **Kernel:** admission for nested step attempts within a message; the running summary writer; the per-message
  budget; visibility on reply text.
- **Evals:** a conversation suite in the gate, run per milestone.
  - Must-checks: never claims an action that didn't happen; never reveals what the participant may not see.
  - Quality checks: resumes the earlier topic; answers "where are we?" correctly; asks no question it already has the answer to.

## Verification
- A topic change mid-intake and a return to it.
- "Where are we?" at three states.
- A change of quantity after the brief is confirmed: the agent explains and prepares the decision; no state change without it.
- The buyer and the requester each chatting with their own visibility.
- All on the real model, in `make gate`.
