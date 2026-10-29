import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router";
import { useQueryClient } from "@tanstack/react-query";
import { ApiProblemError } from "../../api/problems";
import {
  ProblemNotice,
  RefusalNotice,
  Skeleton,
  problemNotice,
} from "../../components";
import type { Problem } from "../../api/problems";
import { clearComposerDraft, getComposerDraft, setComposerDraft } from "./composerDrafts";
import { composerBlockedForPoLoop } from "./composerGate";
import { closedComposerMessage, isJobClosed } from "./jobLifecycle";
import { Conversation } from "./Conversation";
import { useJobPage } from "./useJobPage";
import { WorkPanel } from "./WorkPanel";
import { shouldAutoFocusWorkPanel } from "./workPanelAutoFocus";
import { newClientTurnId } from "../../components/clientTurnId";
import { personChatPath } from "../jobPaths";
import { startSpecialistFromIntake } from "../startJobs";
import { useDigitalWorkers } from "../useWorkspaceQueries";
import { buildHandoffIntakeMessage, isCoordinatorJob, shouldHandOffFromCoordinator } from "../workspaceEntry";
import { markCoordinatorHandedOff } from "../openPersonChat";
import styles from "./job.module.css";

export default function JobPage({ chatLayout = false }: { chatLayout?: boolean }) {
  const params = useParams();
  const instanceId = (chatLayout ? params.instanceId : params.id) ?? "";
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const workers = useDigitalWorkers();
  const [searchParams, setSearchParams] = useSearchParams();
  const panelId = searchParams.get("panel");

  const job = useJobPage(instanceId);
  const activeWorkers = useMemo(
    () => workers.data?.filter((w) => w.state === "ACTIVE") ?? [],
    [workers.data],
  );
  const [composerProblem, setComposerProblem] = useState<Problem | null>(null);
  const [seatBlock, setSeatBlock] = useState<Problem | null>(null);

  const userPanelOverride = useRef(false);
  const prevWorkflowState = useRef<string | null>(null);

  const openArtifact = useCallback(
    (artifactId: string) => {
      setSearchParams({ panel: artifactId });
    },
    [setSearchParams],
  );

  const closeDocuments = useCallback(() => {
    userPanelOverride.current = true;
    setSearchParams({});
  }, [setSearchParams]);

  const selectWorkPanelArtifact = useCallback(
    (artifactId: string) => {
      userPanelOverride.current = true;
      openArtifact(artifactId);
    },
    [openArtifact],
  );

  const onSend = useCallback(
    async (text: string, clientTurnId: string) => {
      setComposerProblem(null);
      setSeatBlock(null);
      try {
        const snap = job.snapshot;
        if (
          snap &&
          isCoordinatorJob(snap) &&
          shouldHandOffFromCoordinator(snap, text, snap.turns, activeWorkers)
        ) {
          const intake = buildHandoffIntakeMessage(text, snap.turns, activeWorkers);
          const data = await startSpecialistFromIntake(intake, newClientTurnId(), queryClient);
          markCoordinatorHandedOff(instanceId);
          clearComposerDraft(instanceId);
          void navigate(personChatPath(data.seat, data.instance_id), { replace: true });
          return;
        }
        await job.postTurn(text, clientTurnId);
        clearComposerDraft(instanceId);
      } catch (e) {
        if (e instanceof ApiProblemError) {
          const d = problemNotice(e.problem);
          if (d.kind === "seat") setSeatBlock(e.problem);
          else setComposerProblem(e.problem);
        }
        throw e;
      }
    },
    [instanceId, job, activeWorkers, queryClient, navigate],
  );

  const snapshot = job.snapshot;
  const artifactFocusKey =
    snapshot?.artifacts
      .map((a) => `${a.artifact_id}:${a.latest_version}:${a.artifact_type}`)
      .join("|") ?? "";

  useEffect(() => {
    if (!snapshot) return;
    if (snapshot.state !== prevWorkflowState.current) {
      userPanelOverride.current = false;
      prevWorkflowState.current = snapshot.state;
    }
    const next = shouldAutoFocusWorkPanel(snapshot, panelId, userPanelOverride.current);
    if (!next) return;
    if (chatLayout) {
      userPanelOverride.current = true;
    }
    openArtifact(next);
  }, [snapshot, artifactFocusKey, panelId, openArtifact, chatLayout]);

  if (job.isLoading) {
    return <Skeleton />;
  }

  if (job.pageError && "code" in job.pageError) {
    const p = job.pageError as Problem;
    if (p.status === 403 && p.code !== "seat_not_active" && p.code !== "kill_switch_active") {
      return (
        <main style={{ padding: 40 }}>
          <RefusalNotice title={p.title} detail={p.detail} />
        </main>
      );
    }
    if (p.status === 404) {
      return (
        <main style={{ padding: 40 }}>
          <RefusalNotice title={p.title ?? "Not found"} detail={p.detail} />
        </main>
      );
    }
  }

  if (!snapshot) {
    return (
      <main style={{ padding: 40 }}>
        <RefusalNotice title="Can't open this job" detail="It may not exist or you may not take part in it." />
      </main>
    );
  }

  const rawNotice = snapshot.seat_notice;
  const seatNotice =
    rawNotice?.kind && rawNotice.text
      ? { kind: rawNotice.kind, text: rawNotice.text }
      : null;
  let composerDisabled: string | undefined;
  if (isJobClosed(snapshot)) composerDisabled = closedComposerMessage;
  else if (seatNotice) composerDisabled = seatNotice.text;
  else if (seatBlock) composerDisabled = seatBlock.title;
  else composerDisabled = composerBlockedForPoLoop(snapshot);

  const documentsOpen = Boolean(panelId);
  const layoutClass = chatLayout ? styles.jobLayoutChatOnly : styles.jobLayout;

  const workPanel = (
    <WorkPanel
      instanceId={instanceId}
      snapshot={snapshot}
      panelArtifactId={panelId}
      onSelectArtifact={selectWorkPanelArtifact}
      onSendRfqs={job.sendRfqs}
      agentBusy={Boolean(
        job.awaitingTurnId ||
          job.streamingTurnId ||
          (job.toolActivity && job.toolActivity.state !== "completed"),
      )}
      onClose={documentsOpen ? closeDocuments : undefined}
    />
  );

  return (
    <div className={layoutClass}>
      <Conversation
        snapshot={snapshot}
        streamingTurnId={job.streamingTurnId}
        awaitingTurnId={job.awaitingTurnId}
        deltas={job.deltas}
        toolActivity={job.toolActivity}
        bannerMode={job.bannerMode}
        syncCount={job.syncCount}
        composerDisabledReason={composerDisabled}
        seatNotice={seatNotice}
        initialComposerText={getComposerDraft(instanceId)}
        onComposerTextChange={(t) => setComposerDraft(instanceId, t)}
        onSend={onSend}
        onDecide={job.decide}
        onOpenArtifact={openArtifact}
        onLoadOlder={() => void job.loadOlderTurns()}
        showLoadOlder={snapshot.turns.length >= 50}
        chatLayout={chatLayout}
        documentCount={snapshot.artifacts.length}
        documentsOpen={documentsOpen}
        onToggleDocuments={() => {
          if (documentsOpen) closeDocuments();
          else if (snapshot.artifacts[0]) openArtifact(snapshot.artifacts[0].artifact_id);
        }}
      />
      {chatLayout ? (
        <>
          {documentsOpen && (
            <button
              type="button"
              className={styles.drawerBackdrop}
              aria-label="Close documents"
              onClick={closeDocuments}
            />
          )}
          <div className={[styles.workPanelDrawer, documentsOpen ? styles.workPanelDrawerOpen : ""].join(" ")}>
            {workPanel}
          </div>
        </>
      ) : (
        workPanel
      )}
      {composerProblem && (
        <div style={{ position: "fixed", bottom: 16, left: 16, right: 16, maxWidth: 480, zIndex: 50 }}>
          <ProblemNotice problem={composerProblem} />
        </div>
      )}
    </div>
  );
}
