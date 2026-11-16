import { ReplyIcon } from "../icons";
import styles from "./job.module.css";

export function ReplyQuoteBar({
  authorName,
  excerpt,
  onDismiss,
}: {
  authorName: string;
  excerpt: string;
  onDismiss: () => void;
}) {
  return (
    <div className={styles.composerQuote} role="region" aria-label={`Replying to ${authorName}`}>
      <ReplyIcon size={14} />
      <span className={styles.composerQuoteBar} aria-hidden="true" />
      <div className={styles.composerQuoteBody}>
        <span className={styles.composerQuoteAuthor}>{authorName}</span>
        <p className={styles.composerQuoteText}>{excerpt}</p>
      </div>
      <button type="button" className={styles.composerQuoteDismiss} onClick={onDismiss} aria-label="Cancel reply">
        ×
      </button>
    </div>
  );
}
