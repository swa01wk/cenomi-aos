import type { Stage } from "../types";
import styles from "./StageStepper.module.css";

export function StageStepper({ stages }: { stages: Stage[] }) {
  return (
    <ol className={styles.list} aria-label="Workflow stages">
      {stages.map((s) => (
        <li
          key={s.state}
          className={`${styles.step} ${styles[s.status]}`}
          aria-current={s.status === "current" ? "step" : undefined}
        >
          {s.label}
        </li>
      ))}
    </ol>
  );
}
