import { useState } from "react";
import {
  AgentMessage,
  Button,
  ChainSteps,
  CheckList,
  Composer,
  ConflictNotice,
  ConnectionBanner,
  DataTable,
  EmptyState,
  ErrorBanner,
  FieldError,
  LifecycleSteps,
  MeterBar,
  PageHeader,
  Panel,
  PersonMessage,
  RefusalNotice,
  SeatNotice,
  SessionDialog,
  Skeleton,
  StageStepper,
  StatTile,
  StatusPill,
  StreamingText,
  Tabs,
  ToolActivity,
} from "../components";
import { DEV_GALLERY_MARKER } from "./markers";
import styles from "./ComponentsGalleryPage.module.css";

export default function ComponentsGalleryPage() {
  const [tab, setTab] = useState("one");
  const [sessionOpen, setSessionOpen] = useState(false);

  return (
    <main className={styles.page}>
      <p className={styles.marker}>{DEV_GALLERY_MARKER}</p>
      <PageHeader
        eyebrow="Dev only"
        title="Shared components"
        subtitle="Layout mirrors the Components and States boards with neutral fixture data."
      />

      <section className={styles.grid}>
        <Panel title="Button">
          <div className={styles.row}>
            <Button variant="primary">Primary</Button>
            <Button variant="secondary">Secondary</Button>
            <Button variant="dark">Dark</Button>
            <Button variant="danger">Danger</Button>
            <Button disabledReason="Waiting on kernel">Disabled</Button>
          </div>
        </Panel>

        <Panel title="Status and stage">
          <div className={styles.row}>
            <StatusPill state="ACTIVE" />
            <StatusPill state="DRAFT" />
          </div>
          <StageStepper
            stages={[
              { state: "a", label: "Alpha", status: "done" },
              { state: "b", label: "Beta", status: "current" },
              { state: "c", label: "Gamma", status: "next" },
            ]}
          />
        </Panel>

        <Panel title="Conversation">
          <AgentMessage
            turn={{
              turn_id: "t1",
              seq: 1,
              author: { kind: "seat", id: "s1", name: "Assistant" },
              blocks: [
                { kind: "text", text: "Saved draft v2." },
                { kind: "artifact_chip", artifact_id: "art1", version: 2, label: "Record" },
                { kind: "source_chip", source_ref: "src1", label: "External lookup · 2026" },
              ],
              at: "2026-01-01T10:00:00Z",
            }}
          />
          <PersonMessage
            turn={{
              turn_id: "t2",
              seq: 2,
              author: { kind: "person", id: "p1", name: "Alex Kim" },
              blocks: [{ kind: "text", text: "Looks good." }],
              at: "2026-01-01T10:04:00Z",
            }}
          />
        </Panel>

        <Panel title="Layout and data">
          <StatTile label="Open jobs" value="4" />
          <MeterBar label="Spend today" value={3} limit={10} />
          <DataTable
            columns={[
              { id: "id", header: "Job", render: (r: { id: string }) => r.id },
              { id: "state", header: "State", render: (r: { state: string }) => <StatusPill state={r.state} /> },
            ]}
            rows={[{ id: "J-0001", state: "RUNNING" }]}
            getRowKey={(r) => r.id}
            empty={<span>No rows</span>}
          />
          <Tabs
            label="Example tabs"
            activeId={tab}
            onChange={setTab}
            tabs={[
              { id: "one", label: "One", panel: <p>Tab one</p> },
              { id: "two", label: "Two", panel: <p>Tab two</p> },
            ]}
          />
        </Panel>

        <Panel title="Console pieces">
          <ChainSteps parts={[{ part: "policies", role: "risk", status: "open" }]} />
          <CheckList items={[{ name: "limits", status: "pass", detail: "Within bounds" }]} />
          <LifecycleSteps
            steps={[
              { state: "DRAFT", status: "done", meta: "1 Jan · ready" },
              { state: "ACTIVE", status: "current", meta: "Waiting for the owner" },
            ]}
          />
        </Panel>

        <Panel title="Chat pieces">
          <ToolActivity
            activity={{
              instance_id: "i1",
              attempt_id: "a1",
              tool: "search",
              label: "Searching records",
              state: "allowed",
            }}
          />
          <StreamingText
            turnId="t1"
            showCaret
            deltas={[{ instance_id: "i1", turn_id: "t1", seq: 1, text: "Partial reply" }]}
          />
          <Composer onSend={async () => {}} />
        </Panel>
      </section>

      <section className={styles.grid}>
        <Panel title="States">
          <Skeleton lines={3} />
          <EmptyState title="No jobs yet" nextStep="Start one from New job when a worker is active." />
          <ErrorBanner title="We couldn't load this job" detail="The kernel didn't answer in time." traceId="503 · trace ab12" onRetry={() => {}} />
          <RefusalNotice title="Not shared with your role" detail="Ask the assigned operator." rule="visibility_rule" decisionId="d_01" />
          <ConflictNotice title="This record changed" detail="Reload to see the latest version." onReload={() => {}} />
          <label htmlFor="gal-qty">Quantity</label>
          <input id="gal-qty" aria-describedby="gal-qty-err" aria-invalid="true" />
          <FieldError id="gal-qty-err" message="Enter a whole number, for example 40." />
          <ConnectionBanner mode="reconnecting" />
          <ConnectionBanner mode="synced" updateCount={3} />
          <SeatNotice code="seat_not_active" title="Digital worker paused" detail="Nothing new runs until it is restarted." />
          <Button variant="secondary" onClick={() => setSessionOpen(true)}>
            Show session dialog
          </Button>
          <SessionDialog open={sessionOpen} onSignIn={() => setSessionOpen(false)} />
        </Panel>
      </section>
    </main>
  );
}
