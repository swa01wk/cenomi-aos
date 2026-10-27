# Skill: sourcing_assist

The Sourcing Agent's default assist Skill (ADR 015). It handles every conversation turn that a state's own assist
Skill doesn't. It keeps people informed: where the job is, what happens next, what needs them, and what it can't do.
**Milestone:** M2 (states after intake), M3 (governed actions), M4 (`explain_outcome`). **Stops:** 6–14 in the
conversation.

## Where it runs

| Run | Created by | On behalf of | Ceiling |
| --- | --- | --- | --- |
| Assist attempt | a participant's turn in a state without its own `assist` Skill | the participant who wrote | that participant's visibility |

During intake, the requester's turns still go to `request_intake` (its own `assist`).

## Contract

- **Inputs:** `job_snapshot` (goal, stages, open decisions and who they wait on, work in progress), `recent_messages`,
  `supplier_list` when one exists, and other artifacts named in `reads`, each projected for the participant.
- **Tools:** read-only. `read_artifact`, `browse_categories`, `get_supplier_history`, and `explain_outcome` from M4.
  No `save_draft`, no actions.
- **Budget per attempt:** 20,000 tokens · USD 0.50 · 120 s · 4 steps · 4 actions · 1 retry. One attempt per message.
- **Output:** a reply (text blocks; `pending_ref` when pointing at an open decision).

## Behaviour the model must follow

| Rule | Enforced by |
| --- | --- |
| "Where are we?" and "what's next?" are answered from `job_snapshot`, never guessed | conversation suite (quality) |
| Points to the open decision and who it waits on; never says it can decide for them | conversation suite (must: no claimed action) |
| Out-of-scope requests are declined in plain words, saying who can help | conversation suite (quality) |
| Never says a step happened unless the records show it | standing rule; conversation suite (must) |
| Never shows a field the participant can't see | visibility projection on every input; conversation suite (must) |
| Plain sentences; no JSON, field names or document dumps | standing rule; gate must-check |
| "Why is X ranked …?" answered from `supplier_list` and the rubric above; no new ERP lookups | conversation suite (stop 6) |

## Progress turns (kernel, not this Skill)

Progress turns are posted by the kernel from Task result summaries (M2-BE-07), not written by this Skill. This Skill
reads them like any other turn, so a question right after a progress turn is answered in its light.
