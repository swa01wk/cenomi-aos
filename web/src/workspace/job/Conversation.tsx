import { Link } from "react-router";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
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
import { ReplyIcon, SeatMark } from "../icons";
import { bulkReplyDraft, questionsInAgentTurn } from "./agentReplyTemplate";
import { ReplyQuoteBar } from "./ReplyQuoteBar";
import { turnQuoteExcerpt } from "./turnText";
import { useWorkflowTitle } from "../useWorkspaceQueries";
import { JobClosedBanner } from "./JobClosedBanner";
import { JobProgress } from "./JobProgress";
import { isJobClosed, jobHeaderBadge, stagesForDisplay } from "./jobLifecycle";
import { DecisionCard } from "./DecisionCard";
import { decisionSelectionView, decisionSelectionVersion } from "./decisionArtifactView";
import { JobStepGuide } from "./JobStepGuide";
import { orphanOpenDecisions, splitConversationPending } from "./conversationPending";
import { StaleRetriesPanel } from "./StaleRetriesPanel";
import { jobStepGuide, quickQuoteRfpMisrouteNotice, stageGuideIsLive } from "./stageGuideLogic";
import { AgentWorkStatus } from "./AgentWorkStatus";
import { assigneeLabel } from "../persona";
import { isCoordinatorJob, isSmallTalk } from "../workspaceEntry";
import { BriefSummaryMessage } from "./BriefSummaryMessage";
import {
  briefArtifact,
  holdBriefConfirmDecision,
  showBriefSummaryInChat,
  specialistAwaitingReply,
  specialistChatTurns,
} from "./conversationDisplay";
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
  chatLayout = false,
  documentCount = 0,
  documentsOpen = false,
  showDocumentsEntry = false,
  onToggleDocuments,
  handoffBanner,
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
  chatLayout?: boolean;
  documentCount?: number;
  documentsOpen?: boolean;
  /** Person chat: show Documents even before the first artifact is saved. */
  showDocumentsEntry?: boolean;
  onToggleDocuments?: () => void;
  handoffBanner?: ReactNode;
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
  const openPendingForYou = snapshot.pending.filter(
    (p) =>
      p.status === "open" &&
      !holdBriefConfirmDecision(snapshot, p) &&
      !(
        specialistAwaitingReply(snapshot) &&
        p.kind === "decision" &&
        !snapshot.intake_ready_for_confirm
      ),
  ).length;
  const agentBusy = Boolean(showThinking || streamingTurnId || toolActivity);
  const personTurns = snapshot.turns.filter((t) => t.author.kind === "person").length;
  const isFirstExchange = personTurns <= 1;
  const stepGuide = jobStepGuide(snapshot, { agentBusy, openPendingForYou });
  const pathNotice = quickQuoteRfpMisrouteNotice(snapshot);
  const coordinatorChat = isCoordinatorJob(snapshot);
  const chatOnlyStage = snapshot.state === "conversation" || snapshot.state === "chat";
  const latestPerson = [...snapshot.turns].reverse().find((t) => t.author.kind === "person");
  const latestText =
    latestPerson?.blocks.flatMap((b) => (b.kind === "text" ? [b.text] : [])).join(" ") ?? "";
  const shortlistForYou = snapshot.pending.some(
    (p) => p.status === "open" && p.event === "decision.shortlist_confirmed",
  );
  const casualChat =
    !shortlistForYou &&
    (coordinatorChat || chatOnlyStage || snapshot.state === "intake" || isSmallTalk(latestText));
  const colleague = assigneeLabel(snapshot.assignee);
  const visibleTurns = specialistChatTurns(snapshot, snapshot.turns);
  const brief = briefArtifact(snapshot);
  const briefSummary = showBriefSummaryInChat(snapshot);
  const scroller = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const [composerExpanded, setComposerExpanded] = useState(false);
  const [composerFocusToken, setComposerFocusToken] = useState(0);
  const [replyHint, setReplyHint] = useState<string | null>(null);
  const [replyQuote, setReplyQuote] = useState<{
    turnId: string;
    authorName: string;
    excerpt: string;
  } | null>(null);
  const canQuoteReply = !closed && !composerDisabledReason && !agentBusy;

  const handleReplyToTurn = useCallback(
    (turn: Turn) => {
      const excerpt = turnQuoteExcerpt(turn);
      if (excerpt) {
        setReplyQuote({
          turnId: turn.turn_id,
          authorName: turn.author.name,
          excerpt,
        });
      }
      const questions = questionsInAgentTurn(turn);
      const draft = bulkReplyDraft(questions);
      if (draft && !initialComposerText?.trim()) {
        onComposerTextChange?.(draft);
      }
      setComposerExpanded(questions.length >= 2);
      setReplyHint(
        questions.length >= 2 ? `Answer all ${questions.length} questions in one message.` : null,
      );
      setComposerFocusToken((n) => n + 1);
      stick.current = true;
      window.requestAnimationFrame(() => {
        scroller.current
          ?.querySelector(`[data-turn-id="${turn.turn_id}"]`)
          ?.scrollIntoView({ block: "nearest", behavior: "smooth" });
      });
    },
    [initialComposerText, onComposerTextChange],
  );

  const clearReplyQuote = useCallback(() => {
    setReplyQuote(null);
    setReplyHint(null);
    setComposerExpanded(false);
  }, []);

  const handleSend = useCallback(
    async (text: string, clientTurnId: string) => {
      await onSend(text, clientTurnId);
      setComposerExpanded(false);
      setReplyHint(null);
      setReplyQuote(null);
    },
    [onSend],
  );

  useEffect(() => {
    const el = scroller.current;
    if (!el || !stick.current) return;
    el.scrollTop = el.scrollHeight;
  }, [snapshot.turns.length, deltas.length, showThinking, toolActivity?.state, primaryPending.length, staleRetries.length]);

  return (
    <section aria-label="Conversation" className={styles.conversation}>
      {bannerMode === "reconnecting" && <ConnectionBanner mode="reconnecting" />}
      {bannerMode === "synced" && <ConnectionBanner mode="synced" updateCount={syncCount} />}
      {handoffBanner}

      <header className={[styles.convHeader, closed ? styles.convHeader_closed : ""].filter(Boolean).join(" ")}>
        <div className={styles.convHeaderTop}>
          {chatLayout && snapshot.seat ? (
            <Link to={`/workspace/people/${encodeURIComponent(snapshot.seat)}`} className={styles.convBack}>
              Back
            </Link>
          ) : null}
          <div className={styles.convPeer}>
            <span className={styles.convPeerAvatar} aria-hidden="true">
              {(colleague.name[0] ?? "?").toUpperCase()}
            </span>
            <div className={styles.convPeerText}>
              <span className={styles.convPeerName}>{colleague.name}</span>
              {colleague.title ? <span className={styles.convPeerTitle}>{colleague.title}</span> : null}
            </div>
          </div>
          {chatLayout && (documentCount > 0 || showDocumentsEntry) && onToggleDocuments ? (
            <button type="button" className={styles.convDocsBtn} onClick={onToggleDocuments}>
              {documentsOpen ? "Hide" : documentCount > 0 ? "Documents" : "Work panel"}
            </button>
          ) : null}
        </div>
        {!chatLayout ? (
          <>
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
          </>
        ) : null}
        {closed ? <JobClosedBanner snapshot={snapshot} /> : null}
        {!chatLayout ? <JobProgress stages={displayStages} allComplete={closed} /> : null}
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
        {briefSummary && brief ? (
          <BriefSummaryMessage
            artifactId={brief.artifact_id}
            version={brief.latest_version}
            view={brief.view}
            specialistName={colleague.name}
          />
        ) : null}
        {visibleTurns.map((turn) => (
          <TurnView
            key={turn.turn_id}
            turn={turn}
            streamingTurnId={streamingTurnId}
            awaitingTurnId={showThinking ? awaitingTurnId : null}
            deltas={deltas}
            toolActivity={toolActivity}
            workflowState={snapshot.state}
            isFirstExchange={isFirstExchange}
            coordinatorChat={casualChat}
            onOpenArtifact={onOpenArtifact}
            renderPending={(pendingId) => {
              const pending = snapshot.pending.find((item) => item.pending_id === pendingId && item.status === "open");
              if (!pending || pending.kind !== "decision") return null;
              const artifact = snapshot.artifacts.find((item) => item.artifact_id === pending.artifact_ref?.artifact_id);
              const view = decisionSelectionView(pending, artifact);
              const selectionVersion = decisionSelectionVersion(pending, artifact);
              return (
                <DecisionCard
                  pending={pending}
                  view={view}
                  selectionVersion={selectionVersion}
                  latestArtifactVersion={artifact?.latest_version}
                  onApprove={onDecide}
                />
              );
            }}
            quotedForReply={replyQuote?.turnId === turn.turn_id}
            showReply={canQuoteReply}
            onReply={() => handleReplyToTurn(turn)}
          />
        ))}
        {streamingOnly && (
          <AgentStream>
            {showThinking ? (
              casualChat ? (
                <p className="muted">Replying…</p>
              ) : (
                <AgentWorkStatus
                  workflowState={snapshot.state}
                  toolActivity={toolActivity}
                  isFirstExchange={isFirstExchange}
                />
              )
            ) : (
              <StreamingText turnId={streamingTurnId!} deltas={deltas} showCaret />
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
              const view = decisionSelectionView(pending, artifact);
              const selectionVersion = decisionSelectionVersion(pending, artifact);
              return (
                <DecisionCard
                  key={pending.pending_id}
                  pending={pending}
                  view={view}
                  selectionVersion={selectionVersion}
                  latestArtifactVersion={artifact?.latest_version}
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

      {pathNotice && !closed ? (
        <JobStepGuide guide={pathNotice} live={false} workflowState={snapshot.state} />
      ) : null}

      {stepGuide && !casualChat && !seatNotice && !closed && primaryPending.length === 0 ? (
        <JobStepGuide
          guide={stepGuide}
          live={stageGuideIsLive(stepGuide, snapshot.state)}
          workflowState={snapshot.state}
        />
      ) : null}

      {closed ? (
        <p className={styles.closedFooter}>This conversation is read-only. Start a new job from the sidebar to begin again.</p>
      ) : (
        <div className={[styles.composerWrap, replyQuote ? styles.composerWrapQuoted : ""].filter(Boolean).join(" ")}>
          {replyQuote ? (
            <ReplyQuoteBar
              authorName={replyQuote.authorName}
              excerpt={replyQuote.excerpt}
              onDismiss={clearReplyQuote}
            />
          ) : null}
          {replyHint ? <p className={styles.composerReplyHint}>{replyHint}</p> : null}
          <div className={replyQuote ? styles.composerDockQuoted : undefined}>
            <Composer
              onSend={handleSend}
              disabledReason={composerDisabledReason}
              initialText={initialComposerText}
              onTextChange={onComposerTextChange}
              agentBusy={agentBusy}
              expanded={composerExpanded}
              focusToken={composerFocusToken}
              placeholder={
                replyQuote
                  ? "Write a reply…"
                  : composerExpanded
                    ? "Answer each numbered line, then send once"
                    : "Message"
              }
            />
          </div>
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
  coordinatorChat,
  onOpenArtifact,
  renderPending,
  showReply,
  onReply,
  quotedForReply,
}: {
  turn: Turn;
  streamingTurnId: string | null;
  awaitingTurnId: string | null;
  deltas: MessageDelta[];
  toolActivity?: ToolActivityType;
  workflowState: string;
  isFirstExchange: boolean;
  coordinatorChat: boolean;
  onOpenArtifact: (artifactId: string) => void;
  renderPending?: (pendingId: string) => ReactNode;
  showReply?: boolean;
  onReply?: () => void;
  quotedForReply?: boolean;
}) {
  const isStreaming = turn.turn_id === streamingTurnId;
  const hasInlineDecision = turn.blocks.some((b) => b.kind === "pending_ref");
  const turnRowClass = [
    styles.turnRow,
    turn.author.kind === "person" ? styles.turnRowPerson : styles.turnRowAgent,
    quotedForReply ? styles.turnRowQuoted : "",
  ]
    .filter(Boolean)
    .join(" ");

  if (turn.author.kind === "person") {
    // The kernel streams a reply against the turn it answers (the person's message); the reply turn itself only
    // exists once it completes. Show the live text right under the message being answered.
    return (
      <>
        <div className={turnRowClass} data-turn-id={turn.turn_id}>
          <PersonMessage turn={turn} highlighted={quotedForReply} />
          {showReply && onReply ? (
            <button type="button" className={styles.turnReplyBtn} onClick={onReply} aria-label="Quote reply">
              <ReplyIcon size={14} />
              Reply
            </button>
          ) : null}
        </div>
        {(isStreaming || turn.turn_id === awaitingTurnId) && (
          <AgentStream>
            {turn.turn_id === awaitingTurnId && !isStreaming ? (
              coordinatorChat ? (
                <p className="muted">Replying…</p>
              ) : (
                <AgentWorkStatus
                  workflowState={workflowState}
                  toolActivity={toolActivity}
                  isFirstExchange={isFirstExchange}
                />
              )
            ) : (
              <StreamingText turnId={turn.turn_id} deltas={deltas} showCaret />
            )}
            {toolActivity && <ToolActivity activity={toolActivity} />}
          </AgentStream>
        )}
      </>
    );
  }
  const showReplyControl = Boolean(showReply && onReply && !hasInlineDecision);
  return (
    <article className={styles.agentBlock} data-turn-id={turn.turn_id} aria-label={`Reply from ${turn.author.name}`}>
      <div className={turnRowClass}>
        {showReplyControl ? (
          <button type="button" className={styles.turnReplyBtn} onClick={onReply} aria-label="Quote reply">
            <ReplyIcon size={14} />
            Reply
          </button>
        ) : null}
        <AgentMessage
        turn={turn}
        avatar={<SeatMark small />}
        highlighted={quotedForReply}
        onOpenArtifact={(id) => onOpenArtifact(id)}
        renderPending={renderPending}
        />
      </div>
      {isStreaming && (
        <>
          <StreamingText turnId={turn.turn_id} deltas={deltas} showCaret />
          {toolActivity && <ToolActivity activity={toolActivity} />}
        </>
      )}
    </article>
  );
}
