import { useRef, useState } from "react";
import { ApiProblemError } from "../../api/problems";
import { Button } from "../../components";
import type { InstanceSnapshot } from "./jobStreamReducer";
import { formatAttachmentSize, showSharedAttachmentsBar } from "./workSharedAttachments";
import styles from "./job.module.css";

type SharedAttachment = NonNullable<InstanceSnapshot["shared_attachments"]>[number];

export function WorkPanelSharedAttachments({
  snapshot,
  onUpload,
  onRemove,
  compact = false,
}: {
  snapshot: InstanceSnapshot;
  onUpload: (file: File) => Promise<void>;
  onRemove: (attachmentId: string) => Promise<void>;
  compact?: boolean;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!showSharedAttachmentsBar(snapshot)) return null;

  const items: SharedAttachment[] = snapshot.shared_attachments ?? [];

  const pickFile = () => inputRef.current?.click();

  const onFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file || busy) return;
    setBusy(true);
    setError(null);
    try {
      await onUpload(file);
    } catch (err) {
      const detail =
        err instanceof ApiProblemError
          ? err.problem.detail || err.problem.title
          : err instanceof Error
            ? err.message
            : String(err);
      setError(detail);
    } finally {
      setBusy(false);
    }
  };

  const remove = async (attachmentId: string) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await onRemove(attachmentId);
    } catch (err) {
      const detail =
        err instanceof ApiProblemError
          ? err.problem.detail || err.problem.title
          : err instanceof Error
            ? err.message
            : String(err);
      setError(detail);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className={[styles.workSharedAttachments, compact ? styles.workSharedAttachmentsCompact : ""]
        .filter(Boolean)
        .join(" ")}
      role="region"
      aria-label="Shared RFQ attachments"
    >
      {!compact ? (
        <p className={styles.workSharedAttachmentsText}>
          Add a file once — it is included on every RFQ when you approve and send (up to 2 MB each).
        </p>
      ) : (
        <span className={styles.workSharedAttachmentsCompactLabel} title="Included on every RFQ when you send">
          Shared files
        </span>
      )}
      <input
        ref={inputRef}
        type="file"
        className={styles.workSharedAttachmentsInput}
        onChange={(e) => void onFileChange(e)}
        aria-hidden
        tabIndex={-1}
      />
      <Button
        type="button"
        variant="secondary"
        size="workspace"
        disabledReason={busy ? "Uploading" : undefined}
        onClick={pickFile}
      >
        {busy ? "Working…" : "Upload attachment"}
      </Button>
      {items.length > 0 ? (
        <ul className={styles.workSharedAttachmentsList}>
          {items.map((a) => (
            <li key={a.attachment_id} className={styles.workSharedAttachmentsItem}>
              <span className={styles.workSharedAttachmentsName} title={a.filename}>
                {a.filename}
              </span>
              <span className={styles.workSharedAttachmentsMeta}>{formatAttachmentSize(a.size_bytes)}</span>
              <button
                type="button"
                className={styles.workSharedAttachmentsRemove}
                disabled={busy}
                onClick={() => void remove(a.attachment_id)}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      {error ? <p className={styles.workSharedAttachmentsError}>{error}</p> : null}
    </div>
  );
}
