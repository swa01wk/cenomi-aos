import type { InstanceSnapshot } from "./jobStreamReducer";
import { WorkPanelResendRfqs } from "./WorkPanelResendRfqs";
import { WorkPanelSendRfqs } from "./WorkPanelSendRfqs";
import { WorkPanelSharedAttachments } from "./WorkPanelSharedAttachments";
import { showResendRfqsBar } from "./workResendRfqs";
import { showSendRfqsBar } from "./workSendRfqs";
import styles from "./job.module.css";

export function WorkPanelRfqDock({
  snapshot,
  onSend,
  onResend,
  onUpload,
  onRemove,
}: {
  snapshot: InstanceSnapshot;
  onSend?: () => Promise<void>;
  onResend?: (supplierIds?: string[]) => Promise<void>;
  onUpload?: (file: File) => Promise<void>;
  onRemove?: (attachmentId: string) => Promise<void>;
}) {
  return (
    <div className={styles.workDock} role="region" aria-label="Send options">
      {onUpload && onRemove ? (
        <WorkPanelSharedAttachments snapshot={snapshot} compact onUpload={onUpload} onRemove={onRemove} />
      ) : null}
      {onSend && showSendRfqsBar(snapshot) ? (
        <WorkPanelSendRfqs snapshot={snapshot} compact onSend={onSend} />
      ) : null}
      {onResend && showResendRfqsBar(snapshot) ? (
        <WorkPanelResendRfqs snapshot={snapshot} onResend={onResend} />
      ) : null}
    </div>
  );
}
