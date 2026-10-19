import type { ToolActivity as ToolActivityType } from "../types";
import styles from "./ToolActivity.module.css";

const STATE_WORD: Record<ToolActivityType["state"], string> = {
  requested: "requested",
  allowed: "allowed",
  denied: "denied",
  completed: "completed",
  failed: "failed",
};

export function ToolActivity({ activity }: { activity: ToolActivityType }) {
  return (
    <span className={styles.row}>
      <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" className={styles.icon} strokeWidth="1.6" aria-hidden="true">
        <circle cx="6" cy="6" r="4" />
        <path d="M9 9l3 3" />
      </svg>
      {activity.label} · {STATE_WORD[activity.state]}
    </span>
  );
}
