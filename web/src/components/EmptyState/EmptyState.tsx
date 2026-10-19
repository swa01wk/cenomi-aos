import type { ReactNode } from "react";
import styles from "./EmptyState.module.css";

export function EmptyState({ title, nextStep, action }: { title: string; nextStep?: string; action?: ReactNode }) {
  return (
    <div className={styles.root}>
      <p className={styles.title}>{title}</p>
      {nextStep && <p className={styles.next}>{nextStep}</p>}
      {action}
    </div>
  );
}
