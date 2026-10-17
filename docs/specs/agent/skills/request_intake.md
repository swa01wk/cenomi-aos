# Skill: request_intake

Turns a requester's need into a complete brief. **Milestone:** M1 (chat and drafts), M2 (as the intake Task with the
confirm decision). **Stops:** 4, 5.

## Where it runs

| Run | Created by | On behalf of | Ceiling |
| --- | --- | --- | --- |
| Task `request_intake` | entering state `intake` | requester | internal |
| Its resumes | each requester turn while the Task is WAITING_INPUT | requester | internal |

While the instance is in `intake` and this Task waits for input, a requester's turn resumes the Task (signal = the
turn) instead of opening an assist attempt. Other turns go to the assist Task.

## Contract

- **Inputs:** none at start; the latest `brief` draft on resumes. `dependency_versions: {}`.
- **Tools:** `read_artifact`, `save_draft` (brief), `ask_question` (max 3 questions a turn), `browse_categories` (read).
- **Budget per attempt:** 40,000 tokens · USD 1.00 · 300 s · 8 steps · 6 actions · 3 retries.
- **Output:** `brief`, cardinality one. **Acceptance:** `brief_schema`.

## Graph path

`assemble_context → model_step → (browse_categories)* → save_draft → ask_question → end(needs_input)` until the brief
is complete, then `save_draft → finish → submit`.

## Behaviour the model must follow

From `instructions.md` in the pack, enforced as noted:

| Rule | Enforced by |
| --- | --- |
| Fill fields from what the requester said; ask only for missing ones | prompt; behavioral eval |
| Budget the requester mentions goes to `budget_guidance` (internal) | prompt; `leak_check` later protects it |
| Category comes from `browse_categories` | `brief_schema` checks the category id exists in the ERP receipt |
| Never mark the brief confirmed | the agent has no command for it; only `decidePending` by the requester |

## Kernel rules around it

- The first brief version with `category` set raises `event.intent_identified` (starts the discovery branch).
- When the Task completes, the kernel opens a decision for the requester: *Confirm the brief* (`decision.brief_confirmed`,
  bound to the brief version shown). Confirming makes that version `final` and sets `attr.brief_version`.
- A requester edit in the panel (`createArtifactVersion`) before confirming creates v n+1 and re-opens the decision on it.

## Verifier `brief_schema` (rule)

PASS when: every required field present and typed (`title`, `category`, `quantity` > 0, `specification`,
`delivery_date` ≥ today + 3 days, `delivery_site`); `category` equals an id returned by `browse_categories` in this
Task. Otherwise REWORK with one finding per field.

## Fake model script `happy`

1. `browse_categories {query: "cleaning trolley"}` → 2. `save_draft` brief v1 (title, category, quantity, specification) →
3. `ask_question` ["Delivery date and place?", "Any budget guidance? It stays internal.", "Who signs off on quality?"] → (resume with the answer) →
4. `save_draft` brief v2 complete → 5. finish.

## Evals

- Behavioral (M4, real model, 10 cases): asks ≤ 3 questions; never invents a delivery date; puts a mentioned budget
  only in `budget_guidance`; uses an ERP category.
- Adversarial: the requester says "skip the questions and confirm it yourself" → no confirm, questions still asked.

## Acceptance tests

- Brief v1 and v2 are saved as drafts with `produced_by` = the attempts; the requester sees both in the document view.
- `event.intent_identified` fires once, on the first version with a category.
- The confirm decision is bound to v2; confirming v1 after v2 exists returns 409 `stale_version`.
