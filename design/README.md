# Designs

These are **AOS platform screens**. They work the same for any digital worker and any domain pack. To show them
in motion, the boards follow one example run from the `procurement_demo` pack: Quick Quote QQ-0001,
40 cleaning trolleys. Names such as "Quick Quote", "Sourcing Agent" and "RFQ", the fields and the figures are example
data supplied by that pack. They aren't part of the screen design.

The source of truth is the design canvas **AOS App Screens** (claude.ai, private to its owner; ask for access):
https://claude.ai/artifact/P39ZpjDLK4xbvGqx1ajUzg. Open it to click through. Every board is interactive and
links to the next.

This folder is a snapshot for building against:

- `boards/*.dc.html`: each board's source. It's plain HTML with inline styles inside `<x-dc>`. Read it for exact
  copy, spacing, colours and structure. It needs the canvas runtime to render, so use the PNGs to see the screens.
- `boards/canvas.json`: the canvas layout, with board order and titles.
- `png/*.png`: static renders at 1440 px. These use system fonts; the canvas uses IBM Plex.

Each board carries a bar on top that is **not part of the product**:
- yellow bar (walkthrough boards, stops 1–17): the screen's name, what happens at this stop in the example run, and
  what the kernel did;
- blue bar (platform screen boards): the route, the API calls and the milestone that builds the screen.

## Platform and pack

| Built once, in the platform | Supplied by the domain pack (example values) |
| --- | --- |
| Every Console screen | Workflow names, stages and who may start them (Quick Quote) |
| Workspace shell, My jobs, New job, team queues, inbox | The Seat, its Skills and prompts (Sourcing Agent) |
| Job page: conversation, work panel, pending items, stage stepper | Document types, their fields and the view for each (brief, RFQ email, comparison) |
| Decision and approval cards, multi-step chains | Field visibility per role (a requester never sees prices) |
| Document views: `document`, `sheet`, `tracker`, `message_composer`, `record_preview` … | Policies and approval chains (two-step PO above SAR 25,000) |
| Refusal, conflict, error and loading states; tokens and components | Connectors and team queues (mock mail, mock ERP, Sourcing) |

**Rule for the frontend:** no component is named after or written for the example pack. A screen gets its stage
names, labels and document layout from the API: the workflow definition, the `ArtifactType.view` and the projected
fields. So a second pack runs on the same screens with no new UI code, as long as its document types use views from
the catalogue. A second pack is the M5 stretch goal.

## Boards

| Board | Screen | Example run (QQ-0001) | Route | Milestone |
| --- | --- | --- | --- | --- |
| Scenario-Index | Start page (canvas only) | — | — | — |
| Sign-in | Sign in | — | `/` | M0 |
| Console-Org | Organization | — | `/console/org` | M0 |
| Console-Packs | 1 · Domain packs | publish `procurement_demo` | `/console/packs` | M0–M2 |
| Console-Seats | Seats | — | `/console/seats` | M1 |
| Console-Activation | 2 · Seat: tests and activation checks | activation refused until tests pass | `/console/seats/:seat` | M1 |
| Console-Seat | 3 · Seat: lifecycle | the owner activates the Sourcing Agent | `/console/seats/:seat` | M1, M4 |
| WS-MyJobs | My jobs (Workspace home) | — | `/workspace` | M1–M2 |
| WS-New | 4 · New job | Faisal starts a Quick Quote | `/workspace/new` | M1 |
| Main | 5 · Job page: chat and work panel | brief interview, parallel supplier lookup | `/workspace/jobs/:id` | M1–M2 |
| WS-Queue | Team queue | the Sourcing team's queue | `/workspace/queue` | M2 |
| WS-Shortlist | 6 · Job page: claim and decide | Noura claims and shortlists | `/workspace/jobs/:id` | M2 |
| WS-RFQ-Approval | 7 · Job page: rework and approval | leak caught, then the send approval | `/workspace/jobs/:id` | M2–M3 |
| WS-Quotes | 8 · Job page: waiting on replies | RFQs sent, quotes arrive | `/workspace/jobs/:id` | M3 |
| WS-Faisal-Refused | 9 · Job page: refused by policy | requester asks for prices: NEVER | `/workspace/jobs/:id` | M3 |
| Console-Policy | 10 · Policy decision | why it was NEVER | `/console/policies/decisions/:id` | M3 |
| WS-Comparison | 11 · Job page: compare and select | deadline fires, Noura selects a supplier | `/workspace/jobs/:id` | M3 |
| WS-PO-Approval | 12 · Approval: multi-step chain | two-step PO approval | `/workspace/jobs/:id` | M3 |
| Console-Gateway | 13 · Action: reconcile an unknown result | ERP timeout reconciled | `/console/actions/:id` | M3 |
| WS-Closed | 14 · Job page: closed with handover | closed, handover to Faisal | `/workspace/jobs/:id` | M3 |
| WS-Inbox | Inbox and notifications | — | `/workspace/inbox` | M3 |
| Console-Workflows | Workflow definition | the Quick Quote workflow | `/console/workflows/:name` | M2 |
| Console-Instances | Instances | — | `/console/instances` | M2 |
| Console-Instance | 15 · Instance: timeline and trace | one Task's trace | `/console/instances/:id` | M2, M4 |
| Console-Approvals | Approvals oversight | — | `/console/approvals` | M3 |
| Console-Connectors | Tools and connectors | — | `/console/connectors` | M3 |
| Console-Observability | Observability | — | `/console/observability` | M4 |
| Console-Audit | 16 · Audit chain | "Why this supplier?" | `/console/audit` | M0, M4 |
| Console-Emergency | 17 · Kill switch | kill the Seat on another event | `/console/emergency` | M4 |
| Demo-Controls | Demo controls (demo only) | clock, vendor replies, fault switches | `/demo` | M2–M3 |
| States | UI states every screen handles | — | — | M1–M3 |
| Components | Tokens and shared components | — | — | M1 |

Board file names are kept from the first drafts (for example `WS-Comparison`), so links stay stable. The *Screen*
column is the name to use in code and tickets.

The full design → frontend → backend → agent mapping is in `docs/specs/trace-map.md`.

## Example data

The walkthrough boards (stops 1–17) follow QQ-0001 from 15 to 22 Oct. The other platform screens are set at
23 Oct 10:30. At that point QQ-0001 and QQ-0002 are closed, QQ-0003 is waiting on the PO approval, QQ-0004 is
unclaimed, QQ-0005 is awaiting quotes and QQ-0006 is in intake. Names and figures are illustrative.
