import styles from "./ConnectionBanner.module.css";

export function ConnectionBanner({
  mode,
  updateCount,
}: {
  mode: "reconnecting" | "synced";
  updateCount?: number;
}) {
  const text =
    mode === "reconnecting"
      ? "Reconnecting… showing the last known state"
      : `Back in sync · ${updateCount ?? 0} updates applied`;

  return (
    <div role="status" className={`${styles.banner} ${styles[mode]}`}>
      <span className={styles.dot} aria-hidden="true" />
      {text}
    </div>
  );
}
