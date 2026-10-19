import type { SeatState } from "../types";
import styles from "./LifecycleSteps.module.css";

export type LifecycleStep = {
  state: SeatState;
  status: "done" | "current" | "next";
  meta?: string;
};

export function LifecycleSteps({ steps }: { steps: LifecycleStep[] }) {
  return (
    <ol className={styles.list} aria-label="Seat lifecycle">
      {steps.map((s) => (
        <li
          key={s.state}
          className={`${styles.step} ${styles[s.status]}`}
          aria-current={s.status === "current" ? "step" : undefined}
        >
          <span className={styles.label}>{s.state}</span>
          {s.meta && <p className={styles.meta}>{s.meta}</p>}
        </li>
      ))}
    </ol>
  );
}
