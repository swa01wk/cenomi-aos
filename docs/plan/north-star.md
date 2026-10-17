# North star

Source: *AOS POC Milestone Plan and North Star* (Claude Doc,
https://claude.ai/code/artifact/c3026dcd-e908-468b-abbf-774d5525a693). This file is the copy the repo is built against.

**By the end of M5, Quick Quote QQ-0001 runs end to end on the real stack.** Faisal's request in the Workspace
becomes a verified purchase order in the ERP and a handover back to him. The kernel, not the agent, decides every
transition, permission and external effect, and every step can be explained from stored evidence.

The demo that proves it is the 17 stops of the *AOS App Screens* walkthrough, played live twice in a row. CI runs the
same journey with the fake model.

QQ-0001 is an **example run** from the `procurement_demo` pack. The kernel, Console and Workspace are platform code
and never name the pack (`test_pack_neutral.py`). The stretch goal in M5 checks this with a second, smaller pack:
Sales lead qualification, run on the same build with no platform change.

| What must be true | How we measure it | Proven in |
| --- | --- | --- |
| One journey runs end to end | QQ-0001 reaches `closed` from Workspace actions alone; `aos simulate` reaches `closed` with the fake model | M2 (simulated), M3 (live) |
| Authority stays in the kernel | No state transition or external effect without a kernel decision record; a tool call outside the Seat's grants is denied before any effect | M1–M3 |
| Effects happen exactly once | An ERP timeout after commit yields exactly one PO; duplicate events yield one dispatch | M3 |
| People approve exactly what runs | An approval is bound to the payload hash; editing the payload after approval voids it | M3 |
| Data reaches only who may see it | Faisal's context and browser never hold a quote value; supplier email text is treated as data | M1, M3 |
| Work survives failure | A killed worker is fenced and a new attempt finishes with no duplicate effect; a reconnecting UI rebuilds state from snapshot + cursor | M1, M5 |
| Every outcome is explainable | "Why Najd Supplies?" is answered from records; the audit chain verifies; one Task is traced span by span | M4 |
| Autonomy is bounded | Every attempt runs under the Seat's limits (10 run minutes, 10 actions per run, USD 20 a day); hitting one stops safely and keeps the work | M2, M3 |

These are pass/fail checks. Numeric thresholds (eval pass rates, cost per Task) are set in an ADR in M5 from measured
results, as the guidebook asks.

Out of scope: multi-tenancy and row-level security, single sign-on, sandboxed code execution, agent-proposed graph
changes (ADR 010), migrating running instances (ADR 009), Temporal and Kubernetes.
