import { Button } from "../Button/Button";
import styles from "./ErrorBanner.module.css";

function metaLine(status?: number, traceId?: string): string | undefined {
  const hasStatus = status != null;
  const hasTrace = Boolean(traceId);
  if (!hasStatus && !hasTrace) return undefined;
  if (hasStatus && hasTrace) return `${status} · trace ${traceId}`;
  if (hasStatus) return String(status);
  return `trace ${traceId}`;
}

export function ErrorBanner({
  title,
  detail,
  status,
  traceId,
  onRetry,
}: {
  title: string;
  detail?: string;
  status?: number;
  traceId?: string;
  onRetry?: () => void;
}) {
  const meta = metaLine(status, traceId);

  return (
    <div className={styles.banner} role="alert">
      <p className={styles.title}>{title}</p>
      {detail && <p className={styles.detail}>{detail}</p>}
      {meta && <p className={styles.meta}>{meta}</p>}
      {onRetry && (
        <Button variant="secondary" className={styles.action} onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}
