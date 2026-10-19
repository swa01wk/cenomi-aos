import {
  AgentMessage,
  Composer,
  ConnectionBanner,
  PersonMessage,
  SeatNotice,
  StageStepper,
  StreamingText,
  ToolActivity,
} from "../../components";
import type { MessageDelta, ToolActivity as ToolActivityType, Turn } from "../../components/types";
import { useWorkflowTitle } from "../useWorkspaceQueries";
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

  return (
    <section aria-label="Conversation" className={styles.conversation}>
      {bannerMode === "reconnecting" && <ConnectionBanner mode="reconnecting" />}
      {bannerMode === "synced" && <ConnectionBanner mode="synced" updateCount={syncCount} />}

      <header className={styles.convHeader}>
        <div>
          <span className="muted" style={{ fontSize: 12 }}>
            {workflowTitle(snapshot.workflow)} · {snapshot.instance_id}
          </span>
          <h1 style={{ margin: "4px 0 0", fontSize: 20 }}>{snapshot.title}</h1>
        </div>
        <StageStepper stages={snapshot.stages} />
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
          <div className={styles.agentStream}>
            <StreamingText turnId={streamingTurnId} deltas={deltas} showCaret />
            {toolActivity && <ToolActivity activity={toolActivity} />}
          </div>
        )}
        {!streamingTurnId && toolActivity && (
          <div className={styles.agentStream}>
            <ToolActivity activity={toolActivity} />
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

      <div className={styles.composerWrap}>
        <label className="muted" style={{ fontSize: 12 }}>
          Reply
        </label>
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
          <div className={styles.agentStream}>
            <StreamingText turnId={turn.turn_id} deltas={deltas} showCaret />
            {toolActivity && <ToolActivity activity={toolActivity} />}
          </div>
        )}
      </>
    );
  }
  return (
    <article className={styles.agentBlock} aria-label={`Reply from ${turn.author.name}`}>
      <AgentMessage
        turn={turn}
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
