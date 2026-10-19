import styles from "./Skeleton.module.css";

export function Skeleton({ lines = 4 }: { lines?: number }) {
  return (
    <div className={styles.wrap} aria-busy="true" aria-label="Loading">
      <span className={`${styles.line} ${styles.short}`} />
      {Array.from({ length: lines - 1 }, (_, i) => (
        <span key={i} className={styles.block} style={i === lines - 2 ? { width: "70%" } : undefined} />
      ))}
    </div>
  );
}
