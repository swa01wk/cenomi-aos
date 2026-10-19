import type { ReactNode } from "react";
import type { PublishRequestPart } from "../types";
import { when } from "../../lib/ui";
import styles from "./ChainSteps.module.css";

const PART_LABEL: Record<PublishRequestPart["part"], string> = {
  policies: "Policies",
  seats_and_workflows: "Seats and workflows",
};

function partSummary(p: PublishRequestPart): string {
  const label = PART_LABEL[p.part];
  const bits = [`${label}`, p.role, p.status];
  if (p.status === "approved" && p.by && p.at) {
    bits.push(`by ${p.by}`, when(p.at));
  } else if (p.status === "rejected" && p.by && p.at) {
    bits.push(`by ${p.by}`, when(p.at));
  }
  return bits.join(" · ");
}

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
    const label = PART_LABEL[p.part];
    const role = p.role;
    const status = p.status;
    const byName = p.by ? (formatPerson ? formatPerson(p.by) : p.by) : null;
    if (p.status === "approved" && byName && p.at) {
      return `${label} · ${role} · ${status} · ${byName} · ${when(p.at)}`;
    }
    if (p.status === "rejected" && byName && p.at) {
      return `${label} · ${role} · ${status} · ${byName} · ${when(p.at)}`;
    }
    return partSummary(p);
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
