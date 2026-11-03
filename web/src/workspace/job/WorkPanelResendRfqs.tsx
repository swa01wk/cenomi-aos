import { useState } from "react";
import type { InstanceSnapshot } from "./jobStreamReducer";
import { rfqSupplierTabs } from "./workResendRfqs";
import styles from "./job.module.css";

export function WorkPanelResendRfqs({
  snapshot,
  onResend,
}: {
  snapshot: InstanceSnapshot;
  onResend: (supplierIds?: string[]) => Promise<void>;
}) {
  const tabs = rfqSupplierTabs(snapshot);
  const [busy, setBusy] = useState(false);
  const run = async (supplierIds?: string[]) => {
    setBusy(true);
    try {
      await onResend(supplierIds);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={styles.workResendBlock}>
      <details className={styles.workResendDetails}>
        <summary className={styles.workResendSummary}>About resend routing</summary>
        <p className={styles.workResendHelp}>
          Resend uses the current RFQ text and goes out through the real mail relay. For live demos, RFQs also land in
          the Gmail inbox we poll (see SMTP_USERNAME). Reply there in the thread whose subject includes this job id
          (e.g. [QQ-0072]) or the iPhone RFQ subject — not only on the Webknot ERP address shown in the locked To field.
        </p>
      </details>
      <div className={styles.workResendActions}>
        <button type="button" className="btn primary" disabled={busy} onClick={() => run()}>
          Resend to all
        </button>
        {tabs.map((t) => (
          <button
            key={t.supplierId}
            type="button"
            className="btn"
            disabled={busy}
            onClick={() => run([t.supplierId])}
          >
            Resend · {t.label}
          </button>
        ))}
      </div>
    </div>
  );
}
