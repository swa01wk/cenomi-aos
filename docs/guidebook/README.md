# Guidebook

One chapter per milestone, written when the milestone's exit gate passes. Each chapter says what the milestone
delivered, how it was verified, what happened while building it, and what someone trying it can expect. The
milestone files in `specs/milestones/` say what to build; the guidebook records what was built and what it is like
to use.

Not to be confused with the *Agentic Architecture Engineering Practices Guidebook* (a source document in the AOS
project), which is about how to build agentic systems in general.

| Milestone | Chapter | Exit gate |
| --- | --- | --- |
| M0 Foundations | (before the guidebook; see `specs/milestones/PROGRESS.md`) | done |
| M1 Seat and chat | [M1-seat-and-chat.md](M1-seat-and-chat.md) | passed 19 Oct 2026 |
| M2 Workflow layer | | |
| M3 Governed actions | | |
| M4 Evidence and trace | | |
| M5 End to end | | |

## Writing a chapter

Write it in the PR that closes the milestone's exit gate, or right after. Use these sections, in this order:

1. **In one paragraph**: what changed for the people using the product, and the headline numbers.
2. **What you can expect**: what each person can do now, how to try it, and what it feels like (timings, cost).
3. **What not to expect yet**: limits and known issues, each with where it gets fixed.
4. **How it was verified**: the exit gate item by item with its evidence, test counts, and any real-model results.
5. **Development report**: the PRs, what broke along the way and why, and the decisions it led to.
6. **Carried into the next milestone**: open items, each with a home.
7. **Reference**: the commands and files someone needs to try or change it.

Facts only: every number comes from a test run, CI or a PR, and says where. Name the people by their role in the
walkthrough (Faisal, the Head of Procurement), not by account.
