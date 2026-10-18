# AOS POC — Sourcing Agent on AOS

Proof of concept for the Autonomous Organization OS: a kernel that owns lifecycle, permission and
progression for digital workers (Seats), a LangGraph runtime that does bounded work inside one Task
attempt, a Console to define and govern them and a Workspace where people work with them. The
scenario is **Quick Quote** (QQ-0001): a request for quotation from intake to purchase order.

## Building the next milestones

Building with Cursor: **[`IMPLEMENTING.md`](IMPLEMENTING.md)** (machine setup, the loop for each story, prompts to
paste). Coding agents start at [`AGENTS.md`](AGENTS.md). Everything needed for M1–M5 is in the repo:

| What | Where |
|---|---|
| North star: the eight checks the POC must pass | [`docs/plan/north-star.md`](docs/plan/north-star.md) |
| What it provides now and at M5, how far it scales, what comes after | [`docs/plan/capabilities-and-roadmap.md`](docs/plan/capabilities-and-roadmap.md) |
| Specs index and reading order | [`docs/specs/README.md`](docs/specs/README.md) |
| Screen → route → API → kernel → agent trace | [`docs/specs/trace-map.md`](docs/specs/trace-map.md) |
| API (80 operations, each tagged with its milestone), JSON Schemas, events | [`docs/specs/contracts/`](docs/specs/contracts/README.md) |
| Kernel rules and reference DDL for M1–M4 | [`docs/specs/backend/`](docs/specs/backend/README.md) |
| Agent harness and the five Skills | [`docs/specs/agent/`](docs/specs/agent/harness.md) |
| Frontend routes, components, stream handling | [`docs/specs/frontend/README.md`](docs/specs/frontend/README.md) |
| Milestone stories and exit gates; progress tracker | [`docs/specs/milestones/`](docs/specs/milestones), [`PROGRESS.md`](docs/specs/milestones/PROGRESS.md) |
| Designs: 32 boards (HTML and PNG) | [`design/`](design/README.md) |
| Decisions 001–014 | [`docs/adr/`](docs/adr/README.md) |
| Cursor rules (architecture always on; kernel, agent, frontend and tests by path) | [`.cursor/rules/`](.cursor/rules) |

Plans: the Claude Doc *AOS POC Milestone Plan and North Star*. It sits alongside the *AOS POC Implementation Plan*
and the *Technical Architecture and Implementation Plan*.

## Status: milestone M0 — Foundations

| Area | What exists | Proof |
|---|---|---|
| Pack format | Ten YAML kinds (`apiVersion aos/v1`), the `procurement_demo` pack (39 files) | `make validate` → 0 errors, 0 warnings |
| `aos validate` | Schemas plus every cross-reference: Seat↔Skill↔Role work types, workflow reachability and events, governed effects, approval chains, reconciliation, org owners and placement | `tests/test_validate.py` (22) |
| Database | Six schemas (`org`, `registry`, `work`, `gov`, `evidence`, `lg_checkpoints`); kernel and worker roles; published definitions immutable; audit append-only | `tests/test_kernel_foundations.py` (18) |
| Org seed | `seed/org.yaml`: 3 departments, 4 teams, 7 people with roles | seeded idempotently on API start |
| Audit chain | Per-org SHA-256 hash chain, gap-free under a head lock; verify names the first broken record | tamper, delete and forgery tests |
| Kernel API | FastAPI: persona sign-in, `/me`, `/org`, pack validate and sync (idempotent, version pinning), pack versions and definitions, audit page and verify | `tests/test_api.py` (11) against real Postgres |
| Gateway | Credential broker: 60-second JWTs scoped to one connector, resource and action | `tests/test_connectors.py` |
| Mock connectors | ERP and mail as MCP servers, idempotent committed effects, `find_*` for reconciliation, fault switches, signed inbound replies | `tests/test_connectors.py` (12) |
| Worker | Claim → heartbeat at lease/3 → submit or fail; a stalled worker is fenced | `tests/test_worker_protocol.py` (6) |
| React shell | Persona sign-in; Console: Organization, Domain packs (validate, sync, versions, definitions), Audit (verify chain); Workspace rail | browser walkthrough, phone width included |

**M0 exit gate**

- [ ] ADRs 001–014 signed off. They're drafted in `docs/adr/` with status *Proposed*.
- [x] `aos validate` passes the pack.
- [ ] `make up` green. The Compose file passes `docker compose config`, but it hasn't been run yet
  because the build sandbox has no Docker daemon and no package registry access.

## Quick start

```bash
make up            # Postgres, kernel API, mock ERP, mock mail, web
open http://localhost:8080          # sign in as any seeded person
open http://localhost:8000/docs     # API
```

Try it: sign in as **Platform admin**, open *Domain packs*, **Validate** then **Sync from folder** and
open `v1` to browse the stored definitions. In *Audit*, **Verify chain**. Sign in as **Noura** to see
the Workspace; Console URLs fall back to the Workspace for people without a Console role.

## Local development

```bash
make install       # pip install -e backend[dev,runtime]; npm install in web/
make db            # Postgres only, in Docker (cp .env.example .env first so tests find it)
make test          # 82 tests; with AOS_TEST_REQUIRE_PG=1 database tests fail instead of skipping
make check         # test + validate: what every story keeps green
make dev-api       # :8000, AOS_DATABASE_URL defaults to postgresql://aos_kernel:…@127.0.0.1/aos
make dev-web       # :5173, proxies /api to :8000
```

To create a local database by hand, run the files in `backend/migrations/` in order as a superuser
against an empty database named `aos`. The API seeds the organization on start.

Environment: `AOS_DATABASE_URL`, `AOS_SESSION_SECRET`, `AOS_ORG_FILE`, `AOS_PACKS_DIR`,
`AOS_SEED_ON_START`, `AOS_CORS_ORIGINS`, `AOS_WEB_DIST` (serve a built web app from the API origin).

Worker (Compose defaults to `AOS_RUNTIME=fake`): `AOS_WORKER_TOKEN`, `AOS_RUNTIME=fake|langgraph`,
`AOS_CHECKPOINT_DATABASE_URL` (aos_worker role, `lg_checkpoints`), optional `AOS_FAKE_SCRIPT`
(default `assist.stream.yaml`). Real model: `OPENAI_API_KEY`, `OPENAI_MODEL`, `AOS_MODEL_PRICE_IN_PER_MTOK`,
`AOS_MODEL_PRICE_OUT_PER_MTOK` (and the same pattern for `anthropic` when `AOS_MODEL_PROVIDER=anthropic`).
OpenTelemetry tracing for attempts is deferred to M4 (M4-BE-03 / M4-AG-01).

**Sandboxes without PyPI or npm:** `make vendor` fetches FastAPI and psycopg (pure Python) from GitHub
release tags into `backend/.vendor`. `make web-offline NODE_MODULES=…` builds the web app with esbuild
alone. Neither is needed on a normal machine.

## Layout

```
packs/procurement_demo/   the domain pack (Seat, Skills, verifiers, connectors, policies, workflow, evals)
seed/org.yaml             the seeded organization (stands in for the identity provider)
backend/src/aos/
  registry/               pack kinds, loader, validator (aos validate)
  kernel/                 org, auth, audit chain, settings, stores (audit, registry)
  api/                    FastAPI app and routes
  gateway/                credential broker
  connectors/             mock ERP and mail MCP servers, inbound signing
  worker/                 worker protocol, runner, fake model
backend/migrations/       numbered SQL migrations
web/                      React app (Vite); Console and Workspace
deploy/docker-compose.yml M0 stack
docs/plan/                north star
docs/specs/               trace map, contracts, backend/agent/frontend specs, milestones M1–M5
docs/adr/                 architecture decision records 001–014
design/                   design boards (HTML source, PNG renders)
.cursor/rules/            Cursor rules
```

## Deviations from the technical plan

- **Data access:** psycopg 3 with plain SQL and numbered SQL migrations, not SQLAlchemy, asyncpg and
  Alembic. The kernel's correctness depends on exact SQL (row locks on the audit head, `SKIP LOCKED`
  claims, partial unique indexes); an ORM adds nothing there for the POC.
- **CLI:** `argparse` rather than Typer. Same commands; one dependency fewer.
- **Web routing:** hash routes in `App.tsx` for M0's few pages; M1 moves to `react-router` with real paths
  (see the frontend spec).
- **No Redis:** a Postgres outbox plus `LISTEN/NOTIFY` feeds the event stream; the outbox table is the
  source of truth (ADR 013).
- **Tests:** `unittest` (no pytest dependency); `make test` runs them all.

## Next: M1 — Seat lifecycle and the runtime

Publish requests with Risk and owner approval, Seat activation with admission gates, the Task
Contract and context envelope (ADR 003), and the LangGraph runtime running a Skill with the fake model.
Stories and exit gate: [`docs/specs/milestones/M1-seat-and-chat.md`](docs/specs/milestones/M1-seat-and-chat.md).
