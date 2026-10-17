# Implementing the POC with Cursor

This is the working guide for building M1–M5 in Cursor with Composer 2.5 (Agent mode). The specs say *what* to
build. This file says *how to work*: machine setup, the loop for each story, and prompts you can paste.

**What's already set up for you**

| File | What it does in Cursor |
| --- | --- |
| `AGENTS.md` | Read by the agent at the start of every chat: reading order and the four non-negotiable rules |
| `.cursor/rules/00-project.mdc` | Always on: where everything is and how to work |
| `.cursor/rules/05-story-workflow.mdc` | Always on: one story per chat, plan first, `make check`, tick `PROGRESS.md` |
| `.cursor/rules/10-kernel.mdc` | Attaches for `backend/src/aos/{kernel,api,gateway}`, migrations: transactions, versions, problems, visibility, effects |
| `.cursor/rules/20-agent.mdc` | Attaches for `backend/src/aos/worker`, `packs/`: the agent only proposes, budgets, fencing, untrusted text |
| `.cursor/rules/30-frontend.mdc` | Attaches for `web/`: match the boards, generated API types, typed blocks, pack-neutral screens |
| `.cursor/rules/40-tests.mdc` | Attaches for tests: scratch Postgres, fake model, Playwright naming |
| `.cursorignore` | Keeps vendored code, builds and `.env` out of the index |
| `docs/specs/milestones/PROGRESS.md` | Every story in build order, ticked as PRs merge |
| `.github/workflows/ci.yml` | Runs `make test` (Postgres required) and `make validate`, and builds the web app, on every PR |

## 1. Set up your machine (once)

Prerequisites: Git, Docker Desktop (Compose v2), Python 3.12+ (3.13 is what CI uses), Node 22, `make`, and `psql`
(macOS: `brew install libpq` then `export PATH="/opt/homebrew/opt/libpq/bin:$PATH"`).

```bash
git clone https://github.com/swa01wk/cenomi-aos && cd cenomi-aos
cp .env.example .env              # add OPENAI_API_KEY only when you need the real model
python3 -m venv .venv && source .venv/bin/activate
make install                      # backend (editable, dev tools) + web dependencies
make db                           # Postgres in Docker on :5432 (the tests use it)
make check                        # 82 tests + aos validate; nothing may be skipped
make up                           # full M0 stack: web http://localhost:8080, API http://localhost:8000/docs
```

Sign in as **Platform admin**, open *Domain packs*, **Validate**, then **Sync from folder**. If that works, the
machine is ready.

From M1-AG-01 on, install the agent runtime too: `python -m pip install -e 'backend[dev,runtime]'` (includes the
OpenAI client; add `anthropic` to the extras to use Claude instead).

## 2. Set up Cursor (once)

1. Open the repo root as the workspace (not `backend/` or `web/`), so the rules and `AGENTS.md` load.
2. In Cursor settings, under Rules, check the six project rules are listed and `00-project` and `05-story-workflow`
   show as always applied.
3. Pick **Composer 2.5** in the chat model menu and work in **Agent** mode, so it can edit files and run
   `make check` in the terminal.
4. Let the agent run terminal commands, but review each diff before you accept it. Keep auto-run off for `git push`
   and anything with `docker ... down -v`.

## 3. The loop for each story

One story, one branch, one chat, one PR. Small, well-scoped tasks get the best results from an agent model, and
each story is already sized for that.

1. **Pick the next unticked story** in `docs/specs/milestones/PROGRESS.md`. Branch:
   `git checkout -b m1/be-03-seat-lifecycle`.
2. **Start a new chat** (old chats carry stale context). Paste the *implement a story* prompt (section 4) with the
   story ID.
3. **Plan first.** The prompt asks for a plan before any edits. Check it names the right operations, tables,
   events and tests from the specs. Correct it in one message if not.
4. **Let it implement and test.** It should write the story's tests, then run `make check` until green.
5. **Review the diff yourself.** Use the checklist in section 5. Watch for invented endpoints or fields, logic in
   the browser, and domain names in platform code.
6. **Tick the story** in `PROGRESS.md`, commit (`M1-BE-03: Seat lifecycle`), push, and open a PR. The template
   asks for the same checks. CI must be green before merge.
7. At the end of a milestone, run the **exit gate** prompt (section 4) and tick the gate.

Bigger stories (M2-BE-01 workflow interpreter, M3-BE-01 policy engine, M3-AG-01 interrupt and resume) work better
as two chats: first the core logic with its unit tests, then the API and integration tests.

## 4. Prompts to paste

**Implement a story**

```text
Implement story M1-BE-03 from docs/specs/milestones/M1-seat-and-chat.md.

Read first: AGENTS.md, the story section, and every file it references (operations in
docs/specs/contracts/openapi.yaml, tables in docs/specs/backend/ddl/, rules in docs/specs/backend/README.md,
and for UI stories the boards in design/png and design/boards).

Before editing anything, reply with a short plan: files to add or change, operations and tables used, tests
you will write (the story's own tests first). Wait for my OK.

Then implement it, write the tests, and run `make check` until it is green with nothing skipped.
Do not invent endpoints, fields, events or tables; if the story needs one, stop and tell me which contract
file must change.
```

**Build a screen from a board** (frontend stories)

```text
Build the <Screen name> screen for story M2-FE-01.
Look: @design/png/WS-Queue.png. Exact copy, spacing and colours: @design/boards/WS-Queue.dc.html (the blue/yellow
bar at the top is a design note, not product UI). Route, components and API: @docs/specs/trace-map.md (WS-Queue)
and @docs/specs/frontend/README.md.
Use the shared components and generated API types (`npm run gen:api`). The procurement words on the board are
example data from the pack: take labels, stages and columns from the API, never hard-code them.
Plan first, then implement, then show me a screenshot at 1440 px and at phone width.
```

**Change a contract** (when a story genuinely needs something new)

```text
Story M3-BE-02 needs <field/operation/event>. Add it to the contract first, in one change:
openapi.yaml (and x-milestone), the JSON Schema and its example in docs/specs/contracts/, events.md if it's an
event, the migration if it's a column. Run `make test` (test_contracts.py must pass). Then continue the story.
```

**Check a milestone's exit gate**

```text
Go through the exit gate in docs/specs/milestones/M1-seat-and-chat.md item by item. For each, show the test or
the manual step that proves it, run it, and report pass or fail with the evidence. Fix nothing yet; list what
fails.
```

**Review my branch before the PR**

```text
Review this branch against story M2-BE-03 and the rules in .cursor/rules. Look for: endpoints/fields not in
openapi.yaml, state changes outside one transaction, permission or visibility decided in the browser, effects not
going through the gateway, domain names in platform code, missing tests from the story. List findings with file
and line; don't change code.
```

## 5. Review checklist (every PR)

- [ ] Only what the story asks for; nothing from a later milestone.
- [ ] Every new route, field, event and table exists in `docs/specs/contracts/` or the migrations, in this PR.
- [ ] State change + Decision Record + execution event + outbox rows commit in one transaction; no model or
      connector call inside it.
- [ ] Writes carry `expected_version` (or `payload_hash` / `base_version`); conflicts return 409, not overwrite.
- [ ] Visibility comes from the kernel projection; the browser never hides or computes it.
- [ ] Committed effects go through the gateway with an idempotency key; timeouts become UNKNOWN and reconcile.
- [ ] No pack, workflow, Skill or domain word in platform code (`test_pack_neutral.py`).
- [ ] UI matches the board; agent output rendered from typed blocks only.
- [ ] `make check` green with Postgres running; CI green.

## 6. Pitfalls to tell the agent about

- **Reference DDL moves into migrations.** M1-BE-01 copies `docs/specs/backend/ddl/0003_m1_seats_work.sql` to
  `backend/migrations/0003_m1.sql`. Delete the docs copy and drop its entry from `TABLES` in
  `backend/tests/test_reference_ddl.py` in the same PR. Same for 0004–0006 in later milestones.
- **The contract test grows with you.** `test_contracts.py` checks served routes against `openapi.yaml` for M0.
  When a milestone's operations are built, extend that check to the milestone (one line). This catches drift.
- **Generated types only.** Never hand-write API request or response types in `web/`; run `npm run gen:api`
  after any `openapi.yaml` change. (M1-FE-01 adds that script with `openapi-typescript`.)
- **Fake model by default.** Tests never call the real model or the network. Real-model runs are manual (the M1
  gate, M4 evals) and need `OPENAI_API_KEY` in `.env` (model `OPENAI_MODEL`, `gpt-5.4-mini` in development), plus
  the two `AOS_MODEL_PRICE_*` values so the daily USD limit works.
- **Time.** Kernel code reads time from `kernel/clock.py` so the demo clock works; never `datetime.now()`.
- **Don't relax a test to make it pass.** If a spec test seems wrong, say so in the PR and fix the spec.

## 7. Where to find things

Start at [`docs/specs/README.md`](docs/specs/README.md) for the reading order. What the POC must prove is in
[`docs/plan/north-star.md`](docs/plan/north-star.md); what it provides and what comes after is in
[`docs/plan/capabilities-and-roadmap.md`](docs/plan/capabilities-and-roadmap.md).
