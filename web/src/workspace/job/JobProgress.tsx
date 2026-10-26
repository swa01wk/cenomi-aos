import type { Stage } from "../../components/types";
import styles from "./job.module.css";

/** "Shortlisting · stage 2 of 8", or null once no stage is current. */
export function stageBadgeText(stages: Stage[]): string | null {
  const index = stages.findIndex((s) => s.status === "current");
  if (index < 0) return null;
  return `${stages[index]!.label} · stage ${index + 1} of ${stages.length}`;
}

/** One segment per workflow stage: done, current or next. */
export function JobProgress({ stages }: { stages: Stage[] }) {
  return (
    <ol className={styles.progress} aria-label="Workflow stages" style={{ gridTemplateColumns: `repeat(${stages.length || 1}, minmax(0, 1fr))` }}>
      {stages.map((s) => (
        <li
          key={s.state}
          className={`${styles.segment} ${styles[`segment_${s.status}`]}`}
          aria-current={s.status === "current" ? "step" : undefined}
          title={s.label}
        >
          <span className="ws-sr-only">
            {s.label}
            {s.status === "done" ? ", done" : s.status === "current" ? ", current" : ""}
          </span>
        </li>
      ))}
    </ol>
  );
}
