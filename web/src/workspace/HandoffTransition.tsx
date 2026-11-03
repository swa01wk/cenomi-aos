import styles from "./handoffTransition.module.css";

/** Inline handoff status — stays in the chat column; no full-screen block. */
export function HandoffTransition({
  fromInitials,
  toName,
  toInitials,
}: {
  fromName: string;
  fromTitle: string;
  fromInitials: string;
  toName: string;
  toTitle: string;
  toInitials: string;
}) {
  const first = toName.split(/\s+/)[0] ?? toName;

  return (
    <div className={styles.banner} role="status" aria-live="polite">
      <span className={styles.avatars} aria-hidden="true">
        <span className={[styles.avatar, styles.avatarFrom].join(" ")}>{fromInitials}</span>
        <span className={styles.arrow} />
        <span className={[styles.avatar, styles.avatarTo].join(" ")}>{toInitials}</span>
      </span>
      <span className={styles.text}>
        Connecting you to <strong>{first}</strong>
        <span className={styles.dots} aria-hidden="true">
          <span className={styles.dot} />
          <span className={styles.dot} />
          <span className={styles.dot} />
        </span>
      </span>
    </div>
  );
}
