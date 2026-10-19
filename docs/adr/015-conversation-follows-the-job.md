# ADR 015 — The conversation follows the job

- **Status:** Proposed (19 Oct 2026, after M1)
- **Owner:** Runtime lead, with the product owner

## Context
In M1 a job's chat is tied to the Skill of the workflow's first state (`request_intake`) for the job's whole life.
The attempts it may use are counted per job (three in all).

Once M2 moves jobs between states, that breaks:
- After the brief is confirmed, Faisal's next message still goes to intake.
- The buyer can't talk to the agent at all.
- Nobody hears from the agent when work finishes in the background (supplier lookup, RFQ drafts, a REWORK).
- A fourth message is refused.

A dispatched job should feel agentic: the agent says what it's doing, tells people when something is ready or
needs them, answers "where are we?", and keeps up when someone changes topic. All of that has to happen without the
agent gaining any authority.

## Decision
For the POC:

1. **The chat follows the job's current state.**
   - A Seat declares a default assist Skill (for the Sourcing Agent, `sourcing_assist`).
   - A workflow state may name its own assist Skill instead (intake keeps `request_intake`).
   - Each message is handled by the current state's assist Skill, for whichever participant wrote it.
   - When the job moves, the next message uses the new state's Skill. The job's history and the person's
     visibility carry over.
2. **Each message gets its own attempt budget.** `attempts_used` counts per turn, not per job.
3. **The agent knows where the job is.** `job_snapshot` adds:
   - the workflow's goal;
   - each stage's status;
   - the open decisions, and who each one waits on;
   - the work in progress (Tasks and their state).

   So "where are we?" and "what happens next?" are answered from kernel records, not guessed.
4. **The agent reports progress.**
   - **What triggers a report:** a workflow Task completing, going to REWORK or failing, or the kernel opening or
     resolving a decision.
   - **What the kernel posts:** a short Seat turn to the participants it concerns. The text is the Task's result
     summary, written by the agent for people and checked against each reader's visibility. A decision card
     (`pending_ref` block) is added when someone must act.
   - **The data is unchanged:** progress turns are ordinary turns, so a reload shows them.
5. **Talk never changes state.**
   - Only decisions, completed tasks, events and timers move a job, as published.
   - The assist Skill can explain the state, point to the decision card, and say who can do what.
   - It can't skip, add or reorder steps (ADR 010).

**After the POC:** one conversation skill that requests step Skills as actions within a message, memory of each
person across jobs, and retrieval. See `docs/plan/digital-worker-levels.md`.

## Alternatives
- **One chat Skill for the whole job (M1 as is).** It breaks as soon as jobs move. Rejected.
- **A conversation skill that calls step Skills inside a message.** This is the right end state. It needs
  admission for nested attempts and its own eval suite, so it comes after the POC.
- **One free agent with every tool.** It gives up per-step grants and budgets. Rejected.

## Consequences
- **Contracts:** Seat `assist_skill`, workflow state `assist`, the extended `job_snapshot` resolver, and progress
  turns, which use the existing `agent.message.completed` event with a `pending_ref` block.
- **Pack:** a `sourcing_assist` Skill with read-only tools and its spec in `agent/skills/`.
- **Gate:** a conversation suite on the real model (below), with must and quality checks like M1's.

## Verification
- Seven messages in one job are all answered (the per-message budget).
- After Faisal confirms the brief, "where are we?" names shortlisting and that it waits on the buyer.
- When `supplier_lookup` completes, a progress turn appears for the buyer, with the shortlist decision card.
- A topic change mid-intake is answered, and the next message resumes the brief.
- An out-of-scope request is declined in plain words, with who can help.
- Must-checks: no progress turn or reply reveals a field the reader may not see; no reply claims an action that
  didn't happen.
