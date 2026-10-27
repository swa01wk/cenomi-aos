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
import { JobProgress, stageBadgeText } from "./JobProgress";
import { DecisionCard } from "./DecisionCard";
import { ThinkingStatus } from "./ThinkingStatus";
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
  const pendingInTurns = new Set<string>();
  for (const turn of snapshot.turns) {
    for (const block of turn.blocks ?? []) {
      if ("pending_id" in block && block.kind === "pending_ref") pendingInTurns.add(block.pending_id);
    }
  }
  const orphanPending = snapshot.pending.filter(
    (p) => p.status === "open" && p.kind === "decision" && !pendingInTurns.has(p.pending_id),
  );
  const streamingOnly = streamingTurnId && !turnIds.has(streamingTurnId);
  const badge = stageBadgeText(snapshot.stages);
  const awaitingHasText = Boolean(awaitingTurnId && deltas.some((d) => d.turn_id === awaitingTurnId));
  const showThinking = Boolean(awaitingTurnId) && !awaitingHasText;
  const scroller = useRef<HTMLDivElement>(null);
  const stick = useRef(true);

  useEffect(() => {
    const el = scroller.current;
    if (!el || !stick.current) return;
    el.scrollTop = el.scrollHeight;
  }, [snapshot.turns.length, deltas.length, showThinking, toolActivity?.state]);

  return (
    <section aria-label="Conversation" className={styles.conversation}>
      {bannerMode === "reconnecting" && <ConnectionBanner mode="reconnecting" />}
      {bannerMode === "synced" && <ConnectionBanner mode="synced" updateCount={syncCount} />}

      <header className={styles.convHeader}>
        <span className={styles.convMeta}>
          {workflowTitle(snapshot.workflow)} · {snapshot.instance_id}
        </span>
        <div className={styles.convTitleRow}>
          <h1>{snapshot.title}</h1>
          {badge && <span className={styles.stageBadge}>{badge}</span>}
        </div>
        <JobProgress stages={snapshot.stages} />
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
              <ThinkingStatus />
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
      </div>

      {seatNotice && (
        <SeatNotice
          code={seatNotice.kind === "killed" ? "kill_switch_active" : "seat_not_active"}
          title={seatNotice.kind === "killed" ? "Digital worker stopped" : "Digital worker paused"}
          detail={seatNotice.text}
        />
      )}

      {orphanPending.length > 0 && (
        <div className={styles.openPendingStrip}>
          {orphanPending.map((pending) => {
            const artifact = snapshot.artifacts.find((a) => a.artifact_id === pending.artifact_ref?.artifact_id);
            return (
              <DecisionCard key={pending.pending_id} pending={pending} view={artifact?.view} onApprove={onDecide} />
            );
          })}
        </div>
      )}

      <div className={styles.composerWrap}>
        <Composer
          onSend={onSend}
          disabledReason={composerDisabledReason}
          initialText={initialComposerText}
          onTextChange={onComposerTextChange}
        />
      </div>
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
  onOpenArtifact,
  renderPending,
}: {
  turn: Turn;
  streamingTurnId: string | null;
  awaitingTurnId: string | null;
  deltas: MessageDelta[];
  toolActivity?: ToolActivityType;
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
              <ThinkingStatus />
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
