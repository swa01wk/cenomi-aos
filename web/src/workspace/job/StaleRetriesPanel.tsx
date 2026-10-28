import { useState } from "react";
import type { components } from "../../api/schema";
import { DecisionCard } from "./DecisionCard";

type ArtifactSummary = components["schemas"]["ArtifactSummary"];
import styles from "./StaleRetriesPanel.module.css";

type PendingItem = components["schemas"]["PendingItem"];

export function StaleRetriesPanel({
  retries,
  artifacts,
  onDecide,
}: {
  retries: PendingItem[];
  artifacts: ArtifactSummary[];
  onDecide: (input: {
    pendingId: string;
    value: string;
    artifactVersion?: number;
    note?: string;
    selection?: string[];
    idempotencyKey: string;
  }) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  if (retries.length === 0) return null;

  const stepNames = retries.map((r) => r.title.replace(/^Retry:\s*/i, "").trim()).filter(Boolean);

  return (
    <details
      className={styles.wrap}
      open={open}
      onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}
    >
      <summary className={styles.summary}>
        {retries.length === 1
          ? `Optional: retry ${stepNames[0] ?? "an earlier step"}`
          : `${retries.length} optional retries from earlier steps`}
      </summary>
      <div className={styles.list}>
        {retries.map((pending) => {
          const artifact = artifacts.find((a) => a.artifact_id === pending.artifact_ref?.artifact_id);
          return (
            <DecisionCard
              key={pending.pending_id}
              pending={pending}
              view={artifact?.view}
              onApprove={onDecide}
              variant="retry"
            />
          );
        })}
      </div>
    </details>
  );
}
