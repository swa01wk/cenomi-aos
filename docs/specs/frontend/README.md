# Frontend spec: Workspace and Console

One React app (`web/`) with two shells: the **Workspace** (rail + job pages, for requesters, buyers and approvers)
and the **Console** (dark menu, for admins, Risk and owners). Designs: canvas *AOS App Screens*, sources in
`design/boards/`. Every screen's route, components and API calls are in `../trace-map.md`.

## Rules

1. **Render kernel state, never decide it.** The UI sends commands and shows what the kernel returns. It never
   computes permissions, hides columns or infers state; a disabled button or a missing column comes from the payload.
2. **Snapshot + stream.** A page loads its snapshot, then follows the event stream from the snapshot's cursor. On
   `snapshot.required` or a reconnect gap it reloads the snapshot (guidebook C10).
3. **Typed content only.** Agent and system messages render from typed blocks with fixed components. No
   `dangerouslySetInnerHTML`, no Markdown rendering of model text.
4. **Every write carries what the person saw**: `expected_version`, `payload_hash` or `base_version`. A 409 shows
   `ConflictNotice` and reloads; nothing is retried silently.
5. **Same components everywhere.** Screens compose the components below; no one-off styling of shared patterns.
6. **Nothing is written for one pack.** The screens are platform screens; the procurement content on the boards is
   example data. Stage names come from `snapshot.stages`. Document tabs and their layout come from `ArtifactView`
   (`type`, `columns`, `fields` with labels). The digital workers and workflows on New job come from `listDigitalWorkers`. No
   component, route, CSS class or string literal names a pack, workflow, Skill or document type. See
   [Views from the pack](#views-from-the-pack).

## Stack

| Concern | Choice |
| --- | --- |
| Build | Vite 7, React 19, TypeScript strict |
| Routing | `react-router` with real paths (nginx `try_files` serves `index.html`); replaces M0's hash routes in M1 |
| Server state | TanStack Query: one query per snapshot or list; stream events patch the cache |
| API types | `openapi-typescript` generates `src/api/schema.d.ts` from `docs/specs/contracts/openapi.yaml` (`npm run gen:api`); `openapi-fetch` client |
| Streams | `EventSource` wrapper `useEventStream(url, cursor)`; Last-Event-ID resume; backoff 1, 2, 5, 10 s |
| Styling | CSS variables in `src/styles/tokens.css` (values on the Components board) + CSS modules per component |
| Tests | Vitest + Testing Library for components; Playwright for flows (one spec per walkthrough stop) |

## Layout

```
web/src/
  api/            schema.d.ts (generated), client.ts, problems.ts, stream.ts
  app/            router.tsx, guards.tsx (signed-in, console role), AppErrorBoundary
  components/     the shared components below, one folder each with a test
  styles/         tokens.css, base.css
  workspace/      WorkspaceShell, MyJobsPage, NewJobPage, QueuePage, InboxPage, job/ (JobPage, Conversation, WorkPanel, views/)
  console/        ConsoleShell, OrgPage, PacksPage, VersionPage, SeatsPage, SeatPage, WorkflowPage, InstancesPage,
                  InstancePage, ApprovalsPage, PoliciesPage, DecisionPage, ConnectorsPage, ActionPage,
                  ObservabilityPage, AuditPage, EmergencyPage
  demo/           DemoControlsPage (only when /api/demo/state answers)
```

## Routes

| Path | Page | Guard | Board |
| --- | --- | --- | --- |
| `/` | SignInPage | none | Sign-in |
| `/workspace` | MyJobsPage | signed in | WS-MyJobs |
| `/workspace/new` | NewJobPage | signed in | WS-New |
| `/workspace/queue` | QueuePage | signed in, member of a queue team | WS-Queue |
| `/workspace/inbox` | InboxPage | signed in | WS-Inbox |
| `/workspace/jobs/:id` | JobPage (`?panel=<artifact_id>`) | participant (kernel 403 → RefusalNotice page) | Main … WS-Closed |
| `/console/org` | OrgPage | Console role | Console-Org |
| `/console/packs`, `/console/versions/:id` | PacksPage, VersionPage | Console role | Console-Packs |
| `/console/seats`, `/console/seats/:seat` | SeatsPage, SeatPage | Console role | Console-Seats, -Activation, -Seat |
| `/console/workflows/:name` | WorkflowPage | Console role | Console-Workflows |
| `/console/instances`, `/console/instances/:id` | InstancesPage, InstancePage | Console role | Console-Instances, -Instance |
| `/console/approvals` | ApprovalsPage | Console role | Console-Approvals |
| `/console/policies`, `/console/policies/decisions/:id` | PoliciesPage, DecisionPage | Console role | Console-Policy |
| `/console/connectors`, `/console/actions/:id` | ConnectorsPage, ActionPage | Console role | Console-Connectors, -Gateway |
| `/console/observability` | ObservabilityPage | Console role | Console-Observability |
| `/console/audit` | AuditPage | platform_admin or risk | Console-Audit |
| `/console/emergency` | EmergencyPage | seat_owner or platform_admin | Console-Emergency |
| `/demo` | DemoControlsPage | signed in, demo enabled | Demo-Controls |

Console menu items for pages not built yet show the milestone tag (as in M0). Items a role can't use are shown
disabled with the reason as tooltip, never hidden silently.

## Components

From the Components and States boards. Props are the minimum; types come from `schema.d.ts`.

| Component | Purpose | Key props |
| --- | --- | --- |
| `Button` | primary, secondary, dark, danger; disabled with reason | `variant`, `disabledReason` |
| `StatusPill` | kernel states (monospace caps) | `state` |
| `StageStepper` | workflow stages from `snapshot.stages` | `stages` |
| `PageHeader`, `Panel`, `Tabs`, `DataTable`, `StatTile`, `MeterBar` | layout and data | — |
| `WorkspaceShell`, `ConsoleShell` | rail and menu | `me`, `active` |
| `AgentMessage`, `PersonMessage` | a turn, rendered from `blocks` | `turn` |
| `StreamingText` | deltas for the turn being answered | `turnId` |
| `ToolActivity` | the tool's activity label from the pack, e.g. "Searching suppliers in the ERP · allowed" | `activity` |
| `SourceChip`, `ArtifactChip` | links into sources and the work panel | `block` |
| `DecisionCard` | pending decision; sends `decidePending` with `expected_version` | `pending`, `instanceVersion` |
| `ApprovalCard` | exactly what will run, chain, hash, expiry; approve/reject | `approval`, `myStep` |
| `Composer` | message input; `client_turn_id` per send | `onSend`, `disabledReason` |
| `DocumentView` | `view: document` (example: brief) with edit-in-panel | `version`, `editable` |
| `ArtifactSheet` | `view: sheet` (example: supplier_list, comparison) | `version`, `selectable` |
| `MessageComposerView` | `view: message_composer` (example: rfq_email), one tab per recipient | `versions`, `editable` |
| `TrackerView` | `view: tracker` (example: quote) | `versions` |
| `RecordPreview` | `view: record_preview` (example: po_payload) | `version` |
| `TimelineItem` | any record kind on a timeline | `entry` |
| `TraceWaterfall` | spans of one Task | `spans` |
| `ChainSteps`, `CheckList`, `LifecycleSteps` | approval chain, checks, Seat lifecycle | — |
| `PolicyEvalTrace` | evaluation order with the matching step | `decision` |
| `HashChainBadge` | chain intact / broken at n | `report` |
| `KillSwitchPanel` | scope, reason, confirm | — |
| `Skeleton`, `EmptyState`, `ErrorBanner`, `RefusalNotice`, `ConflictNotice`, `FieldError`, `ConnectionBanner`, `SessionDialog`, `SeatNotice`, `ExceptionCard`, `TaskStatus` | the States board | see below |

Hidden fields: when `ArtifactVersion.hidden_fields` is non-empty, the view shows one quiet line
"Some fields aren't shared with your role" and never an empty column.

## Views from the pack

The work panel picks a component by `ArtifactSummary.view.type`, through one registry
(`workspace/job/views/index.ts`):

| `view.type` | Component | POC | Example in QQ-0001 |
| --- | --- | --- | --- |
| `document` | `DocumentView` | yes | brief |
| `sheet` | `ArtifactSheet` | yes | supplier ranking, comparison |
| `tracker` | `TrackerView` | yes | quote tracker |
| `message_composer` | `MessageComposerView` | yes | RFQ emails, one tab per recipient |
| `record_preview` | `RecordPreview` | yes | PO payload |
| `form`, `comparison`, `rubric`, `approval_pack`, `file_viewer`, `dashboard` | `FieldListView` fallback | fallback only | — |

- Columns and their order come from `view.columns`. Headers come from `view.fields[].label`. Cell formatting comes
  from `view.fields[].type`: `money` shows the currency, `date` uses the locale, `integer` is right-aligned.
- `FieldListView` shows any content as label/value rows, so a pack with an unsupported view type still renders
  something readable. Add a real component only when a second pack needs one.
- Export buttons appear only when `view.export` is set.
- Test: `views.test.tsx` renders every view from a fixture with **made-up** field names and labels (not
  procurement ones). This proves the views don't depend on the example pack.

## Problem → UI

| Status / code | Component | Behaviour |
| --- | --- | --- |
| 401 `unauthenticated` | `SessionDialog` | keep in-memory drafts; sign in again |
| 403 `not_permitted`, `policy_denied`, `policy_never`, `segregation_of_duties` | `RefusalNotice` | show `title` and `detail`; link the decision for Console roles |
| 403 `seat_not_active`, `kill_switch_active` | `SeatNotice` | disable Composer and decision buttons with the reason |
| 409 `stale_version`, `already_claimed`, `approval_stale` | `ConflictNotice` | reload the snapshot; show what changed |
| 409 `fenced` | — | never reaches the browser |
| 422 `validation_failed` | `FieldError` per `errors[].pointer` | keep input |
| 429, 503 `unavailable` | `ErrorBanner` with retry | — |
| 5xx `internal` | `ErrorBanner` with `trace_id` | — |

## Stream reducer (job page)

```ts
switch (event.type) {
  case 'snapshot.required':        refetchSnapshot(); break
  case 'instance.state_changed':   patch(s => ({...s, state: e.to, version: e.version, stages: markStages(s.stages, e.to)})); break
  case 'turn.created':
  case 'agent.message.completed':  upsertTurn(e.turn); clearDeltas(e.turn.turn_id); break
  case 'agent.message.delta':      appendDelta(e.turn_id, e.seq, e.text); break      // ignore seq ≤ last
  case 'pending.created':          upsertPending(e.pending); break
  case 'pending.resolved':         removePending(e.pending_id); break
  case 'artifact.version_created': invalidate(['artifact', e.artifact_id]); bumpArtifact(e); break
  case 'approval.*':               invalidate(['approval', e.approval_id]); break
  case 'kill_switch.changed':      refetchSnapshot(); break
  default:                         patchByType(event)                                  // participant, task, attempt, tool, timer, verification
}
```

Events are applied in `id` order; a duplicate `id` is ignored.

## Accessibility and layout

- Real `<button>`, `<a href>`, `<label>`; focus visible; icon-only buttons have `aria-label`.
- Touch targets 44 px in the Workspace, 40 px in the Console.
- Text contrast at least 4.5:1; colour never carries meaning alone (pills have words).
- Phone width: rail and menu stack above content; tables scroll inside their panel; no horizontal page scroll.

## Tests

- Component tests for every shared component, including each States card.
- Playwright: one spec per walkthrough stop as it becomes real (`e2e/stop-04-new-job.spec.ts`, …), running against
  `make up` with the fake model; M5 runs all 17 in order twice.
