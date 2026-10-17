# Instructions for coding agents

This repo is the AOS POC. Read, in order:

1. `docs/plan/north-star.md` — what the POC must prove.
2. `docs/specs/README.md` — how the specs fit together.
3. The milestone you're working on: `docs/specs/milestones/M<n>-*.md`, and its story in `PROGRESS.md`.

How to work a story (plan, implement, `make check`, record) is in `IMPLEMENTING.md`.

Rules that apply everywhere (details in `.cursor/rules/`):

- The kernel decides; the agent proposes. Nothing but the kernel commits state.
- The platform is pack-neutral. The procurement scenario is example data from `packs/procurement_demo`; platform
  code never names it (`test_pack_neutral.py`).
- Build against the contracts in `docs/specs/contracts/`. Don't invent endpoints, fields, events or tables; if one is
  missing, add it to the contract in the same change.
- Match the designs in `design/` exactly; reuse the shared components.
- Keep `make test` and `make validate` green.
