import { Button } from "../Button/Button";
import styles from "./ConflictNotice.module.css";

export function ConflictNotice({
  title,
  detail,
  onReload,
  reloadLabel = "Reload",
}: {
  title: string;
  detail?: string;
  onReload?: () => void;
  reloadLabel?: string;
}) {
  return (
    <div className={styles.banner} role="alert">
      <p className={styles.title}>{title}</p>
      {detail && <p className={styles.detail}>{detail}</p>}
      {onReload && (
        <Button variant="secondary" size="console" onClick={onReload}>
          {reloadLabel}
        </Button>
      )}
    </div>
  );
}
