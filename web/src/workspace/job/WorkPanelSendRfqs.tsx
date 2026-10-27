import { useMemo, useState } from "react";
import { ApiProblemError } from "../../api/problems";
import { Button } from "../../components";
import type { InstanceSnapshot } from "./jobStreamReducer";
import { messageComposerArtifacts } from "./workComposerHint";
import { sendRfqsCopy, showSendRfqsBar } from "./workSendRfqs";
import styles from "./job.module.css";

export function WorkPanelSendRfqs({
  snapshot,
  onSend,
}: {
  snapshot: InstanceSnapshot;
  onSend: () => Promise<void>;
}) {
  const drafts = useMemo(() => messageComposerArtifacts(snapshot.artifacts), [snapshot.artifacts]);
  const visible = showSendRfqsBar(snapshot);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!visible) return null;

  const send = async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await onSend();
      setError(null);
    } catch (e) {
      const detail =
        e instanceof ApiProblemError ? e.problem.detail || e.problem.title : e instanceof Error ? e.message : String(e);
      setError(detail);
      if (e instanceof ApiProblemError && e.problem.status === 409 && /sent/i.test(detail)) {
        setError(`${detail} Reload the job; the stage may already have moved on.`);
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={styles.workSendRfqs} role="region" aria-label="Send RFQs">
      <p className={styles.workSendRfqsText}>{sendRfqsCopy(drafts.length, snapshot.state)}</p>
      <Button type="button" variant="primary" size="workspace" disabledReason={busy ? "Sending" : undefined} onClick={() => void send()}>
        {busy ? "Sending…" : snapshot.state === "awaiting_quotes" ? "Deliver emails again" : "Approve and send to suppliers"}
      </Button>
      {error ? <p className={styles.workSendRfqsError}>{error}</p> : null}
    </div>
  );
}
