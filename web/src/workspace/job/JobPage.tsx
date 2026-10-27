import { useCallback, useState } from "react";
import { useParams, useSearchParams } from "react-router";
import { ApiProblemError } from "../../api/problems";
import {
  ProblemNotice,
  RefusalNotice,
  Skeleton,
  problemNotice,
} from "../../components";
import type { Problem } from "../../api/problems";
import { clearComposerDraft, getComposerDraft, setComposerDraft } from "./composerDrafts";
import { Conversation } from "./Conversation";
import { useJobPage } from "./useJobPage";
import { WorkPanel } from "./WorkPanel";
import styles from "./job.module.css";

export default function JobPage() {
  const { id: instanceId = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const panelId = searchParams.get("panel");

  const job = useJobPage(instanceId);
  const [composerProblem, setComposerProblem] = useState<Problem | null>(null);
  const [seatBlock, setSeatBlock] = useState<Problem | null>(null);

  const openArtifact = useCallback(
    (artifactId: string) => {
      setSearchParams({ panel: artifactId });
    },
    [setSearchParams],
  );

  const onSend = useCallback(
    async (text: string, clientTurnId: string) => {
      setComposerProblem(null);
      setSeatBlock(null);
      try {
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
    [instanceId, job],
  );

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

  if (!job.snapshot) {
    return (
      <main style={{ padding: 40 }}>
        <RefusalNotice title="Can't open this job" detail="It may not exist or you may not take part in it." />
      </main>
    );
  }

  const rawNotice = job.snapshot.seat_notice;
  const seatNotice =
    rawNotice?.kind && rawNotice.text
      ? { kind: rawNotice.kind, text: rawNotice.text }
      : null;
  let composerDisabled: string | undefined;
  if (seatNotice) composerDisabled = seatNotice.text;
  else if (seatBlock) composerDisabled = seatBlock.title;

  return (
    <div className={styles.jobLayout}>
      <Conversation
        snapshot={job.snapshot}
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
        showLoadOlder={job.snapshot.turns.length >= 50}
      />
      <WorkPanel
        instanceId={instanceId}
        snapshot={job.snapshot}
        panelArtifactId={panelId}
        onSelectArtifact={openArtifact}
        onSendRfqs={job.sendRfqs}
      />
      {composerProblem && (
        <div style={{ position: "fixed", bottom: 16, left: 16, right: 16, maxWidth: 480, zIndex: 10 }}>
          <ProblemNotice problem={composerProblem} />
        </div>
      )}
    </div>
  );
}
