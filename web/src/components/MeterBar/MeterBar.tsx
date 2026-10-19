import styles from "./MeterBar.module.css";

export function MeterBar({
  label,
  value,
  limit,
  showValues = true,
}: {
  label: string;
  value: number;
  limit: number;
  showValues?: boolean;
}) {
  const pct = limit > 0 ? Math.min(100, (value / limit) * 100) : 0;
  return (
    <div className={styles.root}>
      <span className={styles.label}>{label}</span>
      <div className={styles.track} role="meter" aria-valuenow={value} aria-valuemin={0} aria-valuemax={limit} aria-label={label}>
        <div className={styles.fill} style={{ width: `${pct}%` }} />
      </div>
      {showValues && (
        <span className={styles.meta}>
          {value} / {limit}
        </span>
      )}
    </div>
  );
}
