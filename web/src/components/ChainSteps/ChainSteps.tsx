import type { ReactNode } from "react";
import type { PublishRequestPart } from "../types";
import { when } from "../../lib/ui";
import styles from "./ChainSteps.module.css";

const PART_LABEL: Record<PublishRequestPart["part"], string> = {
  policies: "Policies",
  seats_and_workflows: "Seats and workflows",
};

export function ChainSteps({
  parts,
  renderPartActions,
  formatPerson,
}: {
  parts: PublishRequestPart[];
  renderPartActions?: (part: PublishRequestPart, index: number) => ReactNode;
  formatPerson?: (personId: string) => string;
}) {
  const displayPart = (p: PublishRequestPart) => {
    const bits: string[] = [PART_LABEL[p.part], p.role, p.status];
    if (p.status !== "open" && p.by) bits.push(formatPerson ? formatPerson(p.by) : p.by);
    if (p.status !== "open" && p.at) bits.push(when(p.at));
    return bits.join(" · ");
  };

  return (
    <ol className={styles.list} aria-label="Approval chain">
      {parts.map((p, i) => (
        <li key={`${p.part}-${i}`} className={styles.row}>
          <span className={`${styles.step} ${styles[p.status]}`}>{i + 1} · {displayPart(p)}</span>
          {renderPartActions?.(p, i)}
        </li>
      ))}
    </ol>
  );
}
