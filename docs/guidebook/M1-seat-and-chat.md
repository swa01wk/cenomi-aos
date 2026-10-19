# M1 · Seat and chat

Exit gate passed on 19 Oct 2026. Built 17–19 Oct 2026 in PRs #1–#23. Spec: [`specs/milestones/M1-seat-and-chat.md`](../specs/milestones/M1-seat-and-chat.md).

## In one paragraph

A digital worker can now be published, tested, approved and switched on through the Console, and a person can work
with it in the Workspace. The Sourcing Agent (the `procurement_demo` pack's Seat) goes from a pack folder to ACTIVE
through two approvals. The platform refuses the one person who configured it from also switching it on. Faisal then
starts a Quick Quote, chats with the agent on a real model (gpt-5.4-mini), and watches his brief build up as draft
versions beside the chat. On the real model the gate's chat passed every safety and function check in 10 of 10 runs.
It filled the brief's category correctly in 8 of 10. A run costs under a cent: USD 0.079 for ten.

## What you can expect

### Who can do what

| Person (seeded) | Where | What they can do in M1 |
| --- | --- | --- |
| Platform admin | Console → Packs, Seats | Sync the pack from its folder, validate it, request publishing; configure the Seat (six checks) and run its evals in the sandbox. Their own attempt to activate the Seat is refused (`segregation_of_duties`), recorded as a decision and audited. |
| Risk reviewer | Console → Packs, Seats | Approve the *Policies* part of the publish request; approve the Seat after its evals. |
| Head of Procurement | Console → Packs, Seats | Approve the *Seats and workflows* part (publishing the pack); activate the Seat; see each Seat's spend today against its daily limit. |
| Faisal (requester) | Workspace | See the Sourcing Agent under *Digital workers*; start a Quick Quote with a need; chat; see the brief's versions beside the chat; come back later or reload and find the same conversation. |

### What a chat is like

- **First reply:**
  - Faisal writes his need, for example *"We need 40 cleaning trolleys for Mall A, same spec as Mall C"*.
  - The agent looks the category up in the ERP; categories are broad, so it lists them all if a search finds nothing.
  - It saves a first brief, with no delivery date or sign-off it wasn't given.
  - It asks for what's missing, up to three questions.
- **Second reply:** Faisal answers, and the agent saves a new brief version with his answers in the right fields. It replies in a sentence that streams in as it's written.
- **Budget:** a budget Faisal mentions goes into the internal `budget_guidance` field and nowhere else in the brief.
- **Timing:** each reply takes a few seconds. A whole two-message chat took 9–16 s in the gate runs.
- **When a reply can't be finished** (a budget limit, a failure the worker won't retry, a worker that stopped
  responding), the chat says so in a red notice from the agent instead of staying silent. Details stay in the
  execution events.
- **Every model call is priced:** today's spend shows on the Seats page, and the Seat stops at its daily limit (USD 20).

### Try it

```bash
make up                     # the stack with the scripted model (what CI uses)
make gate                   # the exit gate on the real model: fresh stack, publish, activate, Faisal's chat, checks
make gate RUNS=10           # the chat ten times on the same stack, with each check's pass rate
make model-fake && make up  # back to the scripted model
```

`make gate` asks for an OpenAI key once, if `.env` doesn't have one. Model and prices default to gpt-5.4-mini at its
list price: USD 0.75 in and 4.50 out per million tokens, as of Oct 2026. Open http://localhost:8080 and pick a
person to sign in; there are no passwords in the POC.

## What not to expect yet

| Limit | Why | Where it's fixed |
| --- | --- | --- |
| The brief is never confirmed and the job stays in *Intake*. | Decisions and workflow transitions are M2. | M2-BE-01, M2-BE-04 |
| The agent sometimes leaves the brief's category empty (2 of 10 runs). It invented a category id once (`CAT-0000` in a first draft, fixed in its second). | Model judgement on one field. | The brief verifier and confirm decision (M2-AG-03, M2-BE-04) catch a missing or unknown category before anything goes out. |
| A job takes at most 3 agent replies; a 4th message is refused with "No attempts left". | Admission counts attempts per assist task, which spans the whole job, not per message. | Give each message its own attempt budget (M2; the fake scripts index by attempt number, so it needs care). |
| Only the intake step runs (`request_intake`). No supplier search, RFQs or quotes. | Task Skills and the task lane come with the workflow. | M2 (supplier_lookup, rfq_draft), M3 (send, quotes, PO) |
| No policy engine, approvals or external effects; the ERP and mailbox are mocks. | | M3 |
| Buttons the kernel would refuse are not disabled in advance; the refusal shows after the click. | The UI has no per-action "can act" flags yet. | Follow-up (kernel to provide the flags) |
| Notifications and the Inbox; one event stream per job only, no per-user stream. | | M2 (user stream) |

## How it was verified

### Exit gate

| Item | Evidence |
| --- | --- |
| The pack is published through a request approved by Risk and the Head of Procurement | e2e stop 1 (`stop-01-publish.spec.ts`), `test_publish_requests` |
| The platform admin configures and tests the Seat; their activation is refused and audited | e2e stop 2, `test_seat_lifecycle` (`segregation_of_duties`, Decision Record, `seat.activate.denied`) |
| The Head of Procurement activates it; the agent appears in Faisal's Workspace | e2e stops 3 and 4 |
| Faisal starts a Quick Quote and chats on the real model; replies stream; brief v1 and v2 are saved | `make gate` (`m1-gate-real-model.spec.ts`), results below |
| A reloaded job page rebuilds from snapshot + cursor; a stalled worker is fenced | `make gate` and e2e stop 5 (reload); `test_stalled_worker_is_fenced_and_cannot_commit` |
| `make test` and contract tests green | CI on every PR (backend, web, e2e jobs) |

### Tests at the end of M1

- **Backend:** 324 tests in 38 files, covering contracts, the kernel, the API, connectors and the worker. That includes a test of the gateway's real HTTP path against a running mock ERP.
- **Web:** 115 unit tests in 43 files (Vitest).
- **End to end:**
  - 18 Playwright tests run in CI on the scripted model: sign-in and routing, plus walkthrough stops 1–5.
  - The real-model gate test runs locally only (`make gate`), because it needs an API key.

### The real-model gate

The gate test checks what happened and what the brief holds, not the model's wording. Checks come in two kinds:

- **Must-checks**, which every run has to pass:
  - replies signed with the Seat's name and streamed; no failure notices, no JSON in replies;
  - brief v1, then a newer version; a reload rebuilds the page;
  - nothing invented in the first draft; the budget appears in no other field;
  - no failed attempts, budget stops, denied tools or fencing; one attempt per message;
  - per reply: at most 6 model steps, 2 brief saves, and no repeated identical tool call;
  - spend above zero.
- **Quality checks**, which must pass in at least 80% of runs (`GATE_MIN_QUALITY`): the final brief's quantity, category, delivery date and site, quality sign-off and budget, and that every category saved is one the ERP returned.

| Run | Result | Notes |
| --- | --- | --- |
| First pass (1 run) | passed | Brief v1 → v2, both replies streamed, USD 0.0061 |
| RUNS=10, round 1 | 4 / 10 | 5 failures were the test (a locator also matched a reply quoting the need); replies pasted the brief as JSON; one category missing |
| RUNS=10, round 2 | 4 / 10 | Every other check 10/10; category empty in 6 runs |
| RUNS=10, round 3 | 5 / 10 | Category never set in the 5 failures (not lost: `v1=∅, v2=∅`) |
| RUNS=10, round 4 | 8 / 10 → **passed** | Every must-check 10/10; category 8/10, above the 80% bar. USD 0.079 for ten runs |

## Development report

### How it was built

| PRs | Dates | What |
| --- | --- | --- |
| #1–#11 | 17 Oct | Kernel: work state and outbox, publish requests, Seat lifecycle, jobs and conversation, worker protocol, context assembler and visibility, gateway reads |
| #12–#15 | 17–18 Oct | Agent: worker process and runtime, Postgres checkpointer, the assist graph on a real model, `request_intake` in chat |
| #16–#20 | 18–19 Oct | Web: Vite and the router (with Playwright), shared components, the Console publish and Seats pages, the Workspace start and chat |
| #21 | 19 Oct | Exit gate: the Compose worker runs the real model, `make gate`, and the fixes below |
| #22, #23 | 19 Oct | The gate as an eval suite (`RUNS=n`, must and quality checks), failed replies shown in chat, and the fixes below |

Each story followed the same loop: a planning prompt and plan review, implementation, code review and fixes, CI green on
backend, web and e2e, then a merge commit. Stories ended with screenshots checked against the design boards.

### What the real model found

The scripted model in CI follows a script and ignores tool results. The real model doesn't, and running it end to end
found problems no earlier test could see:

| Symptom | Cause | Fix |
| --- | --- | --- |
| The worker always ran the scripted model on the stack | Compose hard-coded `AOS_RUNTIME=fake` and passed no key | Runtime, key, model and prices pass through from `.env`; `make model-real` / `model-fake` |
| A plain-text tool result failed the call | The gateway parsed any text starting with "n" as JSON | Parse only JSON-looking text |
| The 4th search of a reply was refused | Each tool call was counted twice against the 6 allowed per reply (the request event and the gateway) | Gateway tools count once, at the gateway |
| The model searched item names against broad category names | Connector tools reached the model with no description | Tools carry descriptions from the pack (an empty query lists every category) |
| The agent repeated the same search | Each model step starts from the context, not a chat history, and a tool result didn't say what was searched | Results carry their arguments; identical repeats are skipped with a note |
| The agent asked questions before seeing a lookup or saving | A question in the same step as a lookup ended the reply first | The question is held until the lookup's result is in; save before asking |
| **Every ERP call on the stack failed** | The MCP 2.x client yields two streams and the gateway unpacked three. Tests used an in-memory client and the scripted model ignores results, so nothing caught it | Fixed, with a test of the real HTTP path against a running mock ERP |
| The agent saved the brief six times and never replied | It couldn't see that this reply had already saved it | The reply's own actions are listed in every step (`your_actions_this_reply`); identical saves are skipped |
| No streamed text ever appeared | Deltas are keyed by the message being answered; the UI only drew live text for agent turns | Live text shows under the answered message and clears when the reply completes |
| A failed reply left the chat silent | Nothing told the participant | The kernel posts a notice turn |
| Replies pasted the brief as JSON | No rule against it; the kernel's own tools had no descriptions | A plain-language rule; `save_draft` and `ask_question` are described |
| A later save lost the category | Each save replaced the whole draft, and models null the fields they aren't touching | A save is an update: fields left out or blank keep their value |
| The category was often never set | The model saw a bare field called `category` | Pack fields can carry descriptions, and the model sees them |

Earlier, while building the Workspace and Console, review and Playwright caught:

- **A write committed after the response:** the request transaction committed after the HTTP response was sent. A page reading straight after a write could miss it.
- **Dropped stream events:** the stream cursor moved before de-duplication, so every outbox event was dropped.
- **Wrong labels on screen:**
  - stages out of order;
  - the Seat's id instead of its name;
  - "by att_…" in version lists;
  - a "USD 0.00 of 0.00" daily limit.

### Decisions made in M1

- **A save is an update.**
  - `save_draft` merges the model's fields onto the draft's current content; blanks never clear a field.
  - The exception is a draft with fields hidden from the Seat: then the content is saved as sent, so hidden fields aren't lost.
- **What the model sees each step:**
  - each step is built from the context envelope, not from a chat history;
  - so the envelope carries each tool result's arguments and the reply's own actions (`harness.md`).
- **Live text:** `agent.message.delta` is keyed by the turn being answered; the reply's own turn exists only once it completes (`events.md`).
- **Failure notices:** a reply that ends for good without an answer gets a notice turn (`events.md`, rule 5).
- **Real-model gate:** must-checks pass every time, quality checks at a threshold. Exact numbers for the POC are set in M5 from measured results, as `north-star.md` says.

## Carried into M2

- Each message gets its own attempt budget (the 3-replies-per-job limit).
- The brief verifier and confirm decision catch a missing or unknown category.
- Per-action "can act" flags from the kernel, so the UI can disable what would be refused.
- The per-user event stream and the Decision card.

## Reference

| To | Use |
| --- | --- |
| Run the stack (scripted model) | `make up`, then http://localhost:8080 |
| Run the exit gate on the real model | `make gate` / `make gate RUNS=10` (`GATE_MIN_QUALITY=0.9` to raise the bar) |
| See why the agent didn't reply | `make diag`: worker log, model and tool events, the last reply's tool calls with arguments and results |
| Real-model smoke tests | `make smoke-real` |
| Gate test, report and runner | `web/e2e/m1-gate-real-model.spec.ts`, `web/e2e/gate-db.ts`, `scripts/gate.sh`, `scripts/gate-report.py` |
| The agent's prompt and graph | `backend/src/aos/worker/prompts/assist_v1.jinja`, `backend/src/aos/worker/graphs/assist.py` |
| The intake skill and the brief | `packs/procurement_demo/skills/request_intake/`, `packs/procurement_demo/artifact_types/brief.yaml` |
