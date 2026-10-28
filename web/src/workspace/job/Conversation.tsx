import { useEffect, useRef, type ReactNode } from "react";
import {
  AgentMessage,
  Composer,
  ConnectionBanner,
  PersonMessage,
  SeatNotice,
  StreamingText,
  ToolActivity,
} from "../../components";
import type { MessageDelta, ToolActivity as ToolActivityType, Turn } from "../../components/types";
import { SeatMark } from "../icons";
import { useWorkflowTitle } from "../useWorkspaceQueries";
import { JobClosedBanner } from "./JobClosedBanner";
import { JobProgress } from "./JobProgress";
import { isJobClosed, jobHeaderBadge, stagesForDisplay } from "./jobLifecycle";
import { DecisionCard } from "./DecisionCard";
import { JobStepGuide } from "./JobStepGuide";
import { orphanOpenDecisions, splitConversationPending } from "./conversationPending";
import { StaleRetriesPanel } from "./StaleRetriesPanel";
import { jobStepGuide, stageGuideIsLive } from "./stageGuideLogic";
import { AgentWorkStatus } from "./AgentWorkStatus";
import type { InstanceSnapshot } from "./jobStreamReducer";
import styles from "./job.module.css";

export function Conversation({
  snapshot,
  streamingTurnId,
  awaitingTurnId,
  deltas,
  toolActivity,
  bannerMode,
  syncCount,
  composerDisabledReason,
  seatNotice,
  initialComposerText,
  onComposerTextChange,
  onSend,
  onOpenArtifact,
  onDecide,
  onLoadOlder,
  showLoadOlder,
}: {
  snapshot: InstanceSnapshot;
  streamingTurnId: string | null;
  awaitingTurnId: string | null;
  deltas: MessageDelta[];
  toolActivity?: ToolActivityType;
  bannerMode: "hidden" | "reconnecting" | "synced";
  syncCount: number;
  composerDisabledReason?: string;
  seatNotice?: { kind: "paused" | "killed"; text: string } | null;
  initialComposerText?: string;
  onComposerTextChange?: (text: string) => void;
  onSend: (text: string, clientTurnId: string) => Promise<void>;
  onOpenArtifact: (artifactId: string) => void;
  onDecide: (input: {
    pendingId: string;
    value: string;
    artifactVersion?: number;
    note?: string;
    selection?: string[];
    idempotencyKey: string;
  }) => Promise<void>;
  onLoadOlder?: () => void;
  showLoadOlder?: boolean;
}) {
  const workflowTitle = useWorkflowTitle();
  const turnIds = new Set(snapshot.turns.map((t) => t.turn_id));
  const orphanPending = orphanOpenDecisions(snapshot);
  const { primary: primaryPending, staleRetries } = splitConversationPending(orphanPending, snapshot);
  const streamingOnly = streamingTurnId && !turnIds.has(streamingTurnId);
  const closed = isJobClosed(snapshot);
  const displayStages = stagesForDisplay(snapshot.stages, snapshot.state);
  const badge = jobHeaderBadge(snapshot.stages, snapshot.state);
  const awaitingHasText = Boolean(awaitingTurnId && deltas.some((d) => d.turn_id === awaitingTurnId));
  const showThinking = Boolean(awaitingTurnId) && !awaitingHasText;
  const openPendingForYou = snapshot.pending.filter((p) => p.status === "open").length;
  const agentBusy = Boolean(showThinking || streamingTurnId || toolActivity);
  const personTurns = snapshot.turns.filter((t) => t.author.kind === "person").length;
  const isFirstExchange = personTurns <= 1;
  const stepGuide = jobStepGuide(snapshot, { agentBusy, openPendingForYou });
  const scroller = useRef<HTMLDivElement>(null);
  const stick = useRef(true);

  useEffect(() => {
    const el = scroller.current;
    if (!el || !stick.current) return;
    el.scrollTop = el.scrollHeight;
  }, [snapshot.turns.length, deltas.length, showThinking, toolActivity?.state, primaryPending.length, staleRetries.length]);

  return (
    <section aria-label="Conversation" className={styles.conversation}>
      {bannerMode === "reconnecting" && <ConnectionBanner mode="reconnecting" />}
      {bannerMode === "synced" && <ConnectionBanner mode="synced" updateCount={syncCount} />}

      <header className={[styles.convHeader, closed ? styles.convHeader_closed : ""].filter(Boolean).join(" ")}>
        <span className={styles.convMeta}>
          {workflowTitle(snapshot.workflow)} · {snapshot.instance_id}
        </span>
        <div className={styles.convTitleRow}>
          <h1>{snapshot.title}</h1>
          {badge && (
            <span className={[styles.stageBadge, closed ? styles.stageBadge_complete : ""].filter(Boolean).join(" ")}>
              {badge}
            </span>
          )}
        </div>
        {closed ? <JobClosedBanner instanceId={snapshot.instance_id} /> : null}
        <JobProgress stages={displayStages} allComplete={closed} />
      </header>

      <div
        className={styles.turns}
        ref={scroller}
        onScroll={() => {
          const el = scroller.current;
          if (!el) return;
          stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
        }}
      >
        {showLoadOlder && (
          <button type="button" className="btn" onClick={() => onLoadOlder?.()}>
            Show earlier messages
          </button>
        )}
        {snapshot.turns.map((turn) => (
          <TurnView
            key={turn.turn_id}
            turn={turn}
            streamingTurnId={streamingTurnId}
            awaitingTurnId={showThinking ? awaitingTurnId : null}
            deltas={deltas}
            toolActivity={toolActivity}
            workflowState={snapshot.state}
            isFirstExchange={isFirstExchange}
            onOpenArtifact={onOpenArtifact}
            renderPending={(pendingId) => {
              const pending = snapshot.pending.find((item) => item.pending_id === pendingId && item.status === "open");
              if (!pending || pending.kind !== "decision") return null;
              const artifact = snapshot.artifacts.find((item) => item.artifact_id === pending.artifact_ref?.artifact_id);
              return <DecisionCard pending={pending} view={artifact?.view} onApprove={onDecide} />;
            }}
          />
        ))}
        {streamingOnly && (
          <AgentStream>
            {showThinking ? (
              <AgentWorkStatus
                workflowState={snapshot.state}
                toolActivity={toolActivity}
                isFirstExchange={isFirstExchange}
              />
            ) : (
              <StreamingText turnId={streamingTurnId} deltas={deltas} showCaret />
            )}
            {toolActivity && <ToolActivity activity={toolActivity} />}
          </AgentStream>
        )}
        {!streamingTurnId && !showThinking && toolActivity && (
          <AgentStream>
            <ToolActivity activity={toolActivity} />
          </AgentStream>
        )}

        {(primaryPending.length > 0 || staleRetries.length > 0) && (
          <div className={styles.pendingInThread}>
            {primaryPending.map((pending) => {
              const artifact = snapshot.artifacts.find((a) => a.artifact_id === pending.artifact_ref?.artifact_id);
              return (
                <DecisionCard
                  key={pending.pending_id}
                  pending={pending}
                  view={artifact?.view}
                  onApprove={onDecide}
                  variant={pending.event === "task.retry" ? "retry" : "default"}
                />
              );
            })}
            <StaleRetriesPanel retries={staleRetries} artifacts={snapshot.artifacts} onDecide={onDecide} />
          </div>
        )}
      </div>

      {seatNotice && (
        <SeatNotice
          code={seatNotice.kind === "killed" ? "kill_switch_active" : "seat_not_active"}
          title={seatNotice.kind === "killed" ? "Digital worker stopped" : "Digital worker paused"}
          detail={seatNotice.text}
        />
      )}

      {stepGuide && !seatNotice && !closed && primaryPending.length === 0 ? (
        <JobStepGuide
          guide={stepGuide}
          live={stageGuideIsLive(stepGuide, snapshot.state)}
          workflowState={snapshot.state}
        />
      ) : null}

      {closed ? (
        <p className={styles.closedFooter}>This conversation is read-only. Start a new job to run another quick quote.</p>
      ) : (
        <div className={styles.composerWrap}>
          <Composer
            onSend={onSend}
            disabledReason={composerDisabledReason}
            initialText={initialComposerText}
            onTextChange={onComposerTextChange}
            agentBusy={agentBusy}
          />
        </div>
      )}
    </section>
  );
}

function AgentStream({ children }: { children: ReactNode }) {
  return (
    <div className={styles.agentStream}>
      <SeatMark small />
      <div className={styles.agentStreamBody}>{children}</div>
    </div>
  );
}

function TurnView({
  turn,
  streamingTurnId,
  awaitingTurnId,
  deltas,
  toolActivity,
  workflowState,
  isFirstExchange,
  onOpenArtifact,
  renderPending,
}: {
  turn: Turn;
  streamingTurnId: string | null;
  awaitingTurnId: string | null;
  deltas: MessageDelta[];
  toolActivity?: ToolActivityType;
  workflowState: string;
  isFirstExchange: boolean;
  onOpenArtifact: (artifactId: string) => void;
  renderPending?: (pendingId: string) => ReactNode;
}) {
  const isStreaming = turn.turn_id === streamingTurnId;
  if (turn.author.kind === "person") {
    // The kernel streams a reply against the turn it answers (the person's message); the reply turn itself only
    // exists once it completes. Show the live text right under the message being answered.
    return (
      <>
        <PersonMessage turn={turn} />
        {(isStreaming || turn.turn_id === awaitingTurnId) && (
          <AgentStream>
            {turn.turn_id === awaitingTurnId && !isStreaming ? (
              <AgentWorkStatus
                workflowState={workflowState}
                toolActivity={toolActivity}
                isFirstExchange={isFirstExchange}
              />
            ) : (
              <StreamingText turnId={turn.turn_id} deltas={deltas} showCaret />
            )}
            {toolActivity && <ToolActivity activity={toolActivity} />}
          </AgentStream>
        )}
      </>
    );
  }
  return (
    <article className={styles.agentBlock} aria-label={`Reply from ${turn.author.name}`}>
      <AgentMessage
        turn={turn}
        avatar={<SeatMark small />}
        onOpenArtifact={(id) => onOpenArtifact(id)}
        renderPending={renderPending}
      />
      {isStreaming && (
        <>
          <StreamingText turnId={turn.turn_id} deltas={deltas} showCaret />
          {toolActivity && <ToolActivity activity={toolActivity} />}
        </>
      )}
    </article>
  );
}
