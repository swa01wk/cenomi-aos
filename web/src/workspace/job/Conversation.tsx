import type { ReactNode } from "react";
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
import type { InstanceSnapshot } from "./jobStreamReducer";
import styles from "./job.module.css";

export function Conversation({
  snapshot,
  streamingTurnId,
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
  onLoadOlder,
  showLoadOlder,
}: {
  snapshot: InstanceSnapshot;
  streamingTurnId: string | null;
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
  onLoadOlder?: () => void;
  showLoadOlder?: boolean;
}) {
  const workflowTitle = useWorkflowTitle();
  const turnIds = new Set(snapshot.turns.map((t) => t.turn_id));
  const streamingOnly = streamingTurnId && !turnIds.has(streamingTurnId);
  const badge = stageBadgeText(snapshot.stages);

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

      <div className={styles.turns}>
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
            deltas={deltas}
            toolActivity={toolActivity}
            onOpenArtifact={onOpenArtifact}
          />
        ))}
        {streamingOnly && (
          <AgentStream>
            <StreamingText turnId={streamingTurnId} deltas={deltas} showCaret />
            {toolActivity && <ToolActivity activity={toolActivity} />}
          </AgentStream>
        )}
        {!streamingTurnId && toolActivity && (
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
  deltas,
  toolActivity,
  onOpenArtifact,
}: {
  turn: Turn;
  streamingTurnId: string | null;
  deltas: MessageDelta[];
  toolActivity?: ToolActivityType;
  onOpenArtifact: (artifactId: string) => void;
}) {
  const isStreaming = turn.turn_id === streamingTurnId;
  if (turn.author.kind === "person") {
    // The kernel streams a reply against the turn it answers (the person's message); the reply turn itself only
    // exists once it completes. Show the live text right under the message being answered.
    return (
      <>
        <PersonMessage turn={turn} />
        {isStreaming && (
          <AgentStream>
            <StreamingText turnId={turn.turn_id} deltas={deltas} showCaret />
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
