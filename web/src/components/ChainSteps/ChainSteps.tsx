import type { PublishRequestPart } from "../types";
import styles from "./ChainSteps.module.css";

const PART_LABEL: Record<PublishRequestPart["part"], string> = {
  policies: "Policies",
  seats_and_workflows: "Seats and workflows",
};

export function ChainSteps({ parts }: { parts: PublishRequestPart[] }) {
  return (
    <ol className={styles.list} aria-label="Approval chain">
      {parts.map((p, i) => (
        <li key={`${p.part}-${i}`} className={`${styles.step} ${styles[p.status]}`}>
          {i + 1} · {PART_LABEL[p.part]} · {p.role} · {p.status}
        </li>
      ))}
    </ol>
  );
}
