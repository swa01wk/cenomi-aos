import { Link } from "react-router";
import styles from "./JobClosedBanner.module.css";

export function JobClosedBanner({ instanceId }: { instanceId: string }) {
  return (
    <div className={styles.banner} role="status" aria-live="polite">
      <div className={styles.iconWrap} aria-hidden>
        <span className={styles.icon}>✓</span>
      </div>
      <div className={styles.copy}>
        <p className={styles.title}>Job complete</p>
        <p className={styles.detail}>
          <span className={styles.jobId}>{instanceId}</span> is closed. The purchase path finished — open documents on
          the right or scroll above for the full history.
        </p>
        <Link
          to={`/workspace?repeat=${encodeURIComponent(instanceId)}`}
          className={styles.repeatLink}
        >
          Repeat this order
        </Link>
      </div>
    </div>
  );
}
