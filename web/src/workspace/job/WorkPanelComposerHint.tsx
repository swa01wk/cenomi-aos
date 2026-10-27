import { useEffect, useMemo, useState } from "react";
import { Button } from "../../components";
import type { InstanceSnapshot } from "./jobStreamReducer";
import {
  composerHintCopy,
  composerHintDismissed,
  composerHintStorageKey,
  dismissComposerHint,
  messageComposerArtifacts,
} from "./workComposerHint";
import styles from "./job.module.css";

export function WorkPanelComposerHint({
  instanceId,
  snapshot,
  activeArtifactId,
  onOpenDraft,
}: {
  instanceId: string;
  snapshot: InstanceSnapshot;
  activeArtifactId: string;
  onOpenDraft: (artifactId: string) => void;
}) {
  const drafts = useMemo(() => messageComposerArtifacts(snapshot.artifacts), [snapshot.artifacts]);
  const storageKey = useMemo(
    () => (drafts.length ? composerHintStorageKey(instanceId, snapshot.artifacts) : ""),
    [drafts.length, instanceId, snapshot.artifacts],
  );
  const [dismissed, setDismissed] = useState(() => (storageKey ? composerHintDismissed(storageKey) : true));

  useEffect(() => {
    if (!storageKey) return;
    setDismissed(composerHintDismissed(storageKey));
  }, [storageKey]);

  const viewingDraft = drafts.some((a) => a.artifact_id === activeArtifactId);

  useEffect(() => {
    if (!viewingDraft || !storageKey) return;
    dismissComposerHint(storageKey);
    setDismissed(true);
  }, [viewingDraft, storageKey]);

  if (!drafts.length || dismissed) return null;

  const stageLabel = snapshot.stages.find((s) => s.status === "current")?.label;
  const firstId = drafts[0]!.artifact_id;

  return (
    <div className={styles.workComposerHint} role="status" aria-live="polite">
      <p className={styles.workComposerHintText}>
        {composerHintCopy(drafts.length, stageLabel, snapshot.state)}
      </p>
      <div className={styles.workComposerHintActions}>
        <Button type="button" variant="primary" size="workspace" onClick={() => onOpenDraft(firstId)}>
          {drafts.length === 1 ? "Open draft" : "Open drafts"}
        </Button>
        <button
          type="button"
          className={styles.workComposerHintDismiss}
          onClick={() => {
            dismissComposerHint(storageKey);
            setDismissed(true);
          }}
        >
          Dismiss
        </button>
      </div>
    </div>
  );
}
