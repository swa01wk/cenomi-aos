import { Button } from "../Button/Button";
import styles from "./ErrorBanner.module.css";

export function ErrorBanner({
  title,
  detail,
  traceId,
  onRetry,
}: {
  title: string;
  detail?: string;
  traceId?: string;
  onRetry?: () => void;
}) {
  return (
    <div className={styles.banner} role="alert">
      <p className={styles.title}>{title}</p>
      {detail && <p className={styles.detail}>{detail}</p>}
      {traceId && (
        <p className={styles.trace}>
          trace <span>{traceId}</span>
        </p>
      )}
      {onRetry && (
        <Button variant="secondary" onClick={onRetry}>
          Retry
        </Button>
      )}
    </div>
  );
}
